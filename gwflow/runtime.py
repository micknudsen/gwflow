"""Read-only runtime preview contracts.

Submission, scheduler observation, and persisted execution authority are added
by later Phase 2 slices.  This module deliberately consumes a completed pure
plan and performs no filesystem mutation.
"""
from collections.abc import Mapping

from .planner import PlanError


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
    computations = []
    for computation in plan["computations"]:
        targets = [
            {
                "name": target["name"],
                "decision": "execute",
                "reason": {"code": "no-runtime-state", "message": "no retained runtime state has been evaluated"},
                "evidence": [],
                "job_ids": [],
            }
            for target in computation["targets"]
        ]
        computations.append(
            {
                "identity": computation["identity"],
                "decision": "execute",
                "reason": {"code": "no-runtime-state", "message": "no retained runtime state has been evaluated"},
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
