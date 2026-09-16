"""Versioned retained runtime declarations, distinct from planning manifests.

These records are not completion evidence by themselves.  They preserve the
visible computational declaration used to detect a changed published definition
for the *same* bound computation in a later runtime command.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from .planner import PlanError
from .record_io import publish_json, read_json
from .runtime_declarations import canonical as _canonical, normalized, validate as validate_declaration


RUNTIME_RECORD_REVISION = 1


class UnsupportedEvidence(PlanError):
    """An indispensable completion record cannot be interpreted safely."""


class UnsupportedTracking(PlanError):
    """Authoritative job association data cannot be interpreted safely."""


def _fail(detail):
    raise PlanError(f"runtime record: {detail}")


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
                "dependencies": deepcopy(target["dependencies"]),
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
            "targets": targets,
            "computational_edges": edges,
            "entry_targets": deepcopy(computation["entry_targets"]),
            "terminal_targets": deepcopy(computation["terminal_targets"]),
            "internal_outputs": deepcopy(computation["internal_outputs"]),
            "whole_producer_dependencies": deepcopy(computation["whole_producer_dependencies"]),
        }
    except (KeyError, TypeError) as exc:
        _fail("cannot derive computational declaration from planned computation")
    return json.loads(_canonical(normalized(projection)))


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
    validate_execution_manifest(record, project=plan["project"])
    return record


def validate_execution_manifest(record, *, project=None):
    """Validate a retained declaration without interpreting execution success."""
    validate_declaration(record, project=project)


def _identity(value, label):
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail(f"invalid {label} computation identity")


def _token(value, label):
    if type(value) is not str or not value or "\0" in value:
        _fail(f"invalid {label}")


def _path(value, label):
    _token(value, label)
    if not os.path.isabs(value) or os.path.normpath(value) != value:
        _fail(f"invalid {label}: expected normalized absolute path")


def validate_runtime_record(record):
    """Validate any revision-1 record used by the Phase 2 runtime protocol."""
    if type(record) is not dict or type(record.get("record_revision")) is not int or record["record_revision"] != RUNTIME_RECORD_REVISION:
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
            _path(output["path"], "receipt output")
        if len({output["path"] for output in record["outputs"]}) != len(record["outputs"]):
            _fail("duplicate success receipt output")
    elif kind == "job-association":
        if set(record) != common | {"job_id"}:
            _fail("job association has unexpected fields")
        _token(record["job_id"], "job ID")
    elif kind == "attempt-diagnostic":
        if set(record) != common | {"stdout", "stderr"}:
            _fail("attempt diagnostic has unexpected fields")
        _path(record["stdout"], "stdout path")
        _path(record["stderr"], "stderr path")
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
    _identity(identity, "runtime")
    return Path(project) / ".gwflow" / "runtime" / f"v{RUNTIME_RECORD_REVISION}" / "computations" / identity[:2] / identity / "manifest.json"


def computation_directory(project, identity):
    return execution_manifest_path(project, identity).parent


def _component(value):
    _token(value, "record path component")
    if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}", value):
        return value
    # The reserved prefix prevents an encoded name aliasing a literal name.
    return "~" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_attempt_path(project, identity, target):
    return computation_directory(project, identity) / "targets" / _component(target) / "current.json"


def receipt_path(project, identity, target, attempt):
    return current_attempt_path(project, identity, target).parent / "attempts" / _component(attempt) / "receipt.json"


def write_runtime_record(path, record):
    """Durably publish one validated retained record at its selected path."""
    validate_runtime_record(record)
    return publish_json(path, record)


def read_runtime_record(path):
    """Read and validate a required runtime record, returning ``None`` if absent."""
    path = Path(path)
    try:
        record = read_json(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        _fail(f"cannot read {path}: {exc}")
    validate_runtime_record(record)
    return record


def write_execution_manifest(project, record):
    """Durably publish a validated declaration when submission creates it."""
    validate_execution_manifest(record, project=project)
    return publish_json(execution_manifest_path(project, record["identity"]), record)


def read_execution_manifest(project, identity):
    """Load a retained declaration, or return ``None`` when none was published."""
    path = execution_manifest_path(project, identity)
    try:
        record = read_json(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise UnsupportedEvidence(f"runtime record: unreadable execution manifest for {identity}: {exc}") from exc
    try:
        validate_execution_manifest(record, project=project)
        if record["identity"] != identity:
            _fail("execution manifest belongs to a different computation")
    except PlanError as exc:
        raise UnsupportedEvidence(f"runtime record: unsupported execution manifest for {identity}: {exc}") from exc
    return record


def tracking_path(project):
    return Path(project) / ".gwflow" / "runtime" / f"v{RUNTIME_RECORD_REVISION}" / "tracking.json"


def validate_tracking(record):
    if type(record) is not dict or set(record) != {"kind", "tracking_revision", "associations"}:
        raise UnsupportedTracking("runtime record: tracking has unexpected fields")
    if record["kind"] != "job-tracking" or type(record["tracking_revision"]) is not int or record["tracking_revision"] != 1 or type(record["associations"]) is not dict:
        raise UnsupportedTracking("runtime record: unsupported job tracking revision")
    job_ids = set()
    try:
        for key, association in record["associations"].items():
            validate_runtime_record(association)
            if association["kind"] != "job-association" or key != association_key(association["identity"], association["target"]):
                _fail("misfiled job association")
            if association["job_id"] in job_ids:
                _fail("one job ID is associated with multiple targets")
            job_ids.add(association["job_id"])
    except PlanError as exc:
        raise UnsupportedTracking(f"runtime record: invalid authoritative tracking: {exc}") from exc


def association_key(identity, target):
    _identity(identity, "job association")
    _token(target, "target")
    return f"{identity}:{target}"


def job_tracking(associations=()):
    """Build authoritative latest-job associations, independently of receipts."""
    record = {"kind": "job-tracking", "tracking_revision": 1, "associations": {}}
    for association in associations:
        validate_runtime_record(association)
        if association["kind"] != "job-association":
            raise UnsupportedTracking("runtime record: expected a job association")
        key = association_key(association["identity"], association["target"])
        if key in record["associations"]:
            raise UnsupportedTracking("runtime record: duplicate target association")
        record["associations"][key] = deepcopy(association)
    validate_tracking(record)
    return record


def write_tracking(project, record):
    """Publish an already established authoritative association set durably."""
    validate_tracking(record)
    return publish_json(tracking_path(project), record)


def _require_tracked_history(project, record):
    """Detect missing authority without reconstructing it from completion data."""
    selections = {
        current_attempt_path(project, item["identity"], item["target"]): item
        for item in record["associations"].values()
    }
    for directory in _retained_target_directories(project):
        if directory / "current.json" not in selections:
            raise UnsupportedTracking(f"runtime record: retained target history has no authoritative job association: {directory}; manual recovery is required")
    for path, association in selections.items():
        try:
            selected = read_runtime_record(path)
        except PlanError:
            # Missing/incompatible completion evidence is ordinary recovery,
            # not loss of the independent authoritative association.
            continue
        if selected is not None and selected["kind"] == "current-attempt" and all(selected[key] == association[key] for key in ("identity", "target")) and selected["attempt"] != association["attempt"]:
            raise UnsupportedTracking(f"runtime record: selected attempt has no matching authoritative job association: {path}; manual recovery is required")


def _retained_target_directories(project):
    root = tracking_path(project).parent / "computations"
    if not root.exists():
        return

    def unreadable(error):
        raise error

    # Do not let glob's suppressed traversal errors masquerade as no history.
    # Only inspect target directory names; receipt/log contents are not authority.
    for directory, children, _ in os.walk(root, onerror=unreadable):
        directory = Path(directory)
        depth = len(directory.relative_to(root).parts)
        if depth == 3:
            if directory.name == "targets":
                for name in children:
                    yield directory / name
            children[:] = []


def _has_owned_locations(project):
    # Surviving owned slots signal lost authority, never successful execution.
    # Other user work/results directories do not match this reserved layout.
    for role in ("work", "results"):
        root = Path(project) / role
        if not root.exists():
            continue
        for prefix in root.iterdir():
            if re.fullmatch(r"[0-9a-f]{2}", prefix.name):
                for slot in prefix.iterdir():
                    if re.fullmatch(r"[0-9a-f]{64}", slot.name) and slot.name.startswith(prefix.name):
                        return True
    return False


def read_tracking(project):
    path = tracking_path(project)
    try:
        if not path.exists():
            if path.parent.parent.exists() or _has_owned_locations(project):
                raise UnsupportedTracking("runtime record: authoritative job tracking is missing from a retained runtime or owned computation location; manual recovery is required")
            return None
        record = read_json(path)
        validate_tracking(record)
        if any(entry.name != path.parent.name for entry in path.parent.parent.iterdir()):
            raise UnsupportedTracking("runtime record: unsupported retained runtime namespace; authoritative tracking cannot be established")
        _require_tracked_history(project, record)
    except (OSError, ValueError, PlanError) as exc:
        if isinstance(exc, UnsupportedTracking):
            raise
        raise UnsupportedTracking(f"runtime record: unreadable job tracking: {exc}") from exc
    return record


def require_consistent_definition(saved, computation):
    """Reject a visible changed declaration under the same bound computation."""
    validate_execution_manifest(saved)
    if saved["identity"] != computation["identity"]:
        return
    current = computational_declaration(computation)
    if _canonical(normalized(saved["computational_declaration"])) != _canonical(current):
        name = current["definition"]["name"]
        version = current["definition"]["version"]
        _fail(f"visible computational declaration changed for {name}@{version}; publish a new subpipeline version")
