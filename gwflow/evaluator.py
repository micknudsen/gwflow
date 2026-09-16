"""Read-only evaluation of retained runtime state and target freshness."""
from dataclasses import dataclass
from pathlib import Path

from .planner import PlanError
from .runtime_records import UnsupportedEvidence, UnsupportedTracking, current_attempt_path, read_execution_manifest, read_runtime_record, read_tracking, receipt_path, require_consistent_definition


ACTIVE = {"submitted", "running"}
FAILED = {"failed", "cancelled"}


@dataclass(frozen=True)
class TargetDecision:
    name: str
    decision: str
    reason: str
    evidence: tuple[str, ...] = ()
    job_ids: tuple[str, ...] = ()


def _status(statuses, computation, target):
    value = statuses.get((computation["identity"], target["name"]), "unknown")
    if value not in ACTIVE | FAILED | {"completed", "unknown"}:
        raise PlanError(f"runtime evaluator: unsupported scheduler status {value!r}")
    return value


def _receipt(project, computation, target):
    current = read_runtime_record(current_attempt_path(project, computation["identity"], target["name"]))
    if current is None:
        return None
    if current["identity"] != computation["identity"] or current["target"] != target["name"]:
        raise PlanError("runtime evaluator: current attempt does not match planned target")
    receipt = read_runtime_record(receipt_path(project, computation["identity"], target["name"], current["attempt"]))
    if receipt is None:
        return None
    if receipt["kind"] != "success-receipt" or any(receipt[key] != current[key] for key in ("identity", "target", "attempt")):
        raise PlanError("runtime evaluator: receipt does not belong to the current attempt")
    return receipt


def _mtime(path, virtual):
    source = Path(path)
    if source.exists():
        return source.stat().st_mtime_ns
    return virtual.get(path)


def _boundary_evidence(project, computation):
    try:
        manifest = read_execution_manifest(project, computation["identity"])
    except UnsupportedEvidence:
        return None
    if manifest is None:
        return None
    require_consistent_definition(manifest, computation)
    receipts = {}
    for target in computation["targets"]:
        receipt = _receipt(project, computation, target)
        if receipt is None:
            return None
        outputs = {item["path"]: item["mtime_ns"] for item in receipt["outputs"]}
        if set(outputs) != set(target["outputs"]):
            return None
        receipts[target["name"]] = outputs
    if any(not Path(path).exists() for path in computation["retained_outputs"].values()):
        return None
    return receipts


def evaluate(plan, *, statuses=None):
    """Return per-computation/target runtime decisions without changing state.

    Scheduler observations are explicit so callers cannot mistake missing
    tracking for a successful query. The CLI currently supplies all `unknown`;
    the maintained scheduler adapter supplies observations in a later slice.
    """
    statuses = {} if statuses is None else statuses
    read_tracking(plan["project"])
    result = []
    for computation in plan["computations"]:
        project = plan["project"]
        evidence = _boundary_evidence(project, computation)
        virtual = {}
        if evidence is not None:
            retained = set(computation["retained_outputs"].values())
            virtual = {path: stamp for outputs in evidence.values() for path, stamp in outputs.items() if path not in retained and not Path(path).exists()}
        target_by_name = {target["name"]: target for target in computation["targets"]}
        decisions = {}

        def decide(target):
            if target["name"] in decisions:
                return decisions[target["name"]]
            status = _status(statuses, computation, target)
            if status in ACTIVE:
                decision = TargetDecision(target["name"], "attach", status)
            else:
                dependencies = [decide(target_by_name[name]) for name in target["dependencies"]]
                if status in FAILED:
                    decision = TargetDecision(target["name"], "execute", status)
                elif any(item.decision == "execute" for item in dependencies):
                    decision = TargetDecision(target["name"], "execute", "required-prerequisite")
                elif target["always_run"]:
                    decision = TargetDecision(target["name"], "execute", "outputless-always-run")
                else:
                    outputs = [_mtime(path, virtual if evidence is not None else {}) for path in target["outputs"]]
                    if any(value is None for value in outputs):
                        decision = TargetDecision(target["name"], "execute", "missing-output-or-evidence")
                    else:
                        inputs = []
                        for path in target["inputs"]:
                            stamp = _mtime(path, virtual if evidence is not None else {})
                            if stamp is None:
                                if path in {output for item in computation["targets"] for output in item["outputs"]}:
                                    decision = TargetDecision(target["name"], "execute", "required-prerequisite")
                                    break
                                raise PlanError(f"runtime evaluator: missing producerless external input {path}")
                            inputs.append(stamp)
                        else:
                            if inputs and max(inputs) > min(outputs):
                                decision = TargetDecision(target["name"], "execute", "newer-input")
                            elif evidence is None:
                                decision = TargetDecision(target["name"], "execute", "missing-required-evidence")
                            else:
                                decision = TargetDecision(target["name"], "reuse", "current-evidence")
            decisions[target["name"]] = decision
            return decision

        for target in computation["targets"]:
            decide(target)
        values = list(decisions.values())
        if any(value.decision == "attach" for value in values):
            computation_decision, reason = "attach", "active-target"
        elif any(value.decision == "execute" for value in values):
            computation_decision, reason = "execute", next(value.reason for value in values if value.decision == "execute")
        else:
            computation_decision, reason = "reuse", "complete-current-boundary"
        result.append({"identity": computation["identity"], "decision": computation_decision, "reason": reason, "targets": [value.__dict__ for value in values]})
    return result
