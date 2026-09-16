from pathlib import Path
from shlex import quote
import json
import os
import subprocess
import sys
import pytest

from gwflow import MainPipeline, PlanError, Subpipeline, Target, execution_manifest, load, plan
from gwflow.host_execution import ATTEMPT_ALREADY_STARTED, ATTEMPT_FENCE_FAILURE, OUTPUT_CHECK_FAILURE, RECEIPT_PUBLICATION_FAILURE, execute, prepare_attempt, run_prepared, scheduler_name
from gwflow.runtime_records import current_attempt_path, read_runtime_record, receipt_path, write_execution_manifest, write_runtime_record
from test_planner import runtime_cli
from gwflow.runtime_records import job_association, job_tracking, write_tracking


def target(tmp_path, command):
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    computation = result["computations"][0]
    item = dict(computation["targets"][0], command=command)
    (tmp_path / "reads.txt").write_text("input")
    return computation, item


def test_host_execution_fences_then_receipts_success(tmp_path):
    computation, item = target(tmp_path, f"cp {tmp_path}/reads.txt {tmp_path}/results/{'x'}")
    # Use the actual declared output, not an ad-hoc product path.
    item["command"] = f"cp {tmp_path}/reads.txt {item['outputs'][0]}"
    result = execute(tmp_path, computation, item, "attempt-1")
    assert result.returncode == 0
    assert read_runtime_record(current_attempt_path(tmp_path, computation["identity"], item["name"]))["attempt"] == "attempt-1"
    receipt = read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "attempt-1"))
    assert receipt["outputs"][0]["path"] == item["outputs"][0]
    assert result.stdout.exists() and result.stderr.exists()


def test_failed_payload_and_missing_output_do_not_publish_receipts(tmp_path):
    computation, item = target(tmp_path, "true; exit 29")
    failed = execute(tmp_path, computation, item, "attempt-1")
    assert failed.returncode == 29
    assert read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "attempt-1")) is None
    computation, item = target(tmp_path, "true")
    missing = execute(tmp_path, computation, item, "attempt-2")
    assert missing.returncode == OUTPUT_CHECK_FAILURE
    assert read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "attempt-2")) is None


def test_receipt_publication_failure_fails_the_job(tmp_path):
    computation, item = target(tmp_path, "true")
    item["command"] = f"cp {tmp_path}/reads.txt {item['outputs'][0]}"
    path = receipt_path(tmp_path, computation["identity"], item["name"], "attempt-3")
    request = prepare_attempt(tmp_path, computation, item, "attempt-3")
    path.mkdir()
    result = run_prepared(request)
    assert result.returncode == RECEIPT_PUBLICATION_FAILURE
    assert path.is_dir()


def test_replacement_attempt_remains_selected_after_payload_failure(tmp_path):
    computation, item = target(tmp_path, "true; exit 3")
    execute(tmp_path, computation, item, "attempt-1")
    execute(tmp_path, computation, item, "attempt-2")
    assert read_runtime_record(current_attempt_path(tmp_path, computation["identity"], item["name"]))["attempt"] == "attempt-2"


def test_gwf_errexit_stops_payload_before_a_later_success_can_hide_failure(tmp_path):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"false; printf misleading-success > {quote(item['outputs'][0])}"
    result = execute(tmp_path, computation, item, "errexit")
    assert result.returncode != 0
    assert not Path(item["outputs"][0]).exists()
    assert read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "errexit")) is None


def test_gwf_does_not_enable_pipefail_and_uses_the_computation_work_directory(tmp_path):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"false | true; pwd > {quote(item['outputs'][0])}"
    result = execute(tmp_path, computation, item, "pipeline")
    assert result.returncode == 0
    assert Path(item["outputs"][0]).read_text().strip() == computation["work_dir"]


def test_attempt_tokens_cannot_be_reexecuted_or_overwrite_history(tmp_path):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"printf first > {quote(item['outputs'][0])}; printf original-log"
    result = execute(tmp_path, computation, item, "once")
    assert result.returncode == 0
    item["command"] = f"printf replayed > {quote(item['outputs'][0])}"
    with pytest.raises(PlanError, match="attempt.*already"):
        execute(tmp_path, computation, item, "once")
    assert Path(item["outputs"][0]).read_text() == "first"
    assert result.stdout.read_text() == "original-log"


def worker(request):
    return subprocess.run([sys.executable, "-m", "gwflow.host_execution", str(request)], capture_output=True, text=True)


def test_delayed_old_worker_cannot_reselect_itself_or_modify_outputs(tmp_path):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"printf worker-output > {quote(item['outputs'][0])}"
    old_request = prepare_attempt(tmp_path, computation, item, "old")
    new_request = prepare_attempt(tmp_path, computation, item, "new")
    old = worker(old_request)
    assert old.returncode == ATTEMPT_FENCE_FAILURE, old.stderr
    assert not Path(item["outputs"][0]).exists()
    assert read_runtime_record(current_attempt_path(tmp_path, computation["identity"], item["name"]))["attempt"] == "new"
    new = worker(new_request)
    assert new.returncode == 0, new.stderr
    assert Path(item["outputs"][0]).read_text() == "worker-output"
    assert receipt_path(tmp_path, computation["identity"], item["name"], "new").is_file()
    assert not receipt_path(tmp_path, computation["identity"], item["name"], "old").exists()


def test_replayed_worker_is_rejected_without_repeating_payload(tmp_path):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"printf one-execution >> {quote(item['outputs'][0])}; printf original-log"
    request = prepare_attempt(tmp_path, computation, item, "once")
    assert worker(request).returncode == 0
    replay = worker(request)
    assert replay.returncode == ATTEMPT_ALREADY_STARTED
    assert Path(item["outputs"][0]).read_text() == "one-execution"
    assert (request.parent / "stdout.log").read_text() == "original-log"


