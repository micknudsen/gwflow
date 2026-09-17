"""Explicit, audited reconciliation of one uncertain submission.

The operator establishes command termination and exhaustive scheduler coverage.
Machine observations verify positive job ownership and quiescence; absence alone
cannot establish that a request was never accepted.
"""
import os
from pathlib import Path
import re
import uuid

from .coordination import acquire_guard, guard_path, marker_path, release_guard
from .host_execution import scheduler_name
from .planner import PlanError
from .record_io import durable_rmdir, durable_unlink, publish_json, read_json
from .recovery_scheduler import inspect_ownership, TERMINAL
from .runtime_errors import RuntimeFailure
from .runtime_records import (
    association_key, current_attempt, current_attempt_path, job_association,
    read_runtime_record, read_tracking, receipt_path, tracking_path,
    validate_tracking, write_runtime_record, write_tracking,
)


def _blocked(message, code="recovery-incomplete"):
    raise RuntimeFailure(code, message)


def _context(project):
    marker = read_json(marker_path(project))
    if (type(marker) is not dict or set(marker) != {"kind", "record_revision", "submission", "intent"}
            or marker["kind"] != "submission-marker" or type(marker["record_revision"]) is not int
            or marker["record_revision"] != 1 or type(marker["submission"]) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", marker["submission"])):
        _blocked("restore the valid original submission marker before recovery")
    submission = marker["submission"]
    intent_path = tracking_path(project).parent / "submissions" / submission / "intent.json"
    if marker["intent"] != str(intent_path):
        _blocked("submission marker does not name its maintained intent path")
    intent = read_runtime_record(intent_path)
    if intent is None or intent["kind"] != "submission-intent" or intent["submission"] != submission:
        _blocked("restore the complete original submission intent before recovery")
    keys, names = set(), set()
    for item in intent["targets"]:
        key = association_key(item["identity"], item["target"])
        if (key in keys or item["ownership"] in names
                or item["ownership"] != scheduler_name(item["identity"], item["target"], item["attempt"])):
            _blocked("intent contains ambiguous or inconsistent attempt ownership")
        keys.add(key)
        names.add(item["ownership"])
    # Read the independent map without demanding that interrupted selections
    # already agree with it. Its schema and unaffected history still must agree.
    tracking = read_json(tracking_path(project))
    validate_tracking(tracking)
    return marker, intent, tracking


def _resolutions(document, intent, observations):
    fields = {"submission", "command_stopped", "ownership_complete", "evidence", "targets"}
    if (type(document) is not dict or set(document) != fields
            or document["submission"] != intent["submission"]
            or document["command_stopped"] is not True or document["ownership_complete"] is not True
            or type(document["evidence"]) is not str or not document["evidence"].strip()
            or type(document["targets"]) is not list):
        _blocked("certify the stopped submitter, exhaustive ownership inspection, and audit evidence for this submission")
    resolved = {}
    expected = {item["ownership"] for item in intent["targets"]}
    for entry in document["targets"]:
        if (type(entry) is not dict or type(entry.get("ownership")) is not str
                or entry["ownership"] not in expected or entry["ownership"] in resolved):
            _blocked("resolution must cover each intended ownership exactly once")
        name = entry["ownership"]
        observed = [row for row in observations if row["ownership"] == name]
        if any(row["state"] not in TERMINAL for row in observed):
            _blocked(f"affected ownership {name} is active or has unknown activity", "recovery-not-quiescent")
        if set(entry) == {"ownership", "job_id"}:
            job_id = entry["job_id"]
            if (type(job_id) is not str or not observed
                    or {row["job_id"] for row in observed} != {job_id}):
                _blocked(f"cannot verify the unique job association for {name}")
        elif set(entry) == {"ownership", "not_accepted"}:
            proof = entry["not_accepted"]
            if (observed or type(proof) is not dict or set(proof) != {"source", "reference"}
                    or proof["source"] not in {"scheduler-admin-audit", "submission-client-audit"}
                    or type(proof["reference"]) is not str or not proof["reference"].strip()):
                _blocked(f"{name} needs affirmative nonacceptance evidence; an empty query or outputs are insufficient")
        else:
            _blocked("each resolution needs a verified job ID or affirmative nonacceptance audit")
        resolved[name] = entry
    if set(resolved) != expected:
        _blocked("resolution must cover the complete affected submission")
    return resolved


def recover(project, *, since, resolution=None):
    project = Path(os.path.abspath(project))
    report = {"kind": "manual-recovery", "recovery_revision": 1, "project": str(project)}
    lock = project / ".gwflow" / "recovery-guard"
    locked = False
    retiring_marker = False
    try:
        if resolution is not None:
            # A separate exclusive directory serializes operators without
            # deleting or stealing the interrupted command's guard.
            try:
                lock.mkdir()
            except FileExistsError:
                _blocked("another recovery owns the recovery guard", "recovery-guard-held")
            locked = True
        marker, intent, tracking = _context(project)
        observations = inspect_ownership([item["ownership"] for item in intent["targets"]], since)
        report.update(submission=intent["submission"], intent=intent, observations=observations)
        if resolution is None:
            report.update(outcome="inspected", resolution={
                "submission": intent["submission"], "command_stopped": False,
                "ownership_complete": False, "evidence": "",
                "targets": [{"ownership": item["ownership"], "job_id": None} for item in intent["targets"]],
            })
            return report
        document = read_json(resolution)
        resolved = _resolutions(document, intent, observations)
        # A live submitter cannot safely be fenced by Phase 2: the explicit
        # command_stopped attestation is necessary even if no jobs are visible.
        submission = intent["submission"]
        expected_owner = {"kind": "command-guard-owner", "record_revision": 1, "owner": submission}
        if os.path.lexists(guard_path(project)):
            if read_json(guard_path(project) / "owner.json") != expected_owner:
                _blocked("command guard belongs to a different or unknown owner")
        else:
            acquire_guard(project, submission)
        if _context(project) != (marker, intent, tracking):
            _blocked("submission records changed during recovery inspection")
        for item in intent["targets"]:
            try:
                selected = read_runtime_record(current_attempt_path(project, item["identity"], item["target"]))
            except PlanError:
                selected = None
            prior = tracking["associations"].get(association_key(item["identity"], item["target"]))
            known = {item["attempt"]} | ({prior["attempt"]} if prior else set())
            if selected is not None and selected.get("attempt") not in known:
                _blocked("a current selection has ownership outside the affected intent and retained tracking")
            try:
                saved_job = read_runtime_record(receipt_path(project, item["identity"], item["target"], item["attempt"]).parent / "job.json")
            except PlanError:
                saved_job = None
            for saved in (prior, saved_job):
                if (saved is not None and saved["kind"] == "job-association"
                        and all(saved[key] == item[key] for key in ("identity", "target", "attempt"))
                        and resolved[item["ownership"]].get("job_id") != saved["job_id"]):
                    _blocked("resolution contradicts a retained accepted job association")
        audit = uuid.uuid4().hex
        audit_path = tracking_path(project).parent / "submissions" / submission / "recoveries" / f"{audit}.json"
        publish_json(audit_path, {"kind": "manual-recovery-audit", "record_revision": 1,
                                "resolution": document, "since": since, "observations": observations,
                                "previous_tracking": tracking})
        restored, invalidated = [], []
        for item in intent["targets"]:
            identity, target, attempt = (item[key] for key in ("identity", "target", "attempt"))
            entry = resolved[item["ownership"]]
            key = association_key(identity, target)
            selected = current_attempt_path(project, identity, target)
            if "job_id" in entry:
                association = job_association(identity, target, attempt, entry["job_id"])
                write_runtime_record(receipt_path(project, identity, target, attempt).parent / "job.json", association)
                # Only preserve a selection already naming the verified attempt.
                # Missing/malformed evidence is never synthesized from outputs.
                try:
                    valid = read_runtime_record(selected) == current_attempt(identity, target, attempt)
                except PlanError:
                    valid = False
                valid = valid and all(row["state"] == "COMPLETED" for row in observations
                                      if row["ownership"] == item["ownership"])
                if not valid and os.path.lexists(selected):
                    durable_unlink(selected)
                    invalidated.append(key)
                restored.append(entry["job_id"])
            else:
                association = {"kind": "unsubmitted-attempt", "record_revision": 1,
                               "identity": identity, "target": target, "attempt": attempt, "recovery": audit}
                if os.path.lexists(selected):
                    durable_unlink(selected)
                invalidated.append(key)
            tracking["associations"][key] = association
        write_tracking(project, tracking)
        read_tracking(project)  # Verify full retained coverage, including unrelated history.
        release_guard(guard_path(project), submission)
        retiring_marker = True
        durable_unlink(marker_path(project))
        report.update(outcome="recovered", audit=str(audit_path), restored_job_ids=restored,
                      invalidated_targets=invalidated)
    except (OSError, ValueError, PlanError, RuntimeFailure) as exc:
        code = exc.code if isinstance(exc, RuntimeFailure) else "recovery-record-error"
        report.update(outcome="blocked", reason={"code": code, "message": str(exc)}, diagnostic=str(exc))
    finally:
        # A failed marker retirement can have removed its visible path before
        # directory synchronization failed. Keep the recovery guard in that
        # final commit window; the operator must inspect the durable audit.
        if locked and (not retiring_marker or report.get("outcome") == "recovered"
                       or os.path.lexists(marker_path(project))):
            try:
                durable_rmdir(lock)
            except OSError as exc:
                report.update(outcome="blocked", reason={"code": "recovery-guard-release-failed", "message": str(exc)}, diagnostic=str(exc))
    return report
