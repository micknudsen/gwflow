"""Guarded intent/acceptance protocol; the scheduler is supplied at one seam."""
from pathlib import Path
import os
import uuid

from .coordination import acquire_guard, blocking_reason, marker_path, release_guard
from .host_execution import prepare_attempt, scheduler_name
from .planner import PlanError
from .executable_graph import dependency_graph
from .slurm_adapter import GwfSlurmAdapter, observe_tracking
from .record_io import durable_unlink, publish_json
from .runtime import evaluated_preview, host_only
from .runtime_errors import RuntimeFailure
from .runtime_records import (
    association_key, execution_manifest, job_association, job_tracking,
    read_tracking, submission_intent, tracking_path, write_execution_manifest,
    write_runtime_record, write_tracking,
    UnsupportedTracking,
)


def _problem(plan, code, message, *, blocked=False, accepted=(), intent=None):
    return {"kind": "runtime-submission", "submission_revision": 1,
            "project": plan["project"], "outcome": "blocked" if blocked else "error",
            "reason": {"code": code, "message": message}, "diagnostic": message,
            "computations": [], "accepted_job_ids": list(accepted), "intent": str(intent) if intent else None}


def submit(plan, *, scheduler=None):
    """Publish intent before acceptance; keep uncertainty on interrupted work.

    The scheduler satisfies observe(job_ids) and submit(job). Tests substitute
    the external scheduler; normal commands use the maintained gwf/Slurm adapter.
    """
    host_only(plan)
    blocked = blocking_reason(plan["project"])
    if blocked:
        return _problem(plan, *blocked, blocked=True)
    if scheduler is None:
        scheduler = GwfSlurmAdapter(plan["project"])
    project = plan["project"]
    submission = uuid.uuid4().hex
    guard = None
    marker_started = False
    accepted = []
    intent_path = None
    try:
        guard = acquire_guard(project, submission)
        # An interrupted command's marker is authoritative even if somebody
        # manually removed its guard. Acquiring a guard cannot clear it.
        if os.path.lexists(marker_path(project)):
            release_guard(guard, submission)
            guard = None
            return _problem(plan, "submission-uncertain", "retained submission marker requires manual recovery", blocked=True)
        tracking = read_tracking(project)
        tracking = job_tracking() if tracking is None else tracking
        statuses, jobs = observe_tracking(tracking, scheduler)
        report = evaluated_preview(plan, statuses=statuses, job_ids=jobs)
        if report["outcome"] != "ready":
            release_guard(guard, submission)
            guard = None
            return _problem(plan, report["reason"]["code"], report["diagnostic"], blocked=report["outcome"] == "blocked")
        decisions = {(comp["identity"], target["name"]): target["decision"]
                     for comp in report["computations"] for target in comp["targets"]}
        targets, dependencies, order = dependency_graph(plan)
        intended = []
        selected = []
        for identity, name in order:
            if decisions[(identity, name)] != "execute":
                continue
            attempt = f"{submission}-{len(intended)}"
            ownership = scheduler_name(identity, name, attempt)
            intended.append({"identity": identity, "target": name, "attempt": attempt, "ownership": ownership})
            selected.append(targets[(identity, name)])
        intent_path = tracking_path(project).parent / "submissions" / submission / "intent.json"
        # Set the conservative failure policy before the first marker write:
        # an interrupted write may have published a visible but unsynced marker.
        marker_started = True
        publish_json(marker_path(project), {"kind": "submission-marker", "record_revision": 1,
                                            "submission": submission, "intent": str(intent_path)})
        write_runtime_record(intent_path, submission_intent(submission, intended))
        write_tracking(project, tracking)
        for computation in plan["computations"]:
            write_execution_manifest(project, execution_manifest(plan, computation["identity"]))
        prepared = []
        for item, (computation, target) in zip(intended, selected):
            invocation = prepare_attempt(project, computation, target, item["attempt"])
            prepared.append({**item, "invocation": str(invocation),
                             "computation": computation, "definition": target})
        for job in prepared:
            job["dependencies"] = sorted({jobs[parent] for parent in dependencies[(job["identity"], job["target"])] if decisions[parent] != "reuse"})
            job_id = scheduler.submit(job)
            association = job_association(job["identity"], job["target"], job["attempt"], job_id)
            accepted.append(job_id)
            jobs[(job["identity"], job["target"])] = job_id
            tracking["associations"][association_key(job["identity"], job["target"])] = association
            # Retain both per-attempt history and the independent latest-job map.
            write_runtime_record(Path(job["invocation"]).parent / "job.json", association)
            write_tracking(project, tracking)
        write_tracking(project, tracking)  # Also commits all-reused/attached requests.
        durable_unlink(marker_path(project))
        release_guard(guard, submission)
        guard = None
        for computation in report["computations"]:
            for target in computation["targets"]:
                key = (computation["identity"], target["name"])
                target["job_ids"] = [jobs[key]] if key in jobs else []
            computation["job_ids"] = sorted({job_id for target in computation["targets"] for job_id in target["job_ids"]})
        return {"kind": "runtime-submission", "submission_revision": 1,
                "project": project, "outcome": "submitted", "submission": submission,
                "intent": str(intent_path), "accepted_job_ids": accepted,
                "computations": report["computations"]}
    except Exception as exc:
        if guard is not None and not marker_started:
            try:
                release_guard(guard, submission)
            except (OSError, ValueError, RuntimeFailure) as cleanup:
                return _problem(plan, "guard-release-failed", f"{exc}; guard release failed: {cleanup}")
        if isinstance(exc, UnsupportedTracking):
            return _problem(plan, "untrustworthy-job-tracking", str(exc), blocked=True)
        if isinstance(exc, PlanError) and not marker_started:
            raise
        code = exc.code if isinstance(exc, RuntimeFailure) else "submission-failed"
        return _problem(plan, code, str(exc), blocked=code == "command-guard-held", accepted=accepted, intent=intent_path)
