from copy import deepcopy
import json
import os
import stat
import subprocess
import sys

import pytest

from gwflow import PlanError, execution_manifest, load, plan, validate_execution_manifest, validate_runtime_record
from gwflow import LocalImage, MainPipeline, Subpipeline, Target
from gwflow.runtime_records import attempt_diagnostic, current_attempt, job_association, submission_intent, success_receipt
from gwflow.runtime_records import computational_declaration, read_execution_manifest, require_consistent_definition, write_execution_manifest
from gwflow.runtime_records import current_attempt_path, execution_manifest_path, read_runtime_record, receipt_path, write_runtime_record
from gwflow.runtime_records import UnsupportedEvidence
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


def test_detached_outputless_image_declaration_remains_pure_and_valid(tmp_path):
    definition = MainPipeline("examples.outputless", "1", Subpipeline(
        "examples.outputless", "1", {}, {},
        lambda ctx: [Target("notify", "notify", image=LocalImage("images/tool.sif"))],
    ))
    planned = plan(definition, project=tmp_path)
    record = execution_manifest(planned, planned["computations"][0]["identity"])
    validate_execution_manifest(record)
    assert not list(tmp_path.iterdir())


def test_failed_file_sync_cannot_replace_a_published_declaration(tmp_path, monkeypatch):
    result, current = computation(tmp_path)
    original = execution_manifest(result, current["identity"])
    path = write_execution_manifest(tmp_path, original)
    replacement = deepcopy(original)
    replacement["computational_declaration"]["targets"][0]["command"] += " "
    real_fsync = os.fsync

    def fail_file_sync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("injected record sync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_file_sync)
    with pytest.raises(OSError, match="injected record sync failure"):
        write_execution_manifest(tmp_path, replacement)
    assert read_execution_manifest(tmp_path, current["identity"]) == original
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("target,attempt", [
    ("../../outside", "../../other"), ("/tmp/escaped", "/tmp/attempt"),
    (".", ".."), ("a" * 300, "b" * 300), ("分析 / step", "try / 1"),
])
def test_record_names_cannot_escape_the_computation_directory(tmp_path, target, attempt):
    _, current = computation(tmp_path)
    identity = current["identity"]
    root = execution_manifest_path(tmp_path, identity).parent
    selection_path = current_attempt_path(tmp_path, identity, target)
    success_path = receipt_path(tmp_path, identity, target, attempt)
    assert selection_path.is_relative_to(root)
    assert success_path.is_relative_to(root)
    assert ".." not in selection_path.parts + success_path.parts
    assert selection_path.parent.parent == root / "targets"
    assert success_path.parent.parent == selection_path.parent / "attempts"
    selected = current_attempt(identity, target, attempt)
    write_runtime_record(selection_path, selected)
    assert read_runtime_record(selection_path) == selected


def test_different_names_never_alias_the_same_record_path(tmp_path):
    _, current = computation(tmp_path)
    names = ["copy", "a/b", "a%2Fb", "a_b", "..", ".", "分析", "a" * 300]
    paths = [current_attempt_path(tmp_path, current["identity"], name) for name in names]
    assert len(set(paths)) == len(names)


def test_invalid_identity_is_rejected_before_constructing_an_authority_path(tmp_path):
    with pytest.raises(PlanError, match="identity"):
        execution_manifest_path(tmp_path, "../" + "x" * 61)


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
    require_consistent_definition(execution_manifest(result, current["identity"]), other)


@pytest.mark.parametrize("field,value", [
    ("input_interface", []), ("output_interface", {"result": "../../outside"}),
    ("computational_parameters", {"bad": float("nan")}),
    ("computational_edges", [{"producer": "missing", "consumer": "d", "kind": "explicit"}]),
    ("entry_targets", ["missing"]), ("terminal_targets", ["a"]),
    ("internal_outputs", []), ("whole_producer_dependencies", ["bad-id"]),
])
def test_malformed_declarations_are_rejected_as_records(tmp_path, field, value):
    result = plan(load("examples.internal_graph:main"), {"source": "reads.txt"}, project=tmp_path)
    record = execution_manifest(result, result["computations"][0]["identity"])
    record["computational_declaration"][field] = value
    with pytest.raises(PlanError):
        validate_execution_manifest(record)


@pytest.mark.parametrize("field,value", [
    ("name", []), ("dependencies", ["unknown"]), ("inputs", ["relative-path"]),
    ("output_kinds", {}), ("always_run", True),
    ("environment", {"kind": "host", "declaration": "pretend-image"}),
])
def test_malformed_targets_never_escape_validation_as_python_errors(tmp_path, field, value):
    result = plan(load("examples.internal_graph:main"), {"source": "reads.txt"}, project=tmp_path)
    record = execution_manifest(result, result["computations"][0]["identity"])
    record["computational_declaration"]["targets"][0][field] = value
    with pytest.raises(PlanError):
        validate_execution_manifest(record)


def test_reordered_retained_graph_is_not_a_definition_change(tmp_path):
    (tmp_path / "reads.txt").write_text("input\n")
    result = plan(load("examples.internal_graph:main"), {"source": "reads.txt"}, project=tmp_path)
    record = execution_manifest(result, result["computations"][0]["identity"])
    path = write_execution_manifest(tmp_path, record)
    declaration = record["computational_declaration"]
    for key in ("targets", "computational_edges", "internal_outputs"):
        declaration[key].reverse()
    for target in declaration["targets"]:
        target["dependencies"].reverse()
    path.write_text(json.dumps(record))
    assert read_execution_manifest(tmp_path, record["identity"]) == record
    result = runtime_cli(tmp_path, "--dry-run", "examples.internal_graph:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr


def test_runtime_command_enforces_saved_visible_declaration(tmp_path):
    (tmp_path / "reads.txt").write_text("input\n")
    result = plan(load("examples.runtime_records:main"), {"source": "reads.txt"}, project=tmp_path)
    current = result["computations"][0]
    write_execution_manifest(tmp_path, execution_manifest(result, current["identity"]))
    reusable = runtime_cli(tmp_path, "--dry-run", "examples.runtime_records:main", "--bindings", '{"source":"reads.txt"}')
    assert reusable.returncode == 0, reusable.stderr
    changed = runtime_cli(tmp_path, "--dry-run", "examples.runtime_records:changed", "--bindings", '{"source":"reads.txt"}')
    assert changed.returncode == 2
    assert "publish a new subpipeline version" in changed.stderr


@pytest.mark.parametrize("original,replacement", [
    ("boolean_parameter", "integer_parameter"), ("integer_parameter", "float_parameter"),
])
def test_command_rejects_changed_parameter_type_under_the_same_version(tmp_path, original, replacement):
    (tmp_path / "reads.txt").write_text("input\n")
    result = plan(load(f"examples.runtime_records:{original}"), {"source": "reads.txt"}, project=tmp_path)
    write_execution_manifest(tmp_path, execution_manifest(result, result["computations"][0]["identity"]))
    changed = runtime_cli(tmp_path, "--dry-run", f"examples.runtime_records:{replacement}", "--bindings", '{"source":"reads.txt"}')
    assert changed.returncode == 2, changed.stdout + changed.stderr
    assert "publish a new subpipeline version" in changed.stderr


def test_required_attempt_tracking_records_have_independent_roles(tmp_path):
    _, current = computation(tmp_path)
    identity = current["identity"]
    attempt = "attempt-1"
    records = [
        current_attempt(identity, "copy", attempt),
        success_receipt(identity, "copy", attempt, [{"path": str(tmp_path / "results/copy.txt"), "mtime_ns": 7}]),
        job_association(identity, "copy", attempt, "12345"),
        attempt_diagnostic(identity, "copy", attempt, str(tmp_path / "logs/stdout"), str(tmp_path / "logs/stderr")),
        submission_intent("submission-1", [{"identity": identity, "target": "copy", "attempt": attempt, "ownership": "gwflow:submission-1"}]),
    ]
    assert all(validate_runtime_record(record) is None for record in records)
    corrupt = deepcopy(records[1])
    corrupt["attempt"] = "newer-attempt"
    assert corrupt["attempt"] != records[0]["attempt"]
    assert validate_runtime_record(corrupt) is None


@pytest.mark.parametrize("record_kind", ["current-attempt", "success-receipt", "job-association", "attempt-diagnostic", "submission-intent"])
def test_boolean_revision_is_not_an_integer_record_revision(tmp_path, record_kind):
    _, current = computation(tmp_path)
    identity = current["identity"]
    record = {
        "current-attempt": current_attempt(identity, "copy", "one"),
        "success-receipt": success_receipt(identity, "copy", "one", []),
        "job-association": job_association(identity, "copy", "one", "123"),
        "attempt-diagnostic": attempt_diagnostic(identity, "copy", "one", "/logs/stdout", "/logs/stderr"),
        "submission-intent": submission_intent("submission-1", []),
    }[record_kind]
    record["record_revision"] = True
    with pytest.raises(PlanError):
        validate_runtime_record(record)


def test_receipts_reject_duplicate_or_unresolved_output_observations(tmp_path):
    _, current = computation(tmp_path)
    output = {"path": str(tmp_path / "output"), "mtime_ns": 7}
    for outputs in ([output, output], [{"path": "relative-output", "mtime_ns": 7}]):
        with pytest.raises(PlanError):
            success_receipt(current["identity"], "copy", "one", outputs)


@pytest.mark.parametrize("damage", ["duplicate-key", "non-utf8", "wrong-identity", "non-finite-environment"])
def test_unreadable_or_misfiled_manifests_are_not_definition_violations(tmp_path, damage):
    result, current = computation(tmp_path)
    record = execution_manifest(result, current["identity"])
    path = write_execution_manifest(tmp_path, record)
    if damage == "duplicate-key":
        path.write_text('{"kind":"invalid",' + json.dumps(record)[1:])
    elif damage == "non-utf8":
        path.write_bytes(b"\xff")
    elif damage == "non-finite-environment":
        record["computational_declaration"]["targets"][0]["environment"]["declaration"] = float("nan")
        path.write_text(json.dumps(record))
    else:
        other = plan(load("examples.one_file:main"), {"source": "other.txt"}, project=tmp_path)
        path.write_text(json.dumps(execution_manifest(other, other["computations"][0]["identity"])))
    with pytest.raises(UnsupportedEvidence):
        read_execution_manifest(tmp_path, current["identity"])


def test_runnable_record_demo_grades_real_product_commands(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.runtime_records_demo",
                             "--project", str(tmp_path / "demo")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert [(case["case"], case["exit"]) for case in report["cases"]] == [
        ("unchanged", 0), ("command-whitespace", 2), ("target-rename", 2),
        ("resources-and-provenance", 0), ("different-binding", 0),
        ("boolean-to-integer-parameter", 2),
    ]
    assert report["schema_roundtrips"] == [
        "current-attempt", "success-receipt", "job-association", "attempt-diagnostic", "submission-intent",
    ]
