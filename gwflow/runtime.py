"""Read-only runtime preview contracts.

Submission, scheduler observation, and persisted execution authority are added
by later Phase 2 slices.  This module deliberately consumes a completed pure
plan and performs no filesystem mutation.
"""
from collections.abc import Mapping

from .planner import PlanError
from .runtime_records import UnsupportedEvidence, UnsupportedTracking, read_execution_manifest, require_consistent_definition
from .evaluator import evaluate


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


def preview(plan: Mapping) -> dict:
    """Describe the initial runtime decision without reserving or changing state."""
    host_only(plan)
    try:
        evaluated = {item["identity"]: item for item in evaluate(plan)}
    except UnsupportedTracking as exc:
        return {"kind": "runtime-preview", "runtime_preview_revision": RUNTIME_PREVIEW_REVISION, "project": plan["project"], "outcome": "blocked", "diagnostic": str(exc), "computations": []}
    computations = []
    for computation in plan["computations"]:
        decision = evaluated[computation["identity"]]
        try:
            saved = read_execution_manifest(plan["project"], computation["identity"])
        except UnsupportedEvidence:
            saved = True
        no_runtime_state = saved is None
        targets = [
            {
                "name": target["name"], "decision": target["decision"],
                "reason": {"code": "no-runtime-state" if no_runtime_state else target["reason"], "message": "no retained runtime state has been evaluated" if no_runtime_state else target["reason"].replace("-", " ")},
                "evidence": [],
                "job_ids": [],
            }
            for target in decision["targets"]
        ]
        computations.append(
            {
                "identity": computation["identity"],
                "decision": decision["decision"],
                "reason": {"code": "no-runtime-state" if no_runtime_state else decision["reason"], "message": "no retained runtime state has been evaluated" if no_runtime_state else decision["reason"].replace("-", " ")},
                "evidence": [],
                "job_ids": [],
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
