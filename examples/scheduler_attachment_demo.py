"""Sequential native submissions with real host payloads and private Slurm fixtures."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import read_tracking


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new demo directory")
    args = parser.parse_args(argv)
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-attachment-demo-"))
    if args.project:
        root.mkdir(parents=True)
    project = root / "project"
    project.mkdir()
    (project / "reads.txt").write_text("actual host payload\n")
    scheduler = PortableSlurm(root / "scheduler")

    def run(selector="main", *flags, expected=0):
        result = scheduler.command("run", f"examples.static_submission:{selector}", "--project", str(project), *flags)
        if result.returncode != expected:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout)

    first = run("producer_only")
    second = run()
    assert len(first["accepted_job_ids"]) == 4 and len(second["accepted_job_ids"]) == 1
    consumer = scheduler.jobs()[second["accepted_job_ids"][0]]
    associations = read_tracking(project)
    terminal_ids = {item["job_id"] for item in associations["associations"].values() if item["target"] in {"early", "late"}}
    assert set(consumer["dependencies"]) == terminal_ids
    active = run("main", "--dry-run")
    decisions = sorted({target["decision"] for comp in active["computations"] for target in comp["targets"]})
    assert decisions == ["attach"]
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())
    history = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
               for path in (project / ".gwflow").rglob("*") if path.is_file() and "attempts" in path.parts}
    completed = run()
    jobs = scheduler.jobs()
    for job in jobs.values():
        job["state"] = "expired"  # Controlled successful empty accounting, not a time delay.
    scheduler.configure(jobs=jobs)
    expired = run("producer_only")
    assert completed["accepted_job_ids"] == expired["accepted_job_ids"] == []
    assert read_tracking(project) == associations
    unchanged = history == {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                            for path in (project / ".gwflow").rglob("*") if path.is_file() and "attempts" in path.parts}
    assert unchanged
    scheduler.configure(query_failure="sacct")
    failed = run("main", "--dry-run", expected=1)
    assert failed["reason"]["code"] == "scheduler-query-failed" and not failed["computations"]
    scheduler.configure(query_failure=None)
    print(json.dumps({"project": str(project), "real_slurm_jobs_submitted": 0,
        "producer_job_ids": first["accepted_job_ids"], "new_consumer_job_ids": second["accepted_job_ids"],
        "consumer_dependencies": consumer["dependencies"], "active_preview_decisions": decisions,
        "completed_accepted_job_ids": completed["accepted_job_ids"], "expired_accepted_job_ids": expired["accepted_job_ids"],
        "retained_associations": len(associations["associations"]), "attempt_history_unchanged": unchanged,
        "query_failure": {"exit": 1, "code": failed["reason"]["code"], "diagnostic": failed["diagnostic"]}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
