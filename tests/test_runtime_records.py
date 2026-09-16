from copy import deepcopy
import json

import pytest

from gwflow import PlanError, execution_manifest, load, plan, validate_execution_manifest, validate_runtime_record
from gwflow.runtime_records import attempt_diagnostic, current_attempt, job_association, submission_intent, success_receipt
from gwflow.runtime_records import computational_declaration, read_execution_manifest, require_consistent_definition, write_execution_manifest
from test_planner import runtime_cli


def computation(tmp_path):
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    return result, result["computations"][0]


def test_runtime_declaration_round_trip_and_atomic_location(tmp_path):
    result, current = computation(tmp_path)
    record = execution_manifest(result, current["identity"])
    assert validate_execution_manifest(json.loads(json.dumps(record))) is None
    location = write_execution_manifest(tmp_path, record)
    assert location == tmp_path / ".gwflow" / "runtime" / "v1" / "computations" / current["identity"][:2] / current["identity"] / "manifest.json"
    assert read_execution_manifest(tmp_path, current["identity"]) == record


def test_literal_commands_and_target_names_are_immutable(tmp_path):
    result, current = computation(tmp_path)
    saved = execution_manifest(result, current["identity"])
    changed = deepcopy(current)
    changed["targets"][0]["command"] += " "
    with pytest.raises(PlanError, match="publish a new subpipeline version"):
        require_consistent_definition(saved, changed)
    changed = deepcopy(current)
    changed["targets"][0]["name"] = "renamed"
    with pytest.raises(PlanError, match="publish a new subpipeline version"):
        require_consistent_definition(saved, changed)


def test_representation_order_and_resources_do_not_change_declaration(tmp_path):
    _, current = computation(tmp_path)
    changed = deepcopy(current)
    changed["targets"][0]["resources"] = {"memory_mb": 4096}
    changed["computational_edges"] = list(reversed(changed["computational_edges"]))
    assert computational_declaration(changed) == computational_declaration(current)


def test_invalid_or_different_binding_records_are_not_compared_as_a_registry(tmp_path):
    result, current = computation(tmp_path)
    saved = execution_manifest(result, current["identity"])
    saved["extra"] = "no"
    with pytest.raises(PlanError, match="unexpected fields"):
        validate_execution_manifest(saved)
    saved = execution_manifest(result, current["identity"])
    del saved["computational_declaration"]["targets"][0]["command"]
    with pytest.raises(PlanError, match="invalid target declaration"):
        validate_execution_manifest(saved)
    other = plan(load("examples.one_file:main"), {"source": "other.txt"}, project=tmp_path)["computations"][0]
    assert other["identity"] != current["identity"]


def test_runtime_command_enforces_saved_visible_declaration(tmp_path):
    result = plan(load("examples.runtime_records:main"), {"source": "reads.txt"}, project=tmp_path)
    current = result["computations"][0]
    write_execution_manifest(tmp_path, execution_manifest(result, current["identity"]))
    reusable = runtime_cli(tmp_path, "--dry-run", "examples.runtime_records:main", "--bindings", '{"source":"reads.txt"}')
    assert reusable.returncode == 0, reusable.stderr
    changed = runtime_cli(tmp_path, "--dry-run", "examples.runtime_records:changed", "--bindings", '{"source":"reads.txt"}')
    assert changed.returncode == 2
    assert "publish a new subpipeline version" in changed.stderr


def test_required_attempt_tracking_records_have_independent_roles(tmp_path):
    _, current = computation(tmp_path)
    identity = current["identity"]
    attempt = "attempt-1"
    records = [
        current_attempt(identity, "copy", attempt),
        success_receipt(identity, "copy", attempt, [{"path": "results/copy.txt", "mtime_ns": 7}]),
        job_association(identity, "copy", attempt, "12345"),
        attempt_diagnostic(identity, "copy", attempt, "logs/stdout", "logs/stderr"),
        submission_intent("submission-1", [{"identity": identity, "target": "copy", "attempt": attempt, "ownership": "gwflow:submission-1"}]),
    ]
    assert all(validate_runtime_record(record) is None for record in records)
    corrupt = deepcopy(records[1])
    corrupt["attempt"] = "newer-attempt"
    assert corrupt["attempt"] != records[0]["attempt"]
    assert validate_runtime_record(corrupt) is None
