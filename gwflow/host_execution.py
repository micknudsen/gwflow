"""Host-only target execution with attempt fencing and durable receipts."""
from dataclasses import dataclass
from pathlib import Path
import subprocess

from .planner import PlanError
from .runtime_records import attempt_diagnostic, current_attempt, current_attempt_path, receipt_path, success_receipt, write_runtime_record


OUTPUT_CHECK_FAILURE = 72
RECEIPT_PUBLICATION_FAILURE = 73


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    attempt: str
    stdout: Path
    stderr: Path


def _paths(project, computation, target, attempt):
    root = current_attempt_path(project, computation["identity"], target["name"]).parent / "attempts" / attempt
    return root / "stdout.log", root / "stderr.log"


def execute(project, computation, target, attempt):
    """Run one planned host target and publish receipt only on complete success."""
    if target["environment"]["kind"] != "host":
        raise PlanError(f"host executor: {target['name']} declares {target['environment']['kind']}")
    current = current_attempt(computation["identity"], target["name"], attempt)
    # This fence is durable before Bash can replace anything in the result slot.
    write_runtime_record(current_attempt_path(project, computation["identity"], target["name"]), current)
    for directory in (Path(computation["work_dir"]), Path(computation["result_dir"])):
        directory.mkdir(parents=True, exist_ok=True)
    stdout, stderr = _paths(project, computation, target, attempt)
    stdout.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["bash", "-c", target["command"]], cwd=project, text=True, capture_output=True)
    stdout.write_text(result.stdout, encoding="utf-8")
    stderr.write_text(result.stderr, encoding="utf-8")
    write_runtime_record(stdout.parent / "diagnostic.json", attempt_diagnostic(computation["identity"], target["name"], attempt, str(stdout), str(stderr)))
    if result.returncode:
        return ExecutionResult(result.returncode, attempt, stdout, stderr)
    missing = [path for path in target["outputs"] if not Path(path).is_file()]
    if missing:
        stderr.write_text(result.stderr + f"required outputs missing: {missing}\n", encoding="utf-8")
        return ExecutionResult(OUTPUT_CHECK_FAILURE, attempt, stdout, stderr)
    receipt = success_receipt(
        computation["identity"], target["name"], attempt,
        [{"path": path, "mtime_ns": Path(path).stat().st_mtime_ns} for path in target["outputs"]],
    )
    try:
        write_runtime_record(receipt_path(project, computation["identity"], target["name"], attempt), receipt)
    except OSError as error:
        stderr.write_text(result.stderr + f"required receipt publication failed: {error}\n", encoding="utf-8")
        return ExecutionResult(RECEIPT_PUBLICATION_FAILURE, attempt, stdout, stderr)
    return ExecutionResult(0, attempt, stdout, stderr)
