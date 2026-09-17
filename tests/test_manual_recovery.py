"""P2-18 through native commands, real gwf jobs, and portable Slurm inspection."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.manual_recovery_demo import certify, inspect, interrupted, SINCE, DEFINITION
from gwflow.runtime_records import current_attempt_path, read_tracking, tracking_path


def fixture(tmp_path):
    project, scheduler = interrupted(tmp_path)
    report = inspect(project, scheduler)
    document = certify(report, scheduler)
    resolution = tmp_path / "resolution.json"
    resolution.write_text(json.dumps(document))
    return project, scheduler, report, document, resolution


def apply(project, scheduler, resolution):
    return scheduler.command("recover", "--project", str(project), "--since", SINCE,
                             "--apply", str(resolution))


def snapshot(project):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in project.rglob("*") if path.is_file()}


def test_inspection_is_read_only_and_reports_full_attempt_ownership(tmp_path):
    project, scheduler = interrupted(tmp_path)
    before = snapshot(project)
    report = inspect(project, scheduler)
    assert snapshot(project) == before
    assert len(report["intent"]["targets"]) == 5
    assert {item["job_id"] for item in report["observations"]} == {"1001", "1002"}
    assert report["resolution"]["command_stopped"] is False
    assert (project / ".gwflow/submission.json").exists()


@pytest.mark.parametrize("state", ["submitted", "running", "SUSPENDED", "COMPLETING", "MYSTERY"])
def test_remaining_or_unknown_activity_blocks_without_mutation(tmp_path, state):
    project, scheduler, report, document, resolution = fixture(tmp_path)
    jobs = scheduler.jobs()
    for job in jobs.values():
        job["state"] = state
    scheduler.configure(jobs=jobs)
    before = snapshot(project)
    result = apply(project, scheduler, resolution)
    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"]["code"] == "recovery-not-quiescent"
    assert snapshot(project) == before
    assert not (project / ".gwflow/recovery-guard").exists()


@pytest.mark.parametrize("damage", ["empty-query", "missing-target", "unknown-owner", "wrong-job", "outputs-only", "live-command", "incomplete-coverage", "no-audit"])
def test_incomplete_operator_evidence_cannot_clear_uncertainty(tmp_path, damage):
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    if damage == "empty-query":
        scheduler.configure(query_output={"sacct": "", "squeue": ""})
    elif damage == "missing-target":
        document["targets"].pop()
    elif damage == "unknown-owner":
        document["targets"][0]["ownership"] = "unknown"
    elif damage == "wrong-job":
        document["targets"][0]["job_id"] = "9000"
    elif damage == "outputs-only":
        item = next(item for item in document["targets"] if "not_accepted" in item)
        item["not_accepted"] = {"source": "result-files", "reference": "all outputs exist"}
    elif damage == "live-command":
        document["command_stopped"] = False
    elif damage == "incomplete-coverage":
        document["ownership_complete"] = False
    else:
        document["evidence"] = ""
    resolution.write_text(json.dumps(document))
    before = snapshot(project)
    result = apply(project, scheduler, resolution)
    assert result.returncode == 1, result.stdout
    assert snapshot(project) == before
    blocked = scheduler.command("run", DEFINITION, "--project", str(project))
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["reason"]["code"] == "submission-uncertain"


def test_duplicate_job_ownership_and_query_failure_remain_blocked(tmp_path):
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    jobs = scheduler.jobs()
    jobs["9999"] = deepcopy(jobs["1001"])
    scheduler.configure(jobs=jobs)
    assert apply(project, scheduler, resolution).returncode == 1
    scheduler.configure(query_failure="squeue")
    result = apply(project, scheduler, resolution)
    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"]["code"] == "scheduler-query-failed"
    assert (project / ".gwflow/submission.json").exists()


def test_recovery_restores_associations_invalidates_unaccepted_attempts_and_preserves_unrelated_active_job(tmp_path):
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    jobs = scheduler.jobs()
    jobs["9999"] = {**deepcopy(jobs["1001"]), "name": "unrelated-job", "state": "running"}
    scheduler.configure(jobs=jobs)
    history = {path: data for path, data in snapshot(project).items() if path.endswith(".log")}
    result = apply(project, scheduler, resolution)
    assert result.returncode == 0, result.stdout + result.stderr
    recovered = json.loads(result.stdout)
    assert recovered["restored_job_ids"] == ["1001", "1002"]
    assert len(recovered["invalidated_targets"]) == 3
    assert Path(recovered["audit"]).exists()
    tracking = read_tracking(project)
    assert len(tracking["associations"]) == 5
    for item in tracking["associations"].values():
        if item["kind"] == "unsubmitted-attempt":
            assert not current_attempt_path(project, item["identity"], item["target"]).exists()
    assert history == {path: data for path, data in snapshot(project).items() if path.endswith(".log")}
    assert scheduler.jobs()["9999"]["state"] == "running"
    resumed = scheduler.command("run", DEFINITION, "--project", str(project))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert len(json.loads(resumed.stdout)["accepted_job_ids"]) == 3


def test_failed_jobs_cannot_reuse_old_receipts_after_accounting_expires(tmp_path):
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    jobs = scheduler.jobs()
    jobs["1001"]["state"] = "failed"
    scheduler.configure(jobs=jobs)
    assert apply(project, scheduler, resolution).returncode == 0
    for job in jobs.values():
        job["state"] = "unknown"
    scheduler.configure(jobs=jobs)
    preview = scheduler.command("run", DEFINITION, "--project", str(project), "--dry-run")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    decisions = {target["name"]: target["decision"] for comp in json.loads(preview.stdout)["computations"] for target in comp["targets"]}
    assert decisions["seed"] == "execute"


def test_durable_repair_failure_preserves_block_and_can_be_retried(tmp_path, monkeypatch, capsys):
    from gwflow.__main__ import main
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    monkeypatch.setenv("PATH", scheduler.environment["PATH"])
    monkeypatch.setenv("GWFLOW_PORTABLE_SLURM_STATE", str(scheduler.state_path))
    replace = os.replace

    def fail_tracking(source, destination):
        if Path(destination) == tracking_path(project):
            raise OSError("injected tracking commit failure")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_tracking)
    assert main(["recover", "--project", str(project), "--since", SINCE, "--apply", str(resolution)]) == 1
    assert "injected tracking commit failure" in capsys.readouterr().err
    assert (project / ".gwflow/submission.json").exists()
    assert (project / ".gwflow/command-guard").exists()
    monkeypatch.setattr(os, "replace", replace)
    assert apply(project, scheduler, resolution).returncode == 0


def test_portable_manual_recovery_demo(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.manual_recovery_demo", "--project", str(tmp_path / "demo")], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["real_slurm_jobs_submitted"] == 0
    assert report["active_recovery_exit"] == 1
    assert report["resumed_jobs"] == 3
    assert report["reused"] is True


def test_unrelated_tracked_job_remains_active_during_recovery(tmp_path):
    from examples.portable_slurm import PortableSlurm
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("affected input\n")
    (project / "other.txt").write_text("unrelated input\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    first = scheduler.command("run", "examples.one_file:main", "--project", str(project),
                              "--bindings", '{"source":"other.txt"}')
    assert first.returncode == 0, first.stdout + first.stderr
    before = read_tracking(project)["associations"]
    scheduler.configure(lose_reply_at=3)
    interrupted_run = scheduler.command("run", DEFINITION, "--project", str(project))
    assert interrupted_run.returncode == 1
    assert scheduler.execute("1002")
    assert scheduler.execute("1003")
    report = inspect(project, scheduler)
    resolution = tmp_path / "resolution.json"
    resolution.write_text(json.dumps(certify(report, scheduler)))
    recovered = apply(project, scheduler, resolution)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    after = read_tracking(project)["associations"]
    assert all(after[key] == item for key, item in before.items())
    assert scheduler.jobs()["1001"]["state"] == "submitted"


@pytest.mark.parametrize("window", ["before-acceptance", "accepted-before-id"])
def test_other_acceptance_windows_can_recover_without_fabricated_success(tmp_path, window):
    from examples.portable_slurm import PortableSlurm
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("input\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    scheduler.configure(**({"reject_before_accept_at": 1} if window == "before-acceptance" else {"lose_reply_at": 1}))
    failed = scheduler.command("run", DEFINITION, "--project", str(project))
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["accepted_job_ids"] == []
    report = inspect(project, scheduler)
    resolution = tmp_path / "resolution.json"
    resolution.write_text(json.dumps(certify(report, scheduler)))
    scheduler.advance()
    result = apply(project, scheduler, resolution)
    assert result.returncode == 0, result.stdout + result.stderr
    scheduler.configure(reject_before_accept_at=None, lose_reply_at=None)
    resumed = scheduler.command("run", DEFINITION, "--project", str(project))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert len(json.loads(resumed.stdout)["accepted_job_ids"]) == (5 if window == "before-acceptance" else 4)


@pytest.mark.parametrize("damage", ["recovery-guard", "wrong-guard-owner", "foreign-selection", "malformed-scheduler", "unrelated-history", "tracking-revision"])
def test_unknown_authority_or_concurrent_recovery_keeps_block(tmp_path, damage):
    from gwflow.runtime_records import current_attempt, write_runtime_record
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    if damage == "recovery-guard":
        (project / ".gwflow/recovery-guard").mkdir()
    elif damage == "wrong-guard-owner":
        path = project / ".gwflow/command-guard/owner.json"
        owner = json.loads(path.read_text())
        owner["owner"] = "different-command"
        path.write_text(json.dumps(owner))
    elif damage == "foreign-selection":
        item = report["intent"]["targets"][0]
        write_runtime_record(current_attempt_path(project, item["identity"], item["target"]),
                             current_attempt(item["identity"], item["target"], "untracked-newer-attempt"))
    elif damage == "malformed-scheduler":
        scheduler.configure(query_output={"sacct": "1001|truncated-name\n"})
    elif damage == "unrelated-history":
        item = report["intent"]["targets"][0]
        path = current_attempt_path(project, item["identity"], "unknown-target")
        path.parent.mkdir(parents=True)
    else:
        path = tracking_path(project)
        tracking = json.loads(path.read_text())
        tracking["tracking_revision"] = 999
        path.write_text(json.dumps(tracking))
    result = apply(project, scheduler, resolution)
    assert result.returncode == 1, result.stdout + result.stderr
    assert (project / ".gwflow/submission.json").exists()
    assert scheduler.command("run", DEFINITION, "--project", str(project)).returncode == 1


def test_marker_retirement_sync_failure_keeps_a_recovery_block(tmp_path, monkeypatch, capsys):
    from gwflow.__main__ import main
    import gwflow.manual_recovery as recovery
    project, scheduler, report, document, resolution = fixture(tmp_path)
    scheduler.advance()
    monkeypatch.setenv("PATH", scheduler.environment["PATH"])
    monkeypatch.setenv("GWFLOW_PORTABLE_SLURM_STATE", str(scheduler.state_path))
    unlink = recovery.durable_unlink

    def fail_marker_sync(path):
        if Path(path).name == "submission.json":
            Path(path).unlink()
            raise OSError("injected marker directory sync failure")
        unlink(path)

    monkeypatch.setattr(recovery, "durable_unlink", fail_marker_sync)
    assert main(["recover", "--project", str(project), "--since", SINCE, "--apply", str(resolution)]) == 1
    assert "injected marker directory sync failure" in capsys.readouterr().err
    assert (project / ".gwflow/recovery-guard").is_dir()
    blocked = scheduler.command("run", DEFINITION, "--project", str(project))
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["reason"]["code"] == "recovery-guard-held"
