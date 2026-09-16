"""Read-only evaluation of retained runtime state and target freshness."""
from dataclasses import dataclass
from pathlib import Path

from .planner import PlanError
from .graph import acyclic
from .runtime_errors import RuntimeFailure
from .runtime_records import UnsupportedEvidence, current_attempt_path, execution_manifest_path, read_execution_manifest, read_runtime_record, read_tracking, receipt_path, require_consistent_definition


ACTIVE = {"submitted", "running"}
FAILED = {"failed", "cancelled"}


@dataclass(frozen=True)
class TargetDecision:
    name: str
    decision: str
    reason: str
    evidence: tuple[dict, ...] = ()
    job_ids: tuple[str, ...] = ()


def _status(statuses, computation, target):
    value = statuses.get((computation["identity"], target["name"]), "unknown")
    if type(value) is not str or value not in ACTIVE | FAILED | {"completed", "unknown"}:
        raise RuntimeFailure("invalid-scheduler-observation", f"runtime evaluator: unsupported scheduler status {value!r}")
    return value


def _receipt(project, computation, target):
    current = read_runtime_record(current_attempt_path(project, computation["identity"], target["name"]))
    if current is None:
        return None
    if current["kind"] != "current-attempt" or current["identity"] != computation["identity"] or current["target"] != target["name"]:
        raise PlanError("runtime evaluator: current attempt does not match planned target")
    receipt = read_runtime_record(receipt_path(project, computation["identity"], target["name"], current["attempt"]))
    if receipt is None:
        return None
    if receipt["kind"] != "success-receipt" or any(receipt[key] != current[key] for key in ("identity", "target", "attempt")):
        raise PlanError("runtime evaluator: receipt does not belong to the current attempt")
    return receipt


def _mtime(path, virtual, *, output=False):
    source = Path(path)
    if source.exists():
        if output and not source.is_file():
            return None
        return source.stat().st_mtime_ns
    return virtual.get(path)


def _target_evidence(project, computation):
    try:
        manifest = read_execution_manifest(project, computation["identity"])
    except UnsupportedEvidence:
        return None
    if manifest is None:
        return None
    require_consistent_definition(manifest, computation)
    receipts = {}
    for target in computation["targets"]:
        try:
            receipt = _receipt(project, computation, target)
        except PlanError:
            receipt = None
        if receipt is None:
            receipts[target["name"]] = None
            continue
        outputs = {item["path"]: item["mtime_ns"] for item in receipt["outputs"]}
        if set(outputs) != set(target["outputs"]):
            receipts[target["name"]] = None
        else:
            receipts[target["name"]] = {"outputs": outputs, "attempt": receipt["attempt"]}
    return receipts


