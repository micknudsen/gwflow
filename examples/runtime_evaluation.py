"""Portable evaluation fixtures; these records do not claim real job execution."""
import argparse
import json
import os
from pathlib import Path
from shlex import quote
import sys
import tempfile
from examples.portable_slurm import PortableSlurm

from gwflow import MainPipeline, Subpipeline, Target, execution_manifest, plan
from gwflow.runtime_records import (
    current_attempt, current_attempt_path, receipt_path, success_receipt,
    write_execution_manifest, write_runtime_record,
    job_association, job_tracking, write_tracking,
)


def build(ctx):
    a, b, c, d, e = [ctx.path(name) for name in ("a", "b", "c", "d", "final")]
    def copy(name, source, output):
        return Target(name, f"cp {quote(source)} {quote(output)}", (source,), (output,))
    return [copy("a", ctx.inputs["source"], a), copy("b", a, b),
            copy("c", ctx.inputs["other"], c), copy("d", c, d),
            Target("e", f"cat {quote(b)} {quote(d)} > {quote(e)}", (b, d), (e,))]


main = MainPipeline("examples.evaluation", "1", Subpipeline(
    "examples.evaluation", "1", {"source": "file", "other": "file"}, {"final": "final"}, build,
))


def stamp(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture payload\n")
    os.utime(path, ns=(value, value))


def prepare_fixture(project):
    """Seed a successful fork/join for controlled read-only evaluation demos."""
    project = Path(project)
    stamp(project / "reads.txt", 10)
    stamp(project / "other.txt", 150)
    planned = plan(main, {"source": "reads.txt", "other": "other.txt"}, project=project)
    computation = planned["computations"][0]
    identity = computation["identity"]
    write_tracking(project, job_tracking([
        job_association(identity, target["name"], "fixture-success", str(index + 100))
        for index, target in enumerate(computation["targets"])
    ]))
    write_execution_manifest(project, execution_manifest(planned, identity))
    for target in computation["targets"]:
        stamp_value = {"a": 20, "b": 30, "c": 200, "d": 210, "e": 220}[target["name"]]
        outputs = []
        for path in target["outputs"]:
            stamp(path, stamp_value)
            outputs.append({"path": path, "mtime_ns": stamp_value})
        write_runtime_record(current_attempt_path(project, identity, target["name"]),
                             current_attempt(identity, target["name"], "fixture-success"))
        write_runtime_record(receipt_path(project, identity, target["name"], "fixture-success"),
                             success_receipt(identity, target["name"], "fixture-success", outputs))
    return planned


def demo(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new directory; defaults to a unique temporary directory")
    args = parser.parse_args(argv)
    project = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-evaluation-demo-"))
    if args.project:
        project.mkdir(parents=True)
    planned = prepare_fixture(project)
    scheduler = PortableSlurm(project / "fixture-scheduler")
    computation = planned["computations"][0]
    cases = []

    def observe(name, expected_execute=(), expected_exit=0):
        result = scheduler.command(
            "run", "examples.runtime_evaluation:main",
            "--project", str(project), "--dry-run", "--bindings",
            json.dumps({"source": "reads.txt", "other": "other.txt"}),
        )
        report = json.loads(result.stdout)
        targets = report["computations"][0]["targets"] if report["computations"] else []
        executed = sorted(target["name"] for target in targets if target["decision"] == "execute")
        if result.returncode != expected_exit or executed != sorted(expected_execute):
            raise RuntimeError(f"{name}: unexpected preview: {result.stdout} {result.stderr}")
        cases.append({"case": name, "exit": result.returncode, "execute": executed, "diagnostic": result.stderr.strip()})

    observe("completed")
    stamp(project / "reads.txt", 25)
    observe("left-branch-stale", ("a", "b", "e"))
    stamp(project / "reads.txt", 10)
    for path in computation["internal_outputs"]:
        Path(path).unlink()
    observe("intermediates-removed")
    receipt_path(project, computation["identity"], "e", "fixture-success").unlink()
    observe("missing-receipt-after-cleanup", ("a", "b", "c", "d", "e"))
    prepare_fixture(project)
    receipt_path(project, computation["identity"], "e", "fixture-success").unlink()
    observe("partial-retry", ("e",))
    (project / "reads.txt").unlink()
    observe("missing-external-input", expected_exit=1)
    print(json.dumps({"project": str(project), "fixture_only": True, "cases": cases}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(demo())
