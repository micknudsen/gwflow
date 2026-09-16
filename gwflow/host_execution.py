"""Host-only compute-job integration; this is not a local submission backend."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from gwf import Target as GwfTarget
from gwf.executors import serialize

from .planner import PlanError
from .record_io import publish_json, read_json
from .runtime_records import attempt_diagnostic, current_attempt, current_attempt_path, read_runtime_record, receipt_path, success_receipt, write_runtime_record


OUTPUT_CHECK_FAILURE = 72
RECEIPT_PUBLICATION_FAILURE = 73
ATTEMPT_FENCE_FAILURE = 74
ATTEMPT_ALREADY_STARTED = 75


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    attempt: str
    stdout: Path
    stderr: Path


def _paths(project, computation, target, attempt):
    root = receipt_path(project, computation["identity"], target["name"], attempt).parent
    return root / "stdout.log", root / "stderr.log"


def scheduler_name(identity, target, attempt):
    encoded = json.dumps([identity, target, attempt], ensure_ascii=True, separators=(",", ":"))
    return "gwflow_" + hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _run_payload(project, computation, target, attempt, stdout, stderr):
    """Use installed gwf's Bash envelope, not an imitation of its shell flags."""
    payload = GwfTarget(scheduler_name(computation["identity"], target["name"], attempt),
                        target["inputs"], target["outputs"], {},
                        working_dir=computation["work_dir"], spec=target["command"])
    script = stdout.parent / "payload.gwf"
    with script.open("x", encoding="utf-8") as handle:
        serialize(payload, handle)
    environment = os.environ.copy()
    environment["GWF_EXEC_WORKFLOW_ROOT"] = str(project)
    with stdout.open("wb") as out, stderr.open("wb") as err:
        return subprocess.run([sys.executable, "-m", "gwf.exec", str(script)],
                              cwd=computation["work_dir"], env=environment,
                              stdout=out, stderr=err, check=False).returncode


def _validate_invocation(record):
    def invalid():
        raise PlanError("host executor: invalid host invocation record")

    if type(record) is not dict or set(record) != {"kind", "invocation_revision", "project", "computation", "target", "attempt"}:
        invalid()
    if record["kind"] != "host-invocation" or type(record["invocation_revision"]) is not int or record["invocation_revision"] != 1:
        invalid()
    project, computation, target = record["project"], record["computation"], record["target"]
    if type(project) is not str or not os.path.isabs(project) or os.path.normpath(project) != project or "\0" in project:
        invalid()
    if type(computation) is not dict or set(computation) != {"identity", "work_dir", "result_dir"}:
        invalid()
    if type(target) is not dict or set(target) != {"name", "command", "inputs", "outputs", "environment"}:
        invalid()
    current_attempt(computation["identity"], target["name"], record["attempt"])
    for key, folder in (("work_dir", "work"), ("result_dir", "results")):
        if computation[key] != str(Path(project) / folder / computation["identity"][:2] / computation["identity"]):
            invalid()
    if target["environment"] != {"kind": "host", "declaration": None}:
        raise PlanError("host executor: execution is host-only")
    if type(target["command"]) is not str or not target["command"] or "\0" in target["command"]:
        invalid()
    for role in ("inputs", "outputs"):
        if type(target[role]) is not list:
            invalid()
        for path in target[role]:
            if type(path) is not str or "\0" in path or not os.path.isabs(path) or os.path.normpath(path) != path:
                invalid()
            if role == "outputs" and not any(Path(path).is_relative_to(root) and path != root for root in (computation["work_dir"], computation["result_dir"])):
                invalid()
    if len(set(target["outputs"])) != len(target["outputs"]):
        invalid()


