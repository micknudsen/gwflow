"""Execute, remove fixture intermediates, reuse, and recover through native commands."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import current_attempt_path, read_tracking, receipt_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new disposable demo root")
    args = parser.parse_args(argv)
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-recovery-demo-"))
    if args.project:
        root.mkdir(parents=True)
    project = root / "project"
    project.mkdir()
    (project / "reads.txt").write_text("left payload\n")
    (project / "other.txt").write_text("right payload\n")
    scheduler = PortableSlurm(root / "scheduler")
    cases = []

    def command(*flags):
        result = scheduler.command("run", "examples.runtime_evaluation:main", "--project", str(project),
                                   "--bindings", '{"source":"reads.txt","other":"other.txt"}', *flags)
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout)

    def execute_case(name, expected):
        preview = command("--dry-run")
        assert sorted(target["name"] for target in preview["computations"][0]["targets"] if target["decision"] == "execute") == expected
        result = command()
        associations = {item["target"]: item for item in read_tracking(project)["associations"].values()}
        accepted = sorted(name for name, item in associations.items() if item["job_id"] in result["accepted_job_ids"])
        assert accepted == expected
        scheduler.advance()
        assert all(scheduler.jobs()[job]["state"] == "completed" for job in result["accepted_job_ids"])
        assert command("--dry-run")["computations"][0]["decision"] == "reuse"
        cases.append({"case": name, "accepted_targets": accepted, "accepted_job_ids": result["accepted_job_ids"]})
        return associations

    associations = execute_case("initial-execution", ["a", "b", "c", "d", "e"])
    for name in ("a", "b", "c", "d"):
        for output in scheduler.jobs()[associations[name]["job_id"]]["outputs"]:
            Path(output).unlink()  # Only exact disposable files created by this demo.
    execute_case("cleanup-reuse", [])
    target = associations["b"]
    receipt_path(project, target["identity"], "b", target["attempt"]).unlink()
    associations = execute_case("evidence-loss-after-cleanup", ["a", "b", "c", "d", "e"])
    current_attempt_path(project, associations["b"]["identity"], "b").unlink()
    associations = execute_case("partial-evidence-retry", ["b", "e"])
    output = Path(scheduler.jobs()[associations["a"]["job_id"]]["outputs"][0])
    source = project / "reads.txt"
    source.write_text("updated left payload\n")
    newer = output.stat().st_mtime_ns + 1
    os.utime(source, ns=(newer, newer))
    associations = execute_case("stale-left-branch", ["a", "b", "e"])
    final = Path(scheduler.jobs()[associations["e"]["job_id"]]["outputs"][0])
    assert final.read_text() == "updated left payload\nright payload\n"
    print(json.dumps({"project": str(project), "real_slurm_jobs_submitted": 0,
                      "fixture_intermediate_removal_only": True, "cases": cases, "retained_result": str(final)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
