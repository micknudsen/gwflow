"""Seed declaration fixtures and exercise the maintained preview command.

No payload or scheduler is executed. Schema round-trips outside the authority
directory are fixtures, not evidence of successful execution.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from gwflow import execution_manifest, load, plan
from gwflow.runtime_records import (
    attempt_diagnostic, current_attempt, job_association, read_execution_manifest,
    read_runtime_record, submission_intent, success_receipt,
    write_execution_manifest, write_runtime_record,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new directory; defaults to a unique temporary directory")
    args = parser.parse_args(argv)
    if args.project is None:
        root = Path(tempfile.mkdtemp(prefix="gwflow-record-demo-"))
    else:
        root = args.project.absolute()
        root.mkdir(parents=True)  # Never overwrite an existing project.
    outcomes = []

    def prepare(name, definition):
        project = root / name
        project.mkdir()
        (project / "reads.txt").write_text("demo input\n")
        (project / "other.txt").write_text("another input\n")
        planned = plan(load(definition), {"source": "reads.txt"}, project=project)
        computation = planned["computations"][0]
        record = execution_manifest(planned, computation["identity"])
        write_execution_manifest(project, record)
        assert read_execution_manifest(project, computation["identity"]) == record
        return project, computation

    def preview(label, project, definition, expected, source="reads.txt", resources=None):
        command = [sys.executable, "-m", "gwflow", "run", definition, "--dry-run",
                   "--project", str(project), "--bindings", json.dumps({"source": source})]
        if resources:
            command.extend(["--resources", json.dumps(resources)])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        outcomes.append({"case": label, "exit": result.returncode, "expected": expected,
                         "diagnostic": result.stderr.strip()})
        if result.returncode != expected:
            raise RuntimeError(f"{label}: expected {expected}, got {result.returncode}: {result.stdout} {result.stderr}")

    project, computation = prepare("literal", "examples.runtime_records:main")
    preview("unchanged", project, "examples.runtime_records:main", 0)
    preview("command-whitespace", project, "examples.runtime_records:changed", 2)
    preview("target-rename", project, "examples.runtime_records:renamed", 2)
    preview("resources-and-provenance", project, "examples.runtime_records:operational", 0)
    preview("different-binding", project, "examples.runtime_records:changed", 0, "other.txt")
    project, _ = prepare("typed", "examples.runtime_records:boolean_parameter")
    preview("boolean-to-integer-parameter", project, "examples.runtime_records:integer_parameter", 2)

    # Round-trip every non-manifest schema without putting fabricated evidence
    # at the authority paths used by preview or submission.
    identity = computation["identity"]
    target = computation["targets"][0]
    records = [
        current_attempt(identity, target["name"], "fixture-attempt"),
        success_receipt(identity, target["name"], "fixture-attempt", [{"path": target["outputs"][0], "mtime_ns": 7}]),
        job_association(identity, target["name"], "fixture-attempt", "12345"),
        attempt_diagnostic(identity, target["name"], "fixture-attempt", str(root / "stdout"), str(root / "stderr")),
        submission_intent("fixture-submission", [{"identity": identity, "target": target["name"], "attempt": "fixture-attempt", "ownership": "fixture-owner"}]),
    ]
    for record in records:
        path = root / "schema-roundtrips" / (record["kind"] + ".json")
        write_runtime_record(path, record)
        assert read_runtime_record(path) == record
    print(json.dumps({"project": str(root), "cases": outcomes,
                      "schema_roundtrips": [record["kind"] for record in records]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