def prepare_attempt(project, computation, target, attempt):
    """Durably select a never-used attempt before the scheduler can accept it.

    The submission command owns serialization and active-job checks. Preparing
    an attempt does not execute a payload or submit a job.
    """
    record = {"kind": "host-invocation", "invocation_revision": 1,
              "project": os.path.abspath(project),
              "computation": {key: computation[key] for key in ("identity", "work_dir", "result_dir")},
              "target": {key: target[key] for key in ("name", "command", "inputs", "outputs", "environment")},
              "attempt": attempt}
    _validate_invocation(record)
    project = record["project"]
    stdout, stderr = _paths(project, computation, target, attempt)
    try:
        stdout.parent.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise PlanError(f"host executor: attempt {attempt!r} already exists; use a new attempt") from exc
    request = publish_json(stdout.parent / "invocation.json", record)
    write_runtime_record(stdout.parent / "diagnostic.json", attempt_diagnostic(computation["identity"], target["name"], attempt, str(stdout), str(stderr)))
    write_runtime_record(current_attempt_path(project, computation["identity"], target["name"]), current_attempt(computation["identity"], target["name"], attempt))
    for directory in (Path(computation["work_dir"]), Path(computation["result_dir"])):
        directory.mkdir(parents=True, exist_ok=True)
    return request


def _selected(project, computation, target, attempt):
    try:
        selected = read_runtime_record(current_attempt_path(project, computation["identity"], target["name"]))
    except (PlanError, OSError):
        return False
    return selected == current_attempt(computation["identity"], target["name"], attempt)


def _failed(code, attempt, stdout, stderr, message):
    try:
        with stderr.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        print(message, file=sys.stderr)
    return ExecutionResult(code, attempt, stdout, stderr)


def run_prepared(request):
    """Execute a selected attempt once. Workers never write current selection."""
    record = read_json(request)
    _validate_invocation(record)
    project, computation, target, attempt = (record[key] for key in ("project", "computation", "target", "attempt"))
    stdout, stderr = _paths(project, computation, target, attempt)
    if Path(request).absolute() != stdout.parent / "invocation.json":
        raise PlanError("host executor: invocation is filed under a different attempt")
    if not _selected(project, computation, target, attempt):
        return _failed(ATTEMPT_FENCE_FAILURE, attempt, stdout, stderr, "attempt is no longer selected; payload not started")
    started = stdout.parent / "started"
    try:
        started.mkdir()
    except FileExistsError:
        return _failed(ATTEMPT_ALREADY_STARTED, attempt, stdout, stderr, "attempt already started; payload not repeated")
    # Persist the once-only claim before executing. A failed/interrupted claim
    # is not automatically taken over: recovery creates a new attempt.
    publish_json(started / "claim.json", {"attempt": attempt})
    try:
        returncode = _run_payload(project, computation, target, attempt, stdout, stderr)
    except OSError as exc:
        return _failed(ATTEMPT_FENCE_FAILURE, attempt, stdout, stderr, f"payload launch failed: {exc}")
    if returncode:
        return ExecutionResult(returncode, attempt, stdout, stderr)
    outputs = []
    try:
        for path in target["outputs"]:
            observed = Path(path).stat()
            if not stat.S_ISREG(observed.st_mode):
                raise OSError(f"required output is not a regular file: {path}")
            outputs.append({"path": path, "mtime_ns": observed.st_mtime_ns})
    except OSError as exc:
        return _failed(OUTPUT_CHECK_FAILURE, attempt, stdout, stderr, f"required output check failed: {exc}")
    if not _selected(project, computation, target, attempt):
        return _failed(ATTEMPT_FENCE_FAILURE, attempt, stdout, stderr, "attempt is no longer selected; success not published")
    receipt = success_receipt(computation["identity"], target["name"], attempt, outputs)
    try:
        write_runtime_record(receipt_path(project, computation["identity"], target["name"], attempt), receipt)
    except OSError as error:
        return _failed(RECEIPT_PUBLICATION_FAILURE, attempt, stdout, stderr, f"required receipt publication failed: {error}")
    return ExecutionResult(0, attempt, stdout, stderr)


def execute(project, computation, target, attempt):
    """Local integration harness: prepare then run the same compute-job path."""
    return run_prepared(prepare_attempt(project, computation, target, attempt))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Internal host compute-job entry point")
    parser.add_argument("invocation", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_prepared(args.invocation)
    except (PlanError, OSError, ValueError) as exc:
        print(f"gwflow host job: {exc}", file=sys.stderr)
        return ATTEMPT_FENCE_FAILURE
    print(json.dumps({"kind": "host-execution-result", "attempt": result.attempt,
                      "returncode": result.returncode, "stdout": str(result.stdout), "stderr": str(result.stderr)}))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
