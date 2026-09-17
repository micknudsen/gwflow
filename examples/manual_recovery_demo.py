"""Recover a partial acceptance through native commands and private Slurm fixtures."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from examples.portable_slurm import PortableSlurm


SINCE = "2000-01-01T00:00:00"
DEFINITION = "examples.static_submission:main"


def interrupted(root):
    project = root / "project"
    project.mkdir()
    (project / "reads.txt").write_text("recovered payload\n")
    scheduler = PortableSlurm(root / "scheduler")
    scheduler.configure(lose_reply_at=2)
    failed = scheduler.command("run", DEFINITION, "--project", str(project))
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert len(scheduler.jobs()) == 2
    return project, scheduler


def inspect(project, scheduler):
    result = scheduler.command("recover", "--project", str(project), "--since", SINCE)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def certify(report, scheduler):
    """Fixture-only exhaustive ledger proof; operators use actual audit evidence."""
    document = report["resolution"]
    document.update(command_stopped=True, ownership_complete=True,
                    evidence="Portable fixture: submit command exited; full scheduler acceptance ledger inspected")
    jobs = {job["name"]: job_id for job_id, job in scheduler.jobs().items()}
    document["targets"] = [
        {"ownership": item["ownership"], "job_id": jobs[item["ownership"]]}
        if item["ownership"] in jobs else
        {"ownership": item["ownership"], "not_accepted": {
            "source": "scheduler-admin-audit", "reference": str(scheduler.state_path) + ": exhaustive fixture acceptance ledger"}}
        for item in report["intent"]["targets"]]
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new demo root")
    args = parser.parse_args(argv)
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-manual-recovery-"))
    if args.project:
        root.mkdir(parents=True)
    project, scheduler = interrupted(root)
    report = inspect(project, scheduler)
    resolution = root / "resolution.json"
    resolution.write_text(json.dumps(certify(report, scheduler)))
    command = ("recover", "--project", str(project), "--since", SINCE, "--apply", str(resolution))
    active = scheduler.command(*command)
    assert active.returncode == 1
    assert json.loads(active.stdout)["reason"]["code"] == "recovery-not-quiescent"
    scheduler.advance()
    recovered = scheduler.command(*command)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    report = json.loads(recovered.stdout)
    resumed = scheduler.command("run", DEFINITION, "--project", str(project))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert len(json.loads(resumed.stdout)["accepted_job_ids"]) == 3
    scheduler.advance()
    reuse = scheduler.command("run", DEFINITION, "--project", str(project))
    assert reuse.returncode == 0 and json.loads(reuse.stdout)["accepted_job_ids"] == []
    print(json.dumps({"project": str(project), "real_slurm_jobs_submitted": 0,
                      "active_recovery_exit": active.returncode, "recovered_job_ids": report["restored_job_ids"],
                      "invalidated_targets": report["invalidated_targets"], "audit": report["audit"],
                      "resumed_jobs": 3, "reused": True}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
