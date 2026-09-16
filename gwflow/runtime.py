"""Read-only runtime preview contracts.

Submission, scheduler observation, and persisted execution authority are added
by later Phase 2 slices.  This module deliberately consumes a completed pure
plan and performs no filesystem mutation.
"""
from collections.abc import Mapping

from .planner import PlanError
from .runtime_records import UnsupportedTracking
from .evaluator import evaluate
from .runtime_errors import RuntimeFailure
from .coordination import blocking_reason


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


def preview(plan: Mapping, *, statuses=None, job_ids=None) -> dict:
    """Describe the initial runtime decision without reserving or changing state."""
    host_only(plan)
    blocked = blocking_reason(plan["project"])
    if blocked:
        code, message = blocked
        return {"kind": "runtime-preview", "runtime_preview_revision": RUNTIME_PREVIEW_REVISION, "project": plan["project"], "outcome": "blocked", "reason": {"code": code, "message": message}, "diagnostic": message, "computations": []}
    return evaluated_preview(plan, statuses=statuses, job_ids=job_ids)


def evaluated_preview(plan: Mapping, *, statuses=None, job_ids=None) -> dict:
    """Shared evaluator report; caller must check coordination or hold the guard."""
    try:
        evaluated = {item["identity"]: item for item in evaluate(plan, statuses=statuses, job_ids=job_ids)}
    except UnsupportedTracking as exc:
        return {"kind": "runtime-preview", "runtime_preview_revision": RUNTIME_PREVIEW_REVISION, "project": plan["project"], "outcome": "blocked", "reason": {"code": "untrustworthy-job-tracking", "message": str(exc)}, "diagnostic": str(exc), "computations": []}
    except RuntimeFailure as exc:
        return {"kind": "runtime-preview", "runtime_preview_revision": RUNTIME_PREVIEW_REVISION, "project": plan["project"], "outcome": "error", "reason": {"code": exc.code, "message": str(exc)}, "diagnostic": str(exc), "computations": []}
    except OSError as exc:
        return {"kind": "runtime-preview", "runtime_preview_revision": RUNTIME_PREVIEW_REVISION, "project": plan["project"], "outcome": "error", "reason": {"code": "filesystem-error", "message": str(exc)}, "diagnostic": str(exc), "computations": []}
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
