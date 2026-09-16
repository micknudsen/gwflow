"""Real execution, cleanup-tolerant reuse, and recovery at native command seams."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import current_attempt_path, execution_manifest_path, read_runtime_record, read_tracking, receipt_path


ARGUMENTS = ("examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')


def command(project, scheduler, *flags):
    result = scheduler.command("run", *ARGUMENTS, "--project", str(project), *flags)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def completed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("left payload\n")
    (project / "other.txt").write_text("right payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    first = command(project, scheduler)
    assert len(first["accepted_job_ids"]) == 5
    scheduler.advance()
    assert {job["state"] for job in scheduler.jobs().values()} == {"completed"}
    associations = {item["target"]: item for item in read_tracking(project)["associations"].values()}
    return project, scheduler, associations


def test_real_completed_boundary_reuses_after_disposable_intermediate_removal(tmp_path):
    project, scheduler, associations = completed(tmp_path)
    for name, association in associations.items():
        receipt = read_runtime_record(receipt_path(project, association["identity"], name, association["attempt"]))
        assert receipt is not None
        if name != "e":
            for output in receipt["outputs"]:
                Path(output["path"]).unlink()  # Exact files in this disposable test project.
    retained = Path(scheduler.jobs()[associations["e"]["job_id"]]["outputs"][0])
    assert retained.read_text() == "left payload\nright payload\n"
    preview = command(project, scheduler, "--dry-run")
    assert preview["computations"][0]["decision"] == "reuse"
    repeated = command(project, scheduler)
    assert repeated["accepted_job_ids"] == []
    assert len(scheduler.jobs()) == 5
    assert {item["target"]: item for item in read_tracking(project)["associations"].values()} == associations


def recover(project, scheduler, expected):
    preview = command(project, scheduler, "--dry-run")
    assert {target["name"] for target in preview["computations"][0]["targets"] if target["decision"] == "execute"} == set(expected)
    report = command(project, scheduler)
    associations = {item["target"]: item for item in read_tracking(project)["associations"].values()}
    assert set(report["accepted_job_ids"]) == {associations[name]["job_id"] for name in expected}
    scheduler.advance()
    assert all(scheduler.jobs()[job]["state"] == "completed" for job in report["accepted_job_ids"])
    assert command(project, scheduler, "--dry-run")["computations"][0]["decision"] == "reuse"
    return associations


@pytest.mark.parametrize("kind", ["manifest", "selection", "receipt"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "unsupported"])
def test_required_evidence_loss_recovers_real_jobs_and_preserves_successful_work(tmp_path, kind, damage):
    project, scheduler, before = completed(tmp_path)
    target = before["b"]
    path = {"manifest": execution_manifest_path(project, target["identity"]),
            "selection": current_attempt_path(project, target["identity"], "b"),
            "receipt": receipt_path(project, target["identity"], "b", target["attempt"])}[kind]
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"\xff invalid JSON")
    else:
        record = json.loads(path.read_text())
        record["record_revision"] = 999
        path.write_text(json.dumps(record))
    expected = {"a", "b", "c", "d", "e"} if kind == "manifest" else {"b", "e"}
    after = recover(project, scheduler, expected)
    for name in before:
        assert (before[name] == after[name]) == (name not in expected)


def test_recovery_after_cleanup_regenerates_real_prerequisites_and_retained_output(tmp_path):
    project, scheduler, associations = completed(tmp_path)
    for association in associations.values():
        for output in scheduler.jobs()[association["job_id"]]["outputs"]:
            Path(output).unlink()  # Retained output loss must never be virtualized either.
    after = recover(project, scheduler, {"a", "b", "c", "d", "e"})
    result = Path(scheduler.jobs()[after["e"]["job_id"]]["outputs"][0])
    assert result.read_text() == "left payload\nright payload\n"
    assert all(Path(output).is_file() for association in after.values()
               for output in scheduler.jobs()[association["job_id"]]["outputs"])


def test_branch_freshness_ignores_receipt_mtime_and_timestamp_preserving_byte_changes(tmp_path):
    project, scheduler, associations = completed(tmp_path)
    source = project / "reads.txt"
    a = Path(scheduler.jobs()[associations["a"]["job_id"]]["outputs"][0])
    equal = a.stat().st_mtime_ns
    source.write_text("changed left payload\n")
    os.utime(source, ns=(equal, equal))  # Byte changes and equal mtimes do not invalidate.
    b_receipt = receipt_path(project, associations["b"]["identity"], "b", associations["b"]["attempt"])
    os.utime(b_receipt, ns=(4102444800000000000, 4102444800000000000))
    result = Path(scheduler.jobs()[associations["e"]["job_id"]]["outputs"][0])
    os.utime(result, ns=(4102444800000000000, 4102444800000000000))
    assert command(project, scheduler)["accepted_job_ids"] == []
    # One nanosecond newer than the old output, still earlier than the retry.
    os.utime(source, ns=(equal + 1, equal + 1))
    after = recover(project, scheduler, {"a", "b", "e"})
    assert after["c"] == associations["c"] and after["d"] == associations["d"]
    assert result.read_text() == "changed left payload\nright payload\n"


def test_failed_internal_retry_preserves_current_successes_and_waits_for_real_dependencies(tmp_path):
    project, scheduler, before = completed(tmp_path)
    output = Path(scheduler.jobs()[before["b"]["job_id"]]["outputs"][0])
    output.unlink()
    output.mkdir()  # Real command writes into a directory; output check must fail.
    failed = command(project, scheduler)
    assert len(failed["accepted_job_ids"]) == 2
    selected = {item["target"]: item for item in read_tracking(project)["associations"].values()}
    scheduler.advance()
    jobs = scheduler.jobs()
    assert jobs[selected["b"]["job_id"]]["state"] == "failed"
    assert jobs[selected["b"]["job_id"]]["returncode"] == 72
    assert jobs[selected["e"]["job_id"]]["state"] == "submitted"
    assert read_runtime_record(receipt_path(project, selected["b"]["identity"], "b", selected["b"]["attempt"])) is None
    output.rename(project / "failed-output-fixture")
    # Model the selected cluster's terminal invalid-dependency observation.
    # This is external test setup, not gwflow cancelling or repairing a job.
    jobs[selected["e"]["job_id"]]["state"] = "cancelled"
    scheduler.configure(jobs=jobs)
    after = recover(project, scheduler, {"b", "e"})
    for name in ("a", "c", "d"):
        assert after[name] == before[name]
    assert after["b"]["attempt"] != selected["b"]["attempt"] != before["b"]["attempt"]
    assert receipt_path(project, before["b"]["identity"], "b", before["b"]["attempt"]).is_file()


def test_missing_diagnostic_logs_and_superseded_receipts_do_not_regenerate_work(tmp_path):
    project, scheduler, old = completed(tmp_path)
    current_attempt_path(project, old["b"]["identity"], "b").unlink()
    current = recover(project, scheduler, {"b", "e"})
    for name in ("b", "e"):
        receipt_path(project, old[name]["identity"], name, old[name]["attempt"]).unlink()
    for association in current.values():
        root = receipt_path(project, association["identity"], association["target"], association["attempt"]).parent
        for name in ("stdout.log", "stderr.log", "diagnostic.json"):
            (root / name).unlink()
    repeated = command(project, scheduler)
    assert repeated["accepted_job_ids"] == []
    assert repeated["computations"][0]["decision"] == "reuse"
    assert len(scheduler.jobs()) == 7


def test_main_version_reuses_and_upstream_version_rebuilds_consumers_even_for_equal_bytes(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for name in ("reads.txt", "other.txt", "unrelated.txt"):
        (project / name).write_text("same payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")

    def run(selector, verb="run"):
        result = scheduler.command(verb, f"examples.recovery_versions:{selector}", "--project", str(project))
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    original = run("main", "plan")
    first = run("main")
    assert len(first["accepted_job_ids"]) == 7
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())
    assert run("main_changed")["accepted_job_ids"] == []
    changed = run("upstream_changed", "plan")
    before = original["main"]["occurrences"]
    after = changed["main"]["occurrences"]
    assert before["independent"]["identity"] == after["independent"]["identity"]
    assert before["producer"]["identity"] != after["producer"]["identity"]
    assert before["consumer"]["identity"] != after["consumer"]["identity"]
    rerun = run("upstream_changed")
    assert len(rerun["accepted_job_ids"]) == 6
    independent = next(comp for comp in rerun["computations"] if comp["identity"] == before["independent"]["identity"])
    assert independent["decision"] == "reuse"
    scheduler.advance()
    original_consumer = next(comp for comp in original["computations"] if comp["identity"] == before["consumer"]["identity"])
    changed_consumer = next(comp for comp in changed["computations"] if comp["identity"] == after["consumer"]["identity"])
    assert Path(original_consumer["retained_outputs"]["copy"]).read_bytes() == Path(changed_consumer["retained_outputs"]["copy"]).read_bytes()
    assert run("upstream_changed")["accepted_job_ids"] == []


def test_recovery_demo_checks_cleanup_and_selective_real_execution(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.runtime_recovery_demo", "--project", str(tmp_path / "demo")], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["real_slurm_jobs_submitted"] == 0
    assert [(case["case"], case["accepted_targets"]) for case in report["cases"]] == [
        ("initial-execution", ["a", "b", "c", "d", "e"]),
        ("cleanup-reuse", []),
        ("evidence-loss-after-cleanup", ["a", "b", "c", "d", "e"]),
        ("partial-evidence-retry", ["b", "e"]),
        ("stale-left-branch", ["a", "b", "e"]),
    ]
