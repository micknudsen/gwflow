"""Scheduler precedence at the native command boundary with real gwf jobs."""
import json
import subprocess
import sys
import pytest

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import current_attempt_path, execution_manifest_path, read_tracking


COPY = ("examples.one_file:main", "--bindings", '{"source":"reads.txt"}')


def start(tmp_path, *arguments):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("source payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    result = scheduler.command("run", *(arguments or ("examples.static_submission:main",)), "--project", str(project))
    assert result.returncode == 0, result.stdout + result.stderr
    return project, scheduler, json.loads(result.stdout)


def test_native_preview_attaches_queued_jobs_without_receipts_or_mutation(tmp_path):
    project, scheduler, submission = start(tmp_path)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in project.rglob("*") if path.is_file()}
    result = scheduler.command("run", "examples.static_submission:main", "--project", str(project), "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    targets = [target for comp in report["computations"] for target in comp["targets"]]
    assert {target["decision"] for target in targets} == {"attach"}
    assert {target["reason"]["code"] for target in targets} == {"submitted"}
    assert {job for target in targets for job in target["job_ids"]} == set(submission["accepted_job_ids"])
    assert before == {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in project.rglob("*") if path.is_file()}
    assert len(scheduler.jobs()) == 5


@pytest.mark.parametrize("query", ["sacct", "squeue"])
def test_query_failure_is_not_expired_history_for_preview_or_submission(tmp_path, query):
    project, scheduler, _ = start(tmp_path)
    scheduler.advance()
    scheduler.configure(query_failure=query)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in project.rglob("*") if path.is_file()}
    for flags in [("--dry-run",), ()]:
        result = scheduler.command("run", "examples.static_submission:main", "--project", str(project), *flags)
        assert result.returncode == 1
        report = json.loads(result.stdout)
        assert report["outcome"] == "error"
        assert report["reason"]["code"] == "scheduler-query-failed"
        assert report["computations"] == []
        assert "fixture scheduler unavailable" in report["diagnostic"]
        assert not (project / ".gwflow" / "submission.json").exists()
        assert not (project / ".gwflow" / "command-guard").exists()
    assert len(scheduler.jobs()) == 5
    assert before == {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in project.rglob("*") if path.is_file()}


