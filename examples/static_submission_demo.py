"""Run native gwflow commands, real gwf/Bash, and a portable Slurm substitute."""
import argparse
import json
from pathlib import Path
import tempfile

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import read_tracking


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new demo directory; defaults to a unique temporary directory")
    args = parser.parse_args(argv)
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-static-demo-"))
    if args.project:
        root.mkdir(parents=True)
    cases = []
    for case in ("success", "late-failure"):
        project = root / case
        project.mkdir()
        (project / "reads.txt").write_text("portable host payload\n")
        scheduler = PortableSlurm(root / f"{case}-scheduler")
        definition = "examples.static_submission:" + ("main" if case == "success" else "failure")
        submitted = scheduler.command("run", definition, "--project", str(project))
        if submitted.returncode != 0:
            raise RuntimeError(submitted.stdout + submitted.stderr)
        report = json.loads(submitted.stdout)
        associations = read_tracking(project)["associations"].values()
        names = {item["job_id"]: item["target"] for item in associations}
        jobs = scheduler.jobs()
        if len(jobs) != 5 or any(job["state"] != "submitted" for job in jobs.values()):
            raise RuntimeError("command must return after all five jobs are submitted, before fixture execution")
        dependencies = {names[job_id]: sorted(names[parent] for parent in job["dependencies"]) for job_id, job in jobs.items()}
        if dependencies["copy"] != ["early", "late"]:
            raise RuntimeError("consumer lost the independent-terminal barrier")
        scheduler.advance()
        jobs = scheduler.jobs()
        states = {names[job_id]: job["state"] for job_id, job in jobs.items()}
        consumer = next(Path(job["outputs"][0]) for job_id, job in jobs.items() if names[job_id] == "copy")
        reused_ids = None
        if case == "success":
            if any(state != "completed" for state in states.values()) or consumer.read_text() != "portable host payload\n":
                raise RuntimeError("real host graph did not complete")
            reused = scheduler.command("run", definition, "--project", str(project))
            reused_ids = json.loads(reused.stdout)["accepted_job_ids"]
            if reused.returncode or reused_ids:
                raise RuntimeError("completed graph was not reused")
        elif states["early"] != "completed" or states["late"] != "failed" or states["copy"] != "submitted" or consumer.exists():
            raise RuntimeError("late producer failure did not block the consumer")
        cases.append({"case": case, "project": str(project), "accepted_job_ids": report["accepted_job_ids"],
                      "dependencies": dependencies, "states_after_fixture_execution": states,
                      "repeat_accepted_job_ids": reused_ids})
    print(json.dumps({"project": str(root), "real_slurm_jobs_submitted": 0, "cases": cases}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
