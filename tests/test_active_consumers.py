"""Replacement protection through native commands and retained scheduler state."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import execution_manifest_path, read_tracking, receipt_path


PRODUCER = "examples.static_submission:producer_only"
MAIN = "examples.static_submission:main"
UNRELATED = ("examples.one_file:main", "--bindings", '{"source":"other.txt"}')


def run(project, scheduler, *arguments, expected=0):
    result = scheduler.command("run", *arguments, "--project", str(project))
    assert result.returncode == expected, result.stdout + result.stderr
    report = json.loads(result.stdout)
    if expected:
        assert report["diagnostic"] in result.stderr
    return report


def snapshot(project):
    return {str(path.relative_to(project)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in project.rglob("*") if path.is_file()}


def active_consumer(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("producer payload\n")
    (project / "other.txt").write_text("unrelated payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    first = run(project, scheduler, PRODUCER)
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())
    consumer = run(project, scheduler, MAIN)["accepted_job_ids"]
    assert len(consumer) == 1
    associations = {item["target"]: item for item in read_tracking(project)["associations"].values()}
    # Even recovery of the unconsumed terminal must honor the whole producer.
    late = associations["late"]
    receipt_path(project, late["identity"], "late", late["attempt"]).unlink()
    return project, scheduler, first, consumer[0], associations


@pytest.mark.parametrize("state", ["submitted", "running"])
@pytest.mark.parametrize("selector", [PRODUCER, MAIN])
def test_active_consumer_blocks_replacement_inside_or_outside_composition(tmp_path, state, selector):
    project, scheduler, _, consumer, associations = active_consumer(tmp_path)
    jobs = scheduler.jobs()
    jobs[consumer]["state"] = state
    scheduler.configure(jobs=jobs)
    before = snapshot(project)
    for flags in [("--dry-run",), ()]:
        report = run(project, scheduler, selector, *flags, expected=1)
        assert report["outcome"] == "blocked"
        assert report["reason"]["code"] == "active-consumer-conflict"
        assert report["computations"] == []
        assert report.get("accepted_job_ids", []) == []
        assert f"job {consumer}, {state}" in report["diagnostic"]
        assert associations["late"]["identity"] in report["diagnostic"]
        assert snapshot(project) == before
        assert scheduler.jobs() == jobs
        assert not (project / ".gwflow" / "command-guard").exists()
        assert not (project / ".gwflow" / "submission.json").exists()
    pure = scheduler.command("plan", selector, "--project", str(project))
    assert pure.returncode == 0, pure.stderr
    assert snapshot(project) == before


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled", "expired"])
def test_terminal_or_successfully_expired_consumer_permits_replacement(tmp_path, state):
    project, scheduler, _, consumer, _ = active_consumer(tmp_path)
    scheduler.advance()
    jobs = scheduler.jobs()
    jobs[consumer]["state"] = state
    scheduler.configure(jobs=jobs)
    assert run(project, scheduler, PRODUCER, "--dry-run")["outcome"] == "ready"
    retried = run(project, scheduler, PRODUCER)
    assert len(retried["accepted_job_ids"]) == 1
    scheduler.advance()
    assert scheduler.jobs()[retried["accepted_job_ids"][0]]["state"] == "completed"


def test_unrelated_existing_work_recovers_while_conflicting_request_is_blocked(tmp_path):
    project, scheduler, _, consumer, _ = active_consumer(tmp_path)
    first = run(project, scheduler, *UNRELATED)
    assert scheduler.execute(first["accepted_job_ids"][0])
    output = scheduler.jobs()[first["accepted_job_ids"][0]]["outputs"][0]
    Path(output).unlink()
    report = run(project, scheduler, *UNRELATED)
    assert len(report["accepted_job_ids"]) == 1
    assert scheduler.jobs()[consumer]["state"] == "submitted"
    assert run(project, scheduler, PRODUCER, expected=1)["reason"]["code"] == "active-consumer-conflict"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "unsupported"])
def test_unknown_external_active_graph_blocks_existing_replacement_but_not_new_work(tmp_path, damage):
    project, scheduler, _, consumer, associations = active_consumer(tmp_path)
    active = next(item for item in associations.values() if item["job_id"] == consumer)
    manifest = execution_manifest_path(project, active["identity"])
    if damage == "missing":
        manifest.unlink()
    elif damage == "corrupt":
        manifest.write_text("invalid JSON")
    else:
        record = json.loads(manifest.read_text())
        record["record_revision"] = 999
        manifest.write_text(json.dumps(record))
    before = snapshot(project)
    for flags in [("--dry-run",), ()]:
        report = run(project, scheduler, PRODUCER, *flags, expected=1)
        assert report["reason"]["code"] == "active-consumer-state-unknown"
        assert consumer in report["diagnostic"]
        assert snapshot(project) == before
    assert len(run(project, scheduler, *UNRELATED)["accepted_job_ids"]) == 1


def test_submission_rechecks_after_a_ready_preview(tmp_path):
    project, scheduler, _, consumer, _ = active_consumer(tmp_path)
    # The preview sees quiescence; submission observes a currently running job.
    jobs = scheduler.jobs()
    jobs[consumer]["state"] = "completed"
    scheduler.configure(jobs=jobs)
    assert run(project, scheduler, PRODUCER, "--dry-run")["outcome"] == "ready"
    jobs[consumer]["state"] = "running"
    scheduler.configure(jobs=jobs)
    before = snapshot(project)
    assert run(project, scheduler, PRODUCER, expected=1)["reason"]["code"] == "active-consumer-conflict"
    assert snapshot(project) == before


def test_new_producer_version_uses_distinct_slots_while_old_consumer_is_active(tmp_path):
    project, scheduler, _, consumer, _ = active_consumer(tmp_path)
    report = run(project, scheduler, "examples.static_submission:failure")
    assert len(report["accepted_job_ids"]) == 5
    assert scheduler.jobs()[consumer]["state"] == "submitted"


def test_failed_producer_cannot_retry_while_consumer_waits_on_old_job_id(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    selector = "examples.static_submission:failure"
    run(project, scheduler, selector)
    scheduler.advance()
    jobs = scheduler.jobs()
    assert {job["state"] for job in jobs.values()} == {"completed", "failed", "submitted"}
    before = snapshot(project)
    for flags in [("--dry-run",), ()]:
        report = run(project, scheduler, selector, *flags, expected=1)
        assert report["reason"]["code"] == "active-consumer-conflict"
        assert snapshot(project) == before and scheduler.jobs() == jobs


@pytest.mark.parametrize("active_name", ["early", "late"])
def test_internal_active_descendant_blocks_ancestor_retry_but_not_independent_branch(tmp_path, active_name):
    project, scheduler, _, consumer, associations = active_consumer(tmp_path)
    jobs = scheduler.jobs()
    jobs[consumer]["state"] = "cancelled"
    jobs[associations[active_name]["job_id"]]["state"] = "running"
    scheduler.configure(jobs=jobs)
    if active_name == "late":
        early = associations["early"]
        receipt_path(project, early["identity"], "early", early["attempt"]).unlink()
    # An independent branch can recover alongside either active terminal.
    retried = run(project, scheduler, PRODUCER)
    assert len(retried["accepted_job_ids"]) == 1
    assert scheduler.execute(retried["accepted_job_ids"][0])
    seed = associations["seed"]
    receipt_path(project, seed["identity"], "seed", seed["attempt"]).unlink()
    before = snapshot(project)
    for flags in [("--dry-run",), ()]:
        report = run(project, scheduler, PRODUCER, *flags, expected=1)
        assert report["reason"]["code"] == "active-consumer-conflict"
        assert f"{seed['identity']}/seed" in report["diagnostic"]
        assert snapshot(project) == before


def test_active_consumer_demo(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.active_consumer_demo", "--project", str(tmp_path / "demo")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["real_slurm_jobs_submitted"] == 0
    assert report["blocked_reason"] == "active-consumer-conflict"
    assert report["blocked_state_unchanged"] is True
    assert len(report["unrelated_job_ids"]) == len(report["replacement_job_ids"]) == 1
