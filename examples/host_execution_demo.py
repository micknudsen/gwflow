"""Exercise maintained compute-job entry points locally, without Slurm."""
import argparse
import json
from shlex import quote
import subprocess
import sys
import tempfile
from pathlib import Path

from gwflow import load, plan
from gwflow.host_execution import prepare_attempt
from gwflow.runtime_records import receipt_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path, help="new directory; defaults to a unique temporary directory")
    args = parser.parse_args(argv)
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-host-demo-"))
    if args.project:
        root.mkdir(parents=True)
    cases = []
    for name, expected in (("success", 0), ("writes-then-fails", 31), ("missing-output", 72), ("publication-failure", 73)):
        project = root / name
        project.mkdir()
        (project / "reads.txt").write_text("demo input\n")
        planned = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=project)
        computation = planned["computations"][0]
        target = dict(computation["targets"][0])
        output = quote(target["outputs"][0])
        if name == "writes-then-fails":
            target["command"] = f"printf partial > {output}; printf failure-history >&2; exit 31"
        elif name == "missing-output":
            target["command"] = "true"
        invocation = prepare_attempt(project, computation, target, "demo-attempt")
        receipt = receipt_path(project, computation["identity"], target["name"], "demo-attempt")
        if name == "publication-failure":
            receipt.mkdir()  # Fixture-only filesystem failure, not a product hook.
        result = subprocess.run([sys.executable, "-m", "gwflow.host_execution", str(invocation)], capture_output=True, text=True)
        if result.returncode != expected or receipt.is_file() != (expected == 0):
            raise RuntimeError(f"{name}: unexpected job outcome: {result.stdout} {result.stderr}")
        cases.append({"case": name, "exit": result.returncode, "receipt": receipt.is_file(),
                      "invocation": str(invocation), "stdout": str(invocation.parent / "stdout.log"),
                      "stderr": str(invocation.parent / "stderr.log")})
    print(json.dumps({"project": str(root), "scheduler_jobs_submitted": 0, "cases": cases}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
