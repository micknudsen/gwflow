"""Runtime decisions graded at the maintained command boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from examples.runtime_evaluation import prepare_fixture, stamp
from gwflow.runtime import preview as preview_plan
from gwflow import execution_manifest, load, plan
from gwflow.runtime_records import current_attempt, current_attempt_path, receipt_path, success_receipt, write_execution_manifest, write_runtime_record

from test_planner import runtime_cli
from gwflow.runtime_records import association_key, job_association, job_tracking, read_tracking, write_tracking


def preview(tmp_path):
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)["computations"][0]


def decisions(report):
    return {target["name"]: target["decision"] for target in report["targets"]}


def test_missing_external_input_fails_even_when_no_outputs_exist(tmp_path):
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"absent.txt"}')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["outcome"] == "error"
    assert report["computations"] == []
    assert "producerless external input" in result.stderr
    assert not list(tmp_path.iterdir())


def test_partial_retry_preserves_successful_current_internal_work(tmp_path):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    receipt_path(tmp_path, identity, "e", "fixture-success").unlink()
    assert decisions(preview(tmp_path)) == {"a": "reuse", "b": "reuse", "c": "reuse", "d": "reuse", "e": "execute"}


def test_stale_cleaned_boundary_regenerates_real_prerequisites(tmp_path):
    planned = prepare_fixture(tmp_path)
    computation = planned["computations"][0]
    for path in computation["internal_outputs"]:
        Path(path).unlink()
    assert preview(tmp_path)["decision"] == "reuse"
    # A retained result is real, never virtual: losing it puts the entire
    # internal graph back through real-file recovery.
    Path(computation["retained_outputs"]["final"]).unlink()
    assert decisions(preview(tmp_path)) == {"a": "execute", "b": "execute", "c": "execute", "d": "execute", "e": "execute"}


@pytest.mark.parametrize("status", ["submitted", "running", "failed", "cancelled"])
def test_scheduler_precedence_propagates_to_internal_dependents(tmp_path, status):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    report = preview_plan(planned, statuses={(identity, "a"): status}, job_ids={(identity, "a"): "1234"})
    assert decisions(report["computations"][0]) == {
        "a": "attach" if status in {"submitted", "running"} else "execute",
        "b": "execute", "c": "reuse", "d": "reuse", "e": "execute",
    }
    target = next(t for t in report["computations"][0]["targets"] if t["name"] == "a")
    assert target["job_ids"] == ["1234"]


def test_failed_join_after_cleanup_does_not_consume_virtual_prerequisites(tmp_path):
    planned = prepare_fixture(tmp_path)
    computation = planned["computations"][0]
    for path in computation["internal_outputs"]:
        Path(path).unlink()
    report = preview_plan(planned, statuses={(computation["identity"], "e"): "failed"})
    assert decisions(report["computations"][0]) == {"a": "execute", "b": "execute", "c": "execute", "d": "execute", "e": "execute"}


def test_branch_local_freshness_and_real_intermediate_observations(tmp_path):
    planned = prepare_fixture(tmp_path)
    assert preview(tmp_path)["decision"] == "reuse"  # right branch times exceed left outputs
    stamp(tmp_path / "reads.txt", 25)
    assert decisions(preview(tmp_path)) == {"a": "execute", "b": "execute", "c": "reuse", "d": "reuse", "e": "execute"}
    stamp(tmp_path / "reads.txt", 10)
    a = planned["computations"][0]["targets"][0]["outputs"][0]
    stamp(a, 35)
    assert decisions(preview(tmp_path)) == {"a": "reuse", "b": "execute", "c": "reuse", "d": "reuse", "e": "execute"}


def test_equal_future_and_timestamp_preserving_edits_ignore_receipt_mtime(tmp_path):
    planned = prepare_fixture(tmp_path)
    source = tmp_path / "reads.txt"
    stamp(source, 20)  # newest input == oldest output is fresh
    assert preview(tmp_path)["decision"] == "reuse"
    source.write_text("different bytes and size")
    os.utime(source, ns=(20, 20))
    receipt = receipt_path(tmp_path, planned["computations"][0]["identity"], "a", "fixture-success")
    future = 4102444800000000000  # 2100-01-01, independent of the test runner's clock
    os.utime(receipt, ns=(future, future))
    stamp(planned["computations"][0]["retained_outputs"]["final"], future)
    assert preview(tmp_path)["decision"] == "reuse"


def complete_plan(planned):
    project = planned["project"]
    write_tracking(project, job_tracking([
        job_association(computation["identity"], target["name"], "one", str(index + 100))
        for index, (computation, target) in enumerate((c, t) for c in planned["computations"] for t in c["targets"])
    ]))
    produced = {path for c in planned["computations"] for t in c["targets"] for path in t["outputs"]}
    for computation in planned["computations"]:
        identity = computation["identity"]
        write_execution_manifest(project, execution_manifest(planned, identity))
        for target in computation["targets"]:
            for path in target["inputs"]:
                if path not in produced:
                    stamp(path, 10)
            for path in target["outputs"]:
                stamp(path, 100)
            write_runtime_record(current_attempt_path(project, identity, target["name"]), current_attempt(identity, target["name"], "one"))
            write_runtime_record(receipt_path(project, identity, target["name"], "one"), success_receipt(identity, target["name"], "one", [{"path": path, "mtime_ns": 100} for path in target["outputs"]]))


def test_whole_producer_dependencies_propagate_without_pooling_file_times(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "no-scheduler"))
    planned = plan(load("examples.whole_producer:main"), project=tmp_path)
    complete_plan(planned)
    producer = planned["main"]["occurrences"]["producer"]["identity"]
    consumer = planned["main"]["occurrences"]["consumer"]["identity"]
    producer_plan = next(c for c in planned["computations"] if c["identity"] == producer)
    slow = next(t for t in producer_plan["targets"] if t["name"] == "slow")
    stamp(slow["outputs"][0], 4102444800000000000)  # future unconsumed file is not a freshness input
    observed = preview_plan(planned, statuses={})
    assert observed["outcome"] == "ready", observed
    assert len(observed["computations"]) == 2
    assert all(c["decision"] == "reuse" for c in observed["computations"])
    for status in ("submitted", "running", "failed", "cancelled"):
        report = preview_plan(planned, statuses={(producer, "slow"): status})
        assert next(c for c in report["computations"] if c["identity"] == consumer)["decision"] == "execute"


def test_upstream_outputs_not_yet_present_are_not_producerless_errors(tmp_path):
    stamp(tmp_path / "reads.txt", 10)
    result = runtime_cli(tmp_path, "--dry-run", "examples.whole_producer:main")
    assert result.returncode == 0, result.stderr
    assert all(c["decision"] == "execute" for c in json.loads(result.stdout)["computations"])


@pytest.mark.parametrize("damage", ["missing-selection", "malformed-selection", "unsupported-receipt", "wrong-receipt-attempt"])
def test_unusable_selected_evidence_recovers_only_the_affected_path(tmp_path, damage):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    selection = current_attempt_path(tmp_path, identity, "b")
    receipt = receipt_path(tmp_path, identity, "b", "fixture-success")
    if damage == "missing-selection":
        selection.unlink()
    elif damage == "malformed-selection":
        selection.write_text('{"not": "a selection"}')
    else:
        data = json.loads(receipt.read_text())
        if damage == "unsupported-receipt":
            data["record_revision"] = 999
        else:
            data["attempt"] = "some-other-attempt"
        receipt.write_text(json.dumps(data))
    assert decisions(preview(tmp_path)) == {"a": "reuse", "b": "execute", "c": "reuse", "d": "reuse", "e": "execute"}
    report = preview_plan(planned, statuses={(identity, "b"): "running"}, job_ids={(identity, "b"): "88"})
    assert decisions(report["computations"][0])["b"] == "attach"


def test_reuse_explains_selected_and_historical_evidence_without_writing(tmp_path):
    planned = prepare_fixture(tmp_path)
    computation = planned["computations"][0]
    for path in computation["internal_outputs"]:
        Path(path).unlink()
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    report = preview(tmp_path)
    assert report["decision"] == "reuse"
    references = report["evidence"]
    assert {item["kind"] for item in references} >= {"execution-manifest", "current-attempt", "success-receipt", "historical-output", "output-file"}
    assert {item["path"] for item in references if item["kind"] == "historical-output"} == set(computation["internal_outputs"])
    after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_outputless_targets_are_never_made_reusable_by_receipts(tmp_path):
    planned = plan(load("examples.internal_graph:always"), {"source": "reads.txt"}, project=tmp_path)
    complete_plan(planned)
    report = preview_plan(planned, statuses={})["computations"][0]
    assert report["decision"] == "execute"
    assert report["targets"][0]["reason"]["code"] == "outputless-always-run"


def test_new_current_attempt_is_not_certified_by_a_late_historical_receipt(tmp_path):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    tracking = read_tracking(tmp_path)
    tracking["associations"][association_key(identity, "e")] = job_association(identity, "e", "replacement", "999")
    write_tracking(tmp_path, tracking)
    write_runtime_record(current_attempt_path(tmp_path, identity, "e"), current_attempt(identity, "e", "replacement"))
    old_receipt = receipt_path(tmp_path, identity, "e", "fixture-success")
    # Republish the old receipt after the replacement is selected.
    write_runtime_record(old_receipt, json.loads(old_receipt.read_text()))
    report = preview(tmp_path)
    assert decisions(report) == {"a": "reuse", "b": "reuse", "c": "reuse", "d": "reuse", "e": "execute"}


def test_main_only_change_preserves_reuse_but_upstream_identity_change_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "no-scheduler"))
    from dataclasses import replace
    definition = load("examples.connections:main")
    planned = plan(definition, project=tmp_path)
    complete_plan(planned)
    main_changed = plan(replace(definition, version="main-only-revision"), project=tmp_path)
    observed = preview_plan(main_changed, statuses={})
    assert observed["outcome"] == "ready", observed
    assert len(observed["computations"]) == 4
    assert all(c["decision"] == "reuse" for c in observed["computations"])
    upstream_changed = plan(load("examples.connections:revised"), project=tmp_path)
    independent = upstream_changed["main"]["occurrences"]["independent"]["identity"]
    observed = preview_plan(upstream_changed, statuses={})
    assert observed["outcome"] == "ready", observed
    assert len(observed["computations"]) == 4
    for computation in observed["computations"]:
        assert computation["decision"] == ("reuse" if computation["identity"] == independent else "execute")


def test_evaluation_demo_runs_every_claimed_case_through_the_product_command(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.runtime_evaluation", "--project", str(tmp_path / "demo")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [(case["case"], case["exit"], case["execute"]) for case in json.loads(result.stdout)["cases"]] == [
        ("completed", 0, []), ("left-branch-stale", 0, ["a", "b", "e"]),
        ("intermediates-removed", 0, []),
        ("missing-receipt-after-cleanup", 0, ["a", "b", "c", "d", "e"]),
        ("partial-retry", 0, ["e"]), ("missing-external-input", 1, []),
    ]