def test_later_consumer_attaches_to_actual_active_producer_ids(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("source payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    first = scheduler.command("run", "examples.static_submission:producer_only", "--project", str(project))
    assert first.returncode == 0, first.stdout + first.stderr
    initial = read_tracking(project)
    producer_ids = {item["target"]: item["job_id"] for item in initial["associations"].values()}
    assert len(producer_ids) == 4
    second = scheduler.command("run", "examples.static_submission:main", "--project", str(project))
    assert second.returncode == 0, second.stdout + second.stderr
    report = json.loads(second.stdout)
    assert len(report["accepted_job_ids"]) == 1
    consumer = scheduler.jobs()[report["accepted_job_ids"][0]]
    assert set(consumer["dependencies"]) == {producer_ids["early"], producer_ids["late"]}
    assert len(scheduler.jobs()) == 5
    associations = read_tracking(project)["associations"]
    assert all(associations[key] == value for key, value in initial["associations"].items())
    repeated = scheduler.command("run", "examples.static_submission:main", "--project", str(project))
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert json.loads(repeated.stdout)["accepted_job_ids"] == []
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())


@pytest.mark.parametrize("state,decision", [("submitted", "attach"), ("running", "attach"),
    ("failed", "execute"), ("cancelled", "execute"), ("completed", "reuse"), ("expired", "reuse")])
def test_all_gwf_states_take_precedence_over_a_real_success_receipt(tmp_path, state, decision):
    project, scheduler, first = start(tmp_path, *COPY)
    scheduler.advance()
    jobs = scheduler.jobs()
    job_id = first["accepted_job_ids"][0]
    assert jobs[job_id]["state"] == "completed"
    jobs[job_id]["state"] = state  # Controlled external accounting observation after publication.
    scheduler.configure(jobs=jobs)
    result = scheduler.command("run", *COPY, "--project", str(project), "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    target = json.loads(result.stdout)["computations"][0]["targets"][0]
    assert target["decision"] == decision
    observation = next(item for item in target["evidence"] if item["kind"] == "scheduler")
    assert observation == {"kind": "scheduler", "status": "unknown" if state == "expired" else state, "job_ids": [job_id]}
    repeated = scheduler.command("run", *COPY, "--project", str(project))
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    accepted = json.loads(repeated.stdout)["accepted_job_ids"]
    assert len(accepted) == (1 if decision == "execute" else 0)
    assert len(scheduler.jobs()) == (2 if decision == "execute" else 1)


def test_expired_history_prunes_completed_graph_without_losing_tracking_or_logs(tmp_path):
    project, scheduler, _ = start(tmp_path)
    scheduler.advance()
    jobs = scheduler.jobs()
    for job in jobs.values():
        assert job["state"] == "completed"
        job["state"] = "expired"
    scheduler.configure(jobs=jobs)
    original = read_tracking(project)
    history = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
               for path in (project / ".gwflow").rglob("*") if path.is_file() and "attempts" in path.parts}
    assert history and any(path.endswith("stdout.log") for path in history)
    result = scheduler.command("run", "examples.static_submission:producer_only", "--project", str(project))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["accepted_job_ids"] == []
    assert all(comp["decision"] == "reuse" for comp in json.loads(result.stdout)["computations"])
    assert read_tracking(project) == original  # Includes the now-absent consumer.
    assert history == {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                       for path in (project / ".gwflow").rglob("*") if path.is_file() and "attempts" in path.parts}
    assert len(scheduler.jobs()) == 5


@pytest.mark.parametrize("query,output", [("sacct", "1001|UNRECOGNIZED\n"),
    ("squeue", "1001;?\n"), ("sacct", "malformed accounting row\n")])
def test_unrecognized_or_malformed_scheduler_answers_are_errors_not_expiration(tmp_path, query, output):
    project, scheduler, _ = start(tmp_path, *COPY)
    scheduler.configure(query_output={query: output})
    result = scheduler.command("run", *COPY, "--project", str(project), "--dry-run")
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["reason"]["code"] == "scheduler-query-failed"
    assert report["computations"] == []
    assert len(scheduler.jobs()) == 1


def test_scheduler_attachment_demo_runs_sequential_native_commands(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.scheduler_attachment_demo", "--project", str(tmp_path / "demo")], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["real_slurm_jobs_submitted"] == 0
    assert len(report["producer_job_ids"]) == 4
    assert len(report["new_consumer_job_ids"]) == 1
    assert report["active_preview_decisions"] == ["attach"]
    assert report["completed_accepted_job_ids"] == report["expired_accepted_job_ids"] == []
    assert report["retained_associations"] == 5
    assert report["attempt_history_unchanged"] is True
    assert report["query_failure"]["exit"] == 1
    assert report["query_failure"]["code"] == "scheduler-query-failed"


@pytest.mark.parametrize("state", ["submitted", "running"])
def test_active_jobs_survive_missing_manifest_selection_and_receipt(tmp_path, state):
    project, scheduler, first = start(tmp_path, *COPY)
    association = next(iter(read_tracking(project)["associations"].values()))
    execution_manifest_path(project, association["identity"]).unlink()
    current_attempt_path(project, association["identity"], association["target"]).unlink()
    jobs = scheduler.jobs()
    jobs[first["accepted_job_ids"][0]]["state"] = state
    scheduler.configure(jobs=jobs)
    for flags in [("--dry-run",), ()]:
        result = scheduler.command("run", *COPY, "--project", str(project), *flags)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        target = report["computations"][0]["targets"][0]
        assert target["decision"] == "attach"
        assert target["job_ids"] == first["accepted_job_ids"]
        assert report.get("accepted_job_ids", []) == []
    assert len(scheduler.jobs()) == 1


def test_current_queue_state_overrides_older_accounting_and_plan_stays_pure(tmp_path):
    project, scheduler, _ = start(tmp_path, *COPY)
    scheduler.advance()
    scheduler.configure(query_output={"sacct": "1001|COMPLETED\n", "squeue": "1001;R\n"})
    result = scheduler.command("run", *COPY, "--project", str(project), "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    target = json.loads(result.stdout)["computations"][0]["targets"][0]
    assert (target["decision"], target["reason"]["code"]) == ("attach", "running")
    scheduler.configure(query_failure="sacct")
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in project.rglob("*") if path.is_file()}
    pure = scheduler.command("plan", *COPY, "--project", str(project))
    assert pure.returncode == 0, pure.stdout + pure.stderr
    assert json.loads(pure.stdout)["runtime_evaluation"] == "not evaluated"
    assert before == {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in project.rglob("*") if path.is_file()}
