"""Controlled evidence/association fixtures; no scheduler jobs are submitted."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from examples.portable_slurm import PortableSlurm

from examples.runtime_evaluation import prepare_fixture
from gwflow import execution_manifest, manifest
from gwflow.runtime_records import execution_manifest_path, receipt_path, tracking_path, write_execution_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new directory; defaults to a unique temporary directory")
    args = parser.parse_args(argv)
    project = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-compatibility-demo-"))
    if args.project:
        project.mkdir(parents=True)
    planned = prepare_fixture(project)
    scheduler = PortableSlurm(project / "fixture-scheduler")
    identity = planned["computations"][0]["identity"]
    installed = planned["software"]
    planned["software"] = {"gwflow": "prior-compatible-release", "gwf": "prior-compatible-release"}
    (project / "prior-plan.json").write_text(json.dumps(manifest(planned, identity)))
    write_execution_manifest(project, execution_manifest(planned, identity))
    cases = []

    def observe(name, exit_code, executed=()):
        result = scheduler.command(
            "run", "examples.runtime_evaluation:main",
            "--project", str(project), "--dry-run", "--bindings",
            '{"source":"reads.txt","other":"other.txt"}',
        )
        report = json.loads(result.stdout)
        targets = report["computations"][0]["targets"] if report["computations"] else []
        actual = sorted(target["name"] for target in targets if target["decision"] == "execute")
        if result.returncode != exit_code or actual != sorted(executed) or (exit_code == 1 and report["outcome"] != "blocked"):
            raise RuntimeError(f"{name}: unexpected preview: {result.stdout} {result.stderr}")
        cases.append({"case": name, "exit": result.returncode, "outcome": report["outcome"],
                      "execute": actual, "diagnostic": result.stderr.strip()})

    observe("compatible-provenance-reuse", 0)
    receipt = receipt_path(project, identity, "b", "fixture-success")
    record = json.loads(receipt.read_text())
    record["record_revision"] = 999
    receipt.write_text(json.dumps(record))
    observe("unsupported-receipt-recovery", 0, ("b", "e"))
    execution_manifest_path(project, identity).write_text("corrupt manifest")
    observe("corrupt-manifest-recovery", 0, ("a", "b", "c", "d", "e"))
    prepare_fixture(project)
    tracking = tracking_path(project)
    original = tracking.read_text()
    tracking.unlink()
    observe("missing-tracking-block", 1)
    tracking.write_text("corrupt tracking")
    observe("corrupt-tracking-block", 1)
    record = json.loads(original)
    record["tracking_revision"] = 999
    tracking.write_text(json.dumps(record))
    observe("unsupported-tracking-block", 1)
    print(json.dumps({"project": str(project), "fixture_only": True,
                      "scheduler_jobs_submitted": 0, "installed_software": installed,
                      "prior_software": planned["software"], "cases": cases}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
