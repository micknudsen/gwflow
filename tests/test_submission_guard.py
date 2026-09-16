"""Submission coordination through the maintained command seam."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from test_planner import runtime_cli
from gwflow.__main__ import main
from gwflow.runtime_records import current_attempt_path, read_runtime_record, read_tracking, tracking_path
from examples.runtime_evaluation import prepare_fixture, stamp


class RecordingScheduler:
    """Test-only external scheduler substitute; it never executes a payload."""

    def __init__(self, project=None):
        self.jobs = []
        self.project = project

    def observe(self, job_ids):
        return {job_id: "running" for job_id in job_ids}

    def submit(self, job):
        if self.project is not None:
            marker = json.loads((self.project / ".gwflow" / "submission.json").read_text())
            intent = read_runtime_record(marker["intent"])
            assert sorted(item["target"] for item in intent["targets"]) == ["a", "b", "c", "d", "e"]
            for item in intent["targets"]:
                selected = read_runtime_record(current_attempt_path(self.project, item["identity"], item["target"]))
                assert selected["attempt"] == item["attempt"]
        self.jobs.append(job)
        return str(100 + len(self.jobs))


def command(project, scheduler, capsys):
    code = main(["run", "examples.runtime_evaluation:main", "--project", str(project),
                 "--bindings", '{"source":"reads.txt","other":"other.txt"}'], scheduler=scheduler)
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


@pytest.mark.parametrize("retained", ["command-guard", "submission.json"])
def test_held_guard_or_uncertainty_marker_blocks_preview_without_decisions(tmp_path, retained):
    (tmp_path / "reads.txt").write_text("input")
    metadata = tmp_path / ".gwflow"
    metadata.mkdir()
    if retained == "command-guard":
        (metadata / retained).mkdir()
    else:
        (metadata / retained).write_text("even an unreadable marker cannot be ignored")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["outcome"] == "blocked"
    assert report["computations"] == []
    assert report["reason"]["code"] == ("command-guard-held" if retained == "command-guard" else "submission-uncertain")
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_success_persists_complete_intent_and_tracking_then_releases_guard_while_jobs_are_active(tmp_path, capsys):
    (tmp_path / "reads.txt").write_text("input")
    (tmp_path / "other.txt").write_text("other input")
    scheduler = RecordingScheduler(tmp_path)
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 0, diagnostic
    assert report["outcome"] == "submitted"
    assert report["accepted_job_ids"] == ["101", "102", "103", "104", "105"]
    assert len(scheduler.jobs) == 5
    assert not (tmp_path / ".gwflow" / "command-guard").exists()
    assert not (tmp_path / ".gwflow" / "submission.json").exists()
    intent = read_runtime_record(report["intent"])
    assert sorted(item["target"] for item in intent["targets"]) == ["a", "b", "c", "d", "e"]
    associations = list(read_tracking(tmp_path)["associations"].values())
    assert sorted(item["job_id"] for item in associations) == ["101", "102", "103", "104", "105"]
    for item in associations:
        selected = read_runtime_record(current_attempt_path(tmp_path, item["identity"], item["target"]))
        assert selected["attempt"] == item["attempt"]
    # A subsequent command observes active jobs after the first guard released.
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 0, diagnostic
    assert report["accepted_job_ids"] == []
    assert len(scheduler.jobs) == 5
    assert report["computations"][0]["decision"] == "attach"


def test_submission_blocks_corrupt_tracking_without_attempts_or_acceptance(tmp_path, capsys):
    (tmp_path / "reads.txt").write_text("input")
    (tmp_path / "other.txt").write_text("other")
    path = tracking_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("corrupt authority")
    scheduler = RecordingScheduler()
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 1, diagnostic
    assert report["outcome"] == "blocked"
    assert report["reason"]["code"] == "untrustworthy-job-tracking"
    assert report["computations"] == []
    assert scheduler.jobs == []
    assert not (tmp_path / ".gwflow" / "command-guard").exists()
    assert not (path.parent / "computations").exists()


@pytest.mark.parametrize("window", ["before-acceptance", "accepted-without-id", "partial-graph"])
def test_acceptance_failure_preserves_complete_intent_and_blocks_later_commands(tmp_path, capsys, window):
    (tmp_path / "reads.txt").write_text("input")
    (tmp_path / "other.txt").write_text("other")

    class Interrupted(RecordingScheduler):
        def submit(self, job):
            if window == "before-acceptance":
                raise OSError("scheduler request failed before acceptance")
            accepted = super().submit(job)
            if window == "accepted-without-id" or len(self.jobs) == 2:
                raise TimeoutError("connection lost after scheduler acceptance")
            return accepted

    scheduler = Interrupted(tmp_path)
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 1
    assert report["outcome"] == "error"
    assert report["accepted_job_ids"] == (["101"] if window == "partial-graph" else [])
    assert len(read_runtime_record(report["intent"])["targets"]) == 5
    assert (tmp_path / ".gwflow" / "command-guard").is_dir()
    assert (tmp_path / ".gwflow" / "submission.json").is_file()
    repeated = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert repeated.returncode == 1
    assert json.loads(repeated.stdout)["reason"]["code"] == "submission-uncertain"
    assert json.loads(repeated.stdout)["computations"] == []


def test_returned_accepted_id_is_reported_when_its_durable_publication_fails(tmp_path, capsys, monkeypatch):
    (tmp_path / "reads.txt").write_text("input")
    (tmp_path / "other.txt").write_text("other")
    scheduler = RecordingScheduler(tmp_path)
    replace = os.replace

    def fail_association(source, destination):
        if Path(destination).name == "job.json":
            raise OSError("injected association persistence failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_association)
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 1
    assert report["accepted_job_ids"] == ["101"]
    assert len(scheduler.jobs) == 1
    assert (tmp_path / ".gwflow" / "submission.json").exists()
    assert json.loads(tracking_path(tmp_path).read_text())["associations"] == {}


def test_failed_durable_intent_prevents_any_scheduler_acceptance(tmp_path, capsys, monkeypatch):
    (tmp_path / "reads.txt").write_text("input")
    (tmp_path / "other.txt").write_text("other")
    scheduler = RecordingScheduler()
    replace = os.replace

    def fail_intent(source, destination):
        if Path(destination).name == "intent.json":
            raise OSError("injected intent persistence failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_intent)
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 1
    assert report["accepted_job_ids"] == []
    assert scheduler.jobs == []
    assert (tmp_path / ".gwflow" / "submission.json").exists()


def test_interruption_demo_uses_real_process_crashes_and_the_product_preview(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.submission_guard_demo", "--project", str(tmp_path / "demo")], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["scheduler_jobs_submitted"] == 0
    assert [(c["case"], c["fixture_accepted"], c["durably_tracked"], c["intended"], c["preview_exit"]) for c in report["cases"]] == [
        ("before-acceptance", 0, 0, 5, 1), ("accepted-before-id", 1, 0, 5, 1), ("partial-graph", 2, 1, 5, 1),
    ]


def test_overlapping_commands_cannot_both_enter_scheduler_acceptance(tmp_path):
    (tmp_path / "reads.txt").write_text("source")
    (tmp_path / "other.txt").write_text("other")
    first = subprocess.Popen([sys.executable, "-m", "examples.submission_guard_demo", "--project", str(tmp_path), "--worker", "hold"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "fixture-submit-entered").exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "fixture-submit-entered").exists()
        second = runtime_cli(tmp_path, "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
        assert second.returncode == 1
        assert json.loads(second.stdout)["outcome"] == "blocked"
        assert json.loads(second.stdout)["accepted_job_ids"] == []
        assert first.poll() is None
    finally:
        (tmp_path / "fixture-release").write_text("release test-only scheduler")
        stdout, stderr = first.communicate(timeout=25)
    assert first.returncode == 0, stdout + stderr
    assert len(json.loads((tmp_path / "fixture-scheduler.json").read_text())) == 5
    assert not (tmp_path / ".gwflow" / "command-guard").exists()


def test_submission_reevaluates_under_guard_and_preserves_pruned_associations(tmp_path, capsys):
    prepare_fixture(tmp_path)
    before = read_tracking(tmp_path)
    observed = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert json.loads(observed.stdout)["computations"][0]["decision"] == "reuse"

    class ChangedSincePreview(RecordingScheduler):
        def observe(self, job_ids):
            assert (tmp_path / ".gwflow" / "command-guard").is_dir()
            stamp(tmp_path / "reads.txt", 25)
            return {job_id: "unknown" for job_id in job_ids}

        def submit(self, job):
            self.jobs.append(job)
            return str(1000 + len(self.jobs))

    scheduler = ChangedSincePreview()
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 0, diagnostic
    assert sorted(job["target"] for job in scheduler.jobs) == ["a", "b", "e"]
    after = read_tracking(tmp_path)
    for key, association in before["associations"].items():
        if association["target"] in {"c", "d"}:
            assert after["associations"][key] == association


def test_query_failure_releases_guard_without_starting_a_submission(tmp_path, capsys):
    prepare_fixture(tmp_path)
    before = tracking_path(tmp_path).read_bytes()

    class BrokenQuery(RecordingScheduler):
        def observe(self, job_ids):
            raise OSError("scheduler query unavailable")

    scheduler = BrokenQuery()
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 1
    assert report["accepted_job_ids"] == []
    assert scheduler.jobs == []
    assert tracking_path(tmp_path).read_bytes() == before
    assert not (tmp_path / ".gwflow" / "command-guard").exists()
    assert not (tmp_path / ".gwflow" / "submission.json").exists()


def test_tracking_sync_failure_after_acceptance_cannot_release_guard(tmp_path, capsys, monkeypatch):
    (tmp_path / "reads.txt").write_text("input")
    (tmp_path / "other.txt").write_text("other")
    scheduler = RecordingScheduler(tmp_path)
    replace, fsync = os.replace, os.fsync
    failed_commit = False

    def replace_tracking(source, destination):
        nonlocal failed_commit
        replace(source, destination)
        if Path(destination) == tracking_path(tmp_path) and len(scheduler.jobs) == 5:
            failed_commit = True

    def fail_sync(fd):
        if failed_commit:
            raise OSError("injected tracking directory sync failure")
        fsync(fd)

    monkeypatch.setattr(os, "replace", replace_tracking)
    monkeypatch.setattr(os, "fsync", fail_sync)
    code, report, diagnostic = command(tmp_path, scheduler, capsys)
    assert code == 1
    assert report["accepted_job_ids"] == ["101", "102", "103", "104", "105"]
    assert "tracking directory sync failure" in diagnostic
    assert (tmp_path / ".gwflow" / "command-guard").is_dir()
    assert (tmp_path / ".gwflow" / "submission.json").is_file()
