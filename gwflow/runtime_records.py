"""Versioned retained runtime declarations, distinct from planning manifests.

These records are not completion evidence by themselves.  They preserve the
visible computational declaration used to detect a changed published definition
for the *same* bound computation in a later runtime command.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from .identity import address
from .planner import PlanError


RUNTIME_RECORD_REVISION = 1


def _fail(detail):
    raise PlanError(f"runtime record: {detail}")


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def computational_declaration(computation):
    """Return the canonical, visible declaration protected by ADR 0009.

    Target and graph ordering are representation-only.  Command text, target
    names, file-list ordering, declared environments, and all other visible
    computational declarations remain literal.
    """
    try:
        targets = [
            {
                "name": target["name"],
                "command": target["command"],
                "inputs": deepcopy(target["inputs"]),
                "outputs": deepcopy(target["outputs"]),
                "dependencies": sorted(target["dependencies"]),
                "output_kinds": deepcopy(target["output_kinds"]),
                "always_run": target["always_run"],
                "environment": deepcopy(target["environment"]),
            }
            for target in computation["targets"]
        ]
        edges = [deepcopy(edge) for edge in computation["computational_edges"]]
        projection = {
            "definition": {key: computation["definition"][key] for key in ("name", "version")},
            "input_interface": deepcopy(computation["input_interface"]),
            "output_interface": deepcopy(computation["output_interface"]),
            "computational_parameters": deepcopy(computation["computational_parameters"]),
            "targets": sorted(targets, key=lambda target: target["name"]),
            "computational_edges": sorted(edges, key=_canonical),
            "entry_targets": sorted(computation["entry_targets"]),
            "terminal_targets": sorted(computation["terminal_targets"]),
            "internal_outputs": sorted(computation["internal_outputs"]),
            "whole_producer_dependencies": sorted(computation["whole_producer_dependencies"]),
        }
    except (KeyError, TypeError) as exc:
        _fail("cannot derive computational declaration from planned computation")
    return json.loads(_canonical(projection))


def execution_manifest(plan, identity):
    """Create a detached runtime declaration record for one planned computation."""
    try:
        computation = next(item for item in plan["computations"] if item["identity"] == identity)
        record = {
            "kind": "execution-computation",
            "record_revision": RUNTIME_RECORD_REVISION,
            "identity": identity,
            "descriptor": deepcopy(computation["descriptor"]),
            "computational_declaration": computational_declaration(computation),
        }
    except (KeyError, StopIteration, TypeError) as exc:
        _fail(f"missing computation for {identity!r}")
    validate_execution_manifest(record)
    return record


def validate_execution_manifest(record):
    """Validate a retained declaration without interpreting execution success."""
    if type(record) is not dict or set(record) != {"kind", "record_revision", "identity", "descriptor", "computational_declaration"}:
        _fail("execution manifest has unexpected fields")
    if record["kind"] != "execution-computation" or record["record_revision"] != RUNTIME_RECORD_REVISION:
        _fail("unsupported execution-manifest revision")
    descriptor = record["descriptor"]
    if type(descriptor) is not dict or set(descriptor) != {"identity_version", "definition", "bindings"}:
        _fail("invalid identity descriptor")
    if descriptor["identity_version"] != 1 or type(descriptor["definition"]) is not dict:
        _fail("unsupported identity descriptor")
    try:
        expected, _ = address(descriptor["definition"]["name"], descriptor["definition"]["version"], descriptor["bindings"])
    except (KeyError, TypeError, ValueError) as exc:
        _fail("invalid identity descriptor")
    if record["identity"] != expected:
        _fail("identity does not match descriptor")
    projection = record["computational_declaration"]
    if type(projection) is not dict:
        _fail("invalid computational declaration")
    definition = projection.get("definition")
    if type(definition) is not dict or definition != descriptor["definition"]:
        _fail("declaration definition does not match descriptor")
    required = {"definition", "input_interface", "output_interface", "computational_parameters", "targets", "computational_edges", "entry_targets", "terminal_targets", "internal_outputs", "whole_producer_dependencies"}
    if set(projection) != required or type(projection["targets"]) is not list:
        _fail("invalid computational declaration")
    target_fields = {"name", "command", "inputs", "outputs", "dependencies", "output_kinds", "always_run", "environment"}
    if any(type(target) is not dict or set(target) != target_fields for target in projection["targets"]):
        _fail("invalid target declaration")
    names = [target["name"] for target in projection["targets"]]
    if len(names) != len(projection["targets"]) or names != sorted(names) or len(set(names)) != len(names):
        _fail("targets must have sorted distinct names")
    for target in projection["targets"]:
        if type(target["name"]) is not str or not target["name"] or type(target["command"]) is not str or not target["command"]:
            _fail("invalid target declaration")
        if any(type(target[key]) is not list or any(type(item) is not str for item in target[key]) for key in ("inputs", "outputs", "dependencies")):
            _fail("invalid target declaration")
        if type(target["output_kinds"]) is not dict or type(target["always_run"]) is not bool or type(target["environment"]) is not dict:
            _fail("invalid target declaration")


def _identity(value, label):
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail(f"invalid {label} computation identity")


def _token(value, label):
    if type(value) is not str or not value or "\0" in value:
        _fail(f"invalid {label}")


def validate_runtime_record(record):
    """Validate any revision-1 record used by the Phase 2 runtime protocol."""
    if type(record) is not dict or record.get("record_revision") != RUNTIME_RECORD_REVISION:
        _fail("unsupported runtime-record revision")
    kind = record.get("kind")
    if kind == "execution-computation":
        return validate_execution_manifest(record)
    common = {"kind", "record_revision", "identity", "target", "attempt"}
    if kind == "current-attempt":
        if set(record) != common:
            _fail("current attempt has unexpected fields")
    elif kind == "success-receipt":
        if set(record) != common | {"outputs"} or type(record["outputs"]) is not list:
            _fail("success receipt has unexpected fields")
        for output in record["outputs"]:
            if type(output) is not dict or set(output) != {"path", "mtime_ns"} or type(output["path"]) is not str or type(output["mtime_ns"]) is not int or isinstance(output["mtime_ns"], bool):
                _fail("invalid success receipt output")
    elif kind == "job-association":
        if set(record) != common | {"job_id"}:
            _fail("job association has unexpected fields")
        _token(record["job_id"], "job ID")
    elif kind == "attempt-diagnostic":
        if set(record) != common | {"stdout", "stderr"}:
            _fail("attempt diagnostic has unexpected fields")
        _token(record["stdout"], "stdout path")
        _token(record["stderr"], "stderr path")
    elif kind == "submission-intent":
        if set(record) != {"kind", "record_revision", "submission", "targets"} or type(record["targets"]) is not list:
            _fail("submission intent has unexpected fields")
        _token(record["submission"], "submission token")
        for target in record["targets"]:
            if type(target) is not dict or set(target) != {"identity", "target", "attempt", "ownership"}:
                _fail("invalid submission intent target")
            _identity(target["identity"], "submission intent")
            _token(target["target"], "target")
            _token(target["attempt"], "attempt")
            _token(target["ownership"], "ownership")
        return
    else:
        _fail("unsupported runtime record kind")
    _identity(record["identity"], kind)
    _token(record["target"], "target")
    _token(record["attempt"], "attempt")


def current_attempt(identity, target, attempt):
    record = {"kind": "current-attempt", "record_revision": RUNTIME_RECORD_REVISION, "identity": identity, "target": target, "attempt": attempt}
    validate_runtime_record(record)
    return record


def success_receipt(identity, target, attempt, outputs):
    record = {"kind": "success-receipt", "record_revision": RUNTIME_RECORD_REVISION, "identity": identity, "target": target, "attempt": attempt, "outputs": outputs}
    validate_runtime_record(record)
    return record


def job_association(identity, target, attempt, job_id):
    record = {"kind": "job-association", "record_revision": RUNTIME_RECORD_REVISION, "identity": identity, "target": target, "attempt": attempt, "job_id": job_id}
    validate_runtime_record(record)
    return record


def attempt_diagnostic(identity, target, attempt, stdout, stderr):
    record = {"kind": "attempt-diagnostic", "record_revision": RUNTIME_RECORD_REVISION, "identity": identity, "target": target, "attempt": attempt, "stdout": stdout, "stderr": stderr}
    validate_runtime_record(record)
    return record


def submission_intent(submission, targets):
    record = {"kind": "submission-intent", "record_revision": RUNTIME_RECORD_REVISION, "submission": submission, "targets": targets}
    validate_runtime_record(record)
    return record


def execution_manifest_path(project, identity):
    """Return the maintained path for a bound computation's retained declaration."""
    if type(identity) is not str or len(identity) != 64:
        _fail("invalid computation identity")
    return Path(project) / ".gwflow" / "runtime" / f"v{RUNTIME_RECORD_REVISION}" / "computations" / identity[:2] / identity / "manifest.json"


def write_execution_manifest(project, record):
    """Atomically publish a validated declaration when submission creates it."""
    validate_execution_manifest(record)
    path = execution_manifest_path(project, record["identity"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".manifest-", delete=False) as handle:
        json.dump(record, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def read_execution_manifest(project, identity):
    """Load a retained declaration, or return ``None`` when none was published."""
    path = execution_manifest_path(project, identity)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read execution manifest for {identity}: {exc}")
    validate_execution_manifest(record)
    return record


def require_consistent_definition(saved, computation):
    """Reject a visible changed declaration under the same bound computation."""
    validate_execution_manifest(saved)
    current = computational_declaration(computation)
    if saved["computational_declaration"] != current:
        name = current["definition"]["name"]
        version = current["definition"]["version"]
        _fail(f"visible computational declaration changed for {name}@{version}; publish a new subpipeline version")
