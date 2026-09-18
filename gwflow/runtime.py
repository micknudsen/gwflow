"""Read-only runtime preview contracts.

This module consumes a completed pure plan and performs no filesystem mutation.
Submission shares its evaluation while holding the project command guard.
"""
from collections.abc import Mapping

from .planner import PlanError
from .runtime_records import UnsupportedTracking, read_tracking
from .slurm_adapter import GwfSlurmAdapter, observe_tracking
from .evaluator import evaluate
from .active_consumers import replacement_block
from .runtime_errors import RuntimeFailure
from .coordination import blocking_reason, observation_generation


RUNTIME_PREVIEW_REVISION = 1


def host_only(plan: Mapping) -> None:
    """Reject every non-host target before a runtime command can submit work."""
    for computation in plan["computations"]:
        for target in computation["targets"]:
            environment = target["environment"]
            if environment["kind"] != "host":
                raise PlanError(
                    "runtime execution is host-only in Phase 2: "
                    f"{computation['definition']['name']}/{target['name']} "
                    f"declares {environment['kind']}"
                )


def _problem(plan, code, message, *, outcome="blocked"):
    return {"kind": "runtime-preview", "runtime_preview_revision": RUNTIME_PREVIEW_REVISION,
            "project": plan["project"], "outcome": outcome,
            "reason": {"code": code, "message": message}, "diagnostic": message,
            "computations": []}


def preview(plan: Mapping, *, statuses=None, job_ids=None, scheduler=None) -> dict:
    """Describe the initial runtime decision without reserving or changing state."""
    host_only(plan)
    try:
        generation = observation_generation(plan["project"])
        blocked = blocking_reason(plan["project"])
        if blocked:
            return _problem(plan, *blocked)
        failure = None
        try:
            report = evaluated_preview(plan, statuses=statuses, job_ids=job_ids, scheduler=scheduler)
        except PlanError as exc:
            failure = exc
        changed = generation != observation_generation(plan["project"])
        blocked = blocking_reason(plan["project"])
        if blocked:
            return _problem(plan, *blocked)
        if changed:
            return _problem(plan, "runtime-observation-changed", "a submission overlapped runtime observations; retry the read-only preview")
        if failure is not None:
            raise failure
        return report
    except OSError as exc:
        return _problem(plan, "filesystem-error", str(exc), outcome="error")


def evaluated_preview(plan: Mapping, *, statuses=None, job_ids=None, scheduler=None) -> dict:
    """Shared evaluator report; caller must check coordination or hold the guard."""
    try:
        if statuses is None:
            tracking = read_tracking(plan["project"])
            statuses, job_ids = observe_tracking(tracking, scheduler if scheduler is not None else GwfSlurmAdapter(plan["project"]))
        evaluated = {item["identity"]: item for item in evaluate(plan, statuses=statuses, job_ids=job_ids)}
        blocked = replacement_block(plan, evaluated, statuses, job_ids or {})
        if blocked:
            return _problem(plan, *blocked)
    except UnsupportedTracking as exc:
        return _problem(plan, "untrustworthy-job-tracking", str(exc))
    except RuntimeFailure as exc:
        return _problem(plan, exc.code, str(exc), outcome="error")
    except OSError as exc:
        return _problem(plan, "filesystem-error", str(exc), outcome="error")
    computations = []
    for computation in plan["computations"]:
        decision = evaluated[computation["identity"]]
        targets = [
            {
                "name": target["name"], "decision": target["decision"],
                "reason": {"code": target["reason"], "message": target["reason"].replace("-", " ")},
                "evidence": list(target["evidence"]),
                "job_ids": list(target["job_ids"]),
            }
            for target in decision["targets"]
        ]
        computations.append(
            {
                "identity": computation["identity"],
                "decision": decision["decision"],
                "reason": {"code": decision["reason"], "message": decision["reason"].replace("-", " ")},
                "evidence": decision["evidence"],
                "job_ids": decision["job_ids"],
                "targets": targets,
            }
        )
    return {
        "kind": "runtime-preview",
        "runtime_preview_revision": RUNTIME_PREVIEW_REVISION,
        "project": plan["project"],
        "outcome": "ready",
        "computations": computations,
    }