def test_host_environment_and_gwf_target_name_reach_real_bash(tmp_path, monkeypatch):
    monkeypatch.setenv("GWFLOW_TEST_HOST_VALUE", "inherited environment")
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f'printf "%s\\n%s\\n" "$GWFLOW_TEST_HOST_VALUE" "$GWF_TARGET_NAME" > {quote(item["outputs"][0])}; printf problem >&2'
    request = prepare_attempt(tmp_path, computation, item, "environment")
    result = worker(request)
    assert result.returncode == 0, result.stderr
    assert Path(item["outputs"][0]).read_text().splitlines() == ["inherited environment", scheduler_name(computation["identity"], item["name"], "environment")]
    assert (request.parent / "stderr.log").read_text() == "problem"


def test_failed_durable_fence_never_starts_the_payload(tmp_path, monkeypatch):
    computation, item = target(tmp_path, "placeholder")
    output = Path(item["outputs"][0])
    output.parent.mkdir(parents=True)
    output.write_text("old result")
    item["command"] = f"printf overwritten > {quote(str(output))}"
    replace = os.replace

    def fail_selection(source, destination):
        if Path(destination).name == "current.json":
            raise OSError("injected fence failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_selection)
    with pytest.raises(OSError, match="injected fence failure"):
        execute(tmp_path, computation, item, "fence-failure")
    assert output.read_text() == "old result"
    assert not receipt_path(tmp_path, computation["identity"], item["name"], "fence-failure").exists()


def test_post_replacement_receipt_sync_failure_fails_the_compute_job(tmp_path, monkeypatch):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"cp {quote(str(tmp_path / 'reads.txt'))} {quote(item['outputs'][0])}"
    request = prepare_attempt(tmp_path, computation, item, "sync-failure")
    replace, fsync = os.replace, os.fsync
    replaced_receipt = False

    def observe_replace(source, destination):
        nonlocal replaced_receipt
        replace(source, destination)
        replaced_receipt = Path(destination).name == "receipt.json"

    def fail_after_replace(fd):
        if replaced_receipt:
            raise OSError("injected receipt sync failure")
        fsync(fd)

    monkeypatch.setattr(os, "replace", observe_replace)
    monkeypatch.setattr(os, "fsync", fail_after_replace)
    result = run_prepared(request)
    assert result.returncode == RECEIPT_PUBLICATION_FAILURE
    assert "injected receipt sync failure" in result.stderr.read_text()


def test_failed_after_writing_preserves_payload_and_logs_but_no_success_receipt(tmp_path):
    computation, item = target(tmp_path, "placeholder")
    item["command"] = f"printf partial > {quote(item['outputs'][0])}; printf before-failure; printf problem >&2; exit 31"
    request = prepare_attempt(tmp_path, computation, item, "failed")
    result = worker(request)
    assert result.returncode == 31, result.stderr
    assert Path(item["outputs"][0]).read_text() == "partial"
    assert (request.parent / "stdout.log").read_text() == "before-failure"
    assert (request.parent / "stderr.log").read_text() == "problem"
    assert not receipt_path(tmp_path, computation["identity"], item["name"], "failed").exists()


def test_late_actual_old_success_cannot_certify_failed_replacement(tmp_path):
    (tmp_path / "reads.txt").write_text("input")
    planned = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    computation = planned["computations"][0]
    item = computation["targets"][0]
    write_execution_manifest(tmp_path, execution_manifest(planned, computation["identity"]))
    old = prepare_attempt(tmp_path, computation, item, "old")
    assert worker(old).returncode == 0
    old_receipt = receipt_path(tmp_path, computation["identity"], item["name"], "old")
    success = read_runtime_record(old_receipt)
    replacement = prepare_attempt(tmp_path, computation, item, "replacement")
    receipt_path(tmp_path, computation["identity"], item["name"], "replacement").mkdir()
    assert worker(replacement).returncode == RECEIPT_PUBLICATION_FAILURE
    # The local integration harness does not submit jobs. Seed explicit
    # authoritative tracking for this controlled expired-history fixture.
    write_tracking(tmp_path, job_tracking([job_association(computation["identity"], item["name"], "replacement", "fixture-123")]))
    write_runtime_record(old_receipt, success)
    preview = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["computations"][0]["decision"] == "execute"
    assert read_runtime_record(current_attempt_path(tmp_path, computation["identity"], item["name"]))["attempt"] == "replacement"
    assert (old.parent / "stdout.log").is_file() and (old.parent / "diagnostic.json").is_file()


def test_outputless_host_work_still_executes_and_records_an_empty_output_list(tmp_path):
    definition = MainPipeline("examples.notifications", "1", Subpipeline("examples.notifications", "1", {}, {}, lambda ctx: [Target("notify", "printf notified")]))
    planned = plan(definition, project=tmp_path)
    computation = planned["computations"][0]
    item = computation["targets"][0]
    for attempt in ("one", "two"):
        request = prepare_attempt(tmp_path, computation, item, attempt)
        assert worker(request).returncode == 0
        assert (request.parent / "stdout.log").read_text() == "notified"
        assert read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], attempt))["outputs"] == []


def test_host_demo_checks_success_and_each_job_failure_at_the_worker_boundary(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.host_execution_demo", str(tmp_path / "demo")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["scheduler_jobs_submitted"] == 0
    assert [(case["case"], case["exit"], case["receipt"]) for case in report["cases"]] == [
        ("success", 0, True), ("writes-then-fails", 31, False),
        ("missing-output", 72, False), ("publication-failure", 73, False),
    ]
