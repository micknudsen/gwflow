"""Protect an external active consumer through native commands and private Slurm fixtures."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import read_tracking, receipt_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new demo directory")
    args = parser.parse_args(argv)
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-consumer-demo-"))
    if args.project:
        root.mkdir(parents=True)
    project = root / "project"
    project.mkdir()
    (project / "reads.txt").write_text("producer payload\n")
    (project / "other.txt").write_text("unrelated payload\n")
    scheduler = PortableSlurm(root / "scheduler")

    def run(selector, *flags, expected=0):
        result = scheduler.command("run", selector, "--project", str(project), *flags)
        if result.returncode != expected:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout)

    producer = "examples.static_submission:producer_only"
    first = run(producer)
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())
    consumer = run("examples.static_submission:main")["accepted_job_ids"]
    assert len(first["accepted_job_ids"]) == 4 and len(consumer) == 1
    late = next(item for item in read_tracking(project)["associations"].values() if item["target"] == "late")
    receipt_path(project, late["identity"], "late", late["attempt"]).unlink()

    def snapshot():
        return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in project.rglob("*") if path.is_file()}

    before, jobs = snapshot(), scheduler.jobs()
    for flags in [("--dry-run",), ()]:
        blocked = run(producer, *flags, expected=1)
        assert blocked["outcome"] == "blocked"
        assert blocked["reason"]["code"] == "active-consumer-conflict"
        assert blocked["computations"] == []
        assert snapshot() == before and scheduler.jobs() == jobs
    unrelated = run("examples.one_file:main", "--bindings", '{"source":"other.txt"}')
    assert len(unrelated["accepted_job_ids"]) == 1
    assert scheduler.jobs()[consumer[0]]["state"] == "submitted"
    scheduler.advance()
    assert scheduler.jobs()[consumer[0]]["state"] == "completed"
    replacement = run(producer)
    assert len(replacement["accepted_job_ids"]) == 1
    scheduler.advance()
    assert scheduler.jobs()[replacement["accepted_job_ids"][0]]["state"] == "completed"
    print(json.dumps({"project": str(project), "real_slurm_jobs_submitted": 0,
        "consumer_job_id": consumer[0], "blocked_reason": blocked["reason"]["code"],
        "diagnostic": blocked["diagnostic"], "blocked_state_unchanged": True,
        "unrelated_job_ids": unrelated["accepted_job_ids"],
        "replacement_job_ids": replacement["accepted_job_ids"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