def evaluate(plan, *, statuses=None, job_ids=None):
    """Return per-computation/target runtime decisions without changing state.

    Scheduler observations are explicit so callers cannot mistake missing
    tracking for a successful query. The CLI currently supplies all `unknown`;
    the maintained scheduler adapter supplies observations in a later slice.
    """
    statuses = {} if statuses is None else statuses
    job_ids = {} if job_ids is None else job_ids
    read_tracking(plan["project"])
    produced = {path for computation in plan["computations"] for target in computation["targets"] for path in target["outputs"]}
    for computation in plan["computations"]:
        for target in computation["targets"]:
            for path in target["inputs"]:
                if path not in produced and not Path(path).exists():
                    raise RuntimeFailure("missing-external-input", f"runtime evaluator: missing producerless external input {path}")
    result = {}
    computations = {computation["identity"]: computation for computation in plan["computations"]}
    order = acyclic({identity: computation["whole_producer_dependencies"] for identity, computation in computations.items()}, "runtime composition")
    for identity in order:
        computation = computations[identity]
        project = plan["project"]
        evidence = _target_evidence(project, computation)
        virtual = {}
        if evidence is not None and all(value is not None for value in evidence.values()) and all(Path(path).is_file() for path in computation["retained_outputs"].values()):
            retained = set(computation["retained_outputs"].values())
            virtual = {path: stamp for record in evidence.values() for path, stamp in record["outputs"].items() if path not in retained and not Path(path).exists()}
        target_by_name = {target["name"]: target for target in computation["targets"]}
        decisions = {}
        upstream_pending = any(result[producer]["decision"] != "reuse" for producer in computation["whole_producer_dependencies"])

        def decide(target):
            if target["name"] in decisions:
                return decisions[target["name"]]
            status = _status(statuses, computation, target)
            target_evidence = evidence.get(target["name"]) if evidence is not None else None
            ids = (str(job_ids[(computation["identity"], target["name"])]),) if (computation["identity"], target["name"]) in job_ids else ()

            def decision_for(decision, reason):
                references = []
                if evidence is not None:
                    references.append({"kind": "execution-manifest", "path": str(execution_manifest_path(project, computation["identity"]))})
                if target_evidence is not None:
                    attempt = target_evidence["attempt"]
                    references.extend([
                        {"kind": "current-attempt", "path": str(current_attempt_path(project, computation["identity"], target["name"])), "attempt": attempt},
                        {"kind": "success-receipt", "path": str(receipt_path(project, computation["identity"], target["name"], attempt)), "attempt": attempt},
                    ])
                for role in ("inputs", "outputs"):
                    for path in target[role]:
                        stamp = _mtime(path, virtual, output=role == "outputs")
                        kind = "historical-output" if path in virtual else "input-file" if role == "inputs" else "output-file"
                        references.append({"kind": kind, "path": path, "mtime_ns": stamp})
                if status != "unknown" or ids:
                    references.append({"kind": "scheduler", "status": status, "job_ids": list(ids)})
                return TargetDecision(target["name"], decision, reason, tuple(references), ids)

            if status in ACTIVE:
                decision = decision_for("attach", status)
            else:
                dependencies = [decide(target_by_name[name]) for name in target["dependencies"]]
                if status in FAILED:
                    decision = decision_for("execute", status)
                elif any(item.decision != "reuse" for item in dependencies):
                    decision = decision_for("execute", "required-prerequisite")
                elif upstream_pending and target["name"] in computation["entry_targets"]:
                    decision = decision_for("execute", "whole-producer-pending")
                elif target["always_run"]:
                    decision = decision_for("execute", "outputless-always-run")
                elif evidence is None:
                    decision = decision_for("execute", "no-runtime-state")
                else:
                    outputs = [_mtime(path, virtual, output=True) for path in target["outputs"]]
                    if any(value is None for value in outputs):
                        decision = decision_for("execute", "missing-output-or-evidence")
                    else:
                        inputs = []
                        for path in target["inputs"]:
                            stamp = _mtime(path, virtual if evidence is not None else {})
                            if stamp is None:
                                if path in produced:
                                    decision = decision_for("execute", "required-prerequisite")
                                    break
                                raise RuntimeFailure("missing-external-input", f"runtime evaluator: missing producerless external input {path}")
                            inputs.append(stamp)
                        else:
                            if inputs and max(inputs) > min(outputs):
                                decision = decision_for("execute", "newer-input")
                            elif evidence is None or evidence[target["name"]] is None:
                                decision = decision_for("execute", "missing-required-evidence")
                            else:
                                decision = decision_for("reuse", "current-evidence")
            decisions[target["name"]] = decision
            return decision

        for target in computation["targets"]:
            decide(target)
        if virtual and any(value.decision != "reuse" for value in decisions.values()):
            # Historical timestamps apply only to a reusable *whole* boundary.
            # Recovery must reconsider every target using physical files.
            virtual = {}
            decisions.clear()
            for target in computation["targets"]:
                decide(target)
        values = list(decisions.values())
        if any(value.decision == "execute" for value in values):
            computation_decision, reason = "execute", next(value.reason for value in values if value.decision == "execute")
        elif any(value.decision == "attach" for value in values):
            computation_decision, reason = "attach", "active-target"
        else:
            computation_decision, reason = "reuse", "complete-current-boundary"
        references = {str(reference): reference for value in values for reference in value.evidence}
        result[identity] = {"identity": identity, "decision": computation_decision, "reason": reason,
                       "evidence": list(references.values()), "job_ids": sorted({job for value in values for job in value.job_ids}),
                       "targets": [value.__dict__ for value in values]}
    return [result[computation["identity"]] for computation in plan["computations"]]
