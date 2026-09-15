"""Throwaway local E4 probes: real processes/locks, simulated scheduler.

The fake scheduler is a durable JSON store which accepts duplicate requests.
It exposes owner/attempt tokens perfectly; actual Slurm token visibility,
accounting delays, job-state races, and conditional cancellation are NOT tested.
This fixture is not a production gwflow coordinator or a gwf adapter.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import pytest


CRASH_EXIT = 73
OWNER = "phase0-owned-project"
DEADLINE_SECONDS = 10


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def atomic_json(path, value, crash_before_replace=False):
    """Publish in the destination directory; exercise real replace/fsync calls."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".publishing-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        if crash_before_replace:
            os._exit(CRASH_EXIT)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def advisory_lock(path, contention_path=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        if contention_path:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                Path(contention_path).touch()
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def wait_for(path):
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {path}")
        time.sleep(0.01)


def scheduler_jobs(root):
    return read_json(root / "fake-scheduler.json", [])


def scheduler_accept(root, owner, target, attempt):
    """Simulate durable acceptance; deliberately do not deduplicate tokens."""
    with advisory_lock(root / "fake-scheduler.lock"):
        jobs = scheduler_jobs(root)
        job_id = f"fake-job-{len(jobs) + 1}"
        jobs.append({
            "job_id": job_id,
            "owner": owner,
            "target": target,
            "attempt": attempt,
            "state": "QUEUED",
        })
        atomic_json(root / "fake-scheduler.json", jobs)
        return job_id


def coordinate(config):
    root = Path(config["root"])
    project_path = root / "project.json"
    with advisory_lock(root / "project.lock", config.get("lock_contended")):
        if config.get("lock_ready"):
            Path(config["lock_ready"]).touch()
            wait_for(Path(config["release_lock"]))
        project = read_json(project_path, {"targets": {}})
        for target in config["targets"]:
            entry = project["targets"].get(target)
            if entry is None:
                entry = {"attempt": uuid.uuid4().hex, "job_id": None}
                project["targets"][target] = entry
                atomic_json(project_path, project)
            if entry["job_id"] is not None:
                # This probe's accepted fake jobs stay queued throughout.
                continue
            matching = [
                job for job in scheduler_jobs(root)
                if job["owner"] == OWNER
                and job["target"] == target
                and job["attempt"] == entry["attempt"]
            ]
            if len(matching) > 1:
                raise RuntimeError("Ambiguous fake scheduler ownership")
            if matching:
                job_id = matching[0]["job_id"]
            else:
                if config.get("crash_before") == target:
                    os._exit(CRASH_EXIT)
                job_id = scheduler_accept(root, OWNER, target, entry["attempt"])
                if config.get("crash_after") == target:
                    os._exit(CRASH_EXIT)
            entry["job_id"] = job_id
            atomic_json(project_path, project)
    return project


def atomic_payload(generation):
    return {"generation": generation, "payload": str(generation) * 8192}


def run_worker(config):
    mode = config.get("mode", "coordinate")
    root = Path(config["root"])
    if mode == "coordinate":
        return coordinate(config)
    if mode == "atomic_reader":
        observations = 0
        generations = set()
        deadline = time.monotonic() + DEADLINE_SECONDS
        while True:
            value = read_json(root / "atomic.json", None)
            if value != atomic_payload(value["generation"]):
                raise AssertionError("Observed a mixed or incomplete record")
            observations += 1
            generations.add(value["generation"])
            if observations == 1:
                (root / "reader-ready").touch()
            if value["generation"] == 1:
                (root / "reader-saw-first").touch()
            if (root / "writer-done").exists() and value["generation"] == 64:
                return {"observations": observations,
                        "generations": sorted(generations)}
            if time.monotonic() >= deadline:
                raise TimeoutError("Atomic reader did not see writer completion")
            time.sleep(0.001)
    if mode == "atomic_writer":
        wait_for(root / "reader-ready")
        for generation in range(1, 65):
            atomic_json(root / "atomic.json", atomic_payload(generation))
            if generation == 1:
                wait_for(root / "reader-saw-first")
        (root / "writer-done").touch()
        return {"published": 64}
    if mode == "atomic_crash":
        atomic_json(root / "atomic.json", atomic_payload(999),
                    crash_before_replace=True)
    raise ValueError(mode)


@pytest.fixture
def processes():
    children = []

    def start(root, **config):
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "worker",
             json.dumps({"root": str(root), **config})],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        children.append(child)
        return child

    yield start

    for child in children:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=DEADLINE_SECONDS)


def finish(child, expected=0):
    stdout, stderr = child.communicate(timeout=DEADLINE_SECONDS)
    assert child.returncode == expected, (child.returncode, stdout, stderr)
    return json.loads(stdout) if stdout.strip() else None


def test_competing_invocations_submit_equivalent_work_once(tmp_path, processes):
    ready = tmp_path / "first-has-lock"
    release = tmp_path / "release-first"
    contended = tmp_path / "second-observed-contention"
    first = processes(tmp_path, targets=["align"], lock_ready=str(ready),
                      release_lock=str(release))
    wait_for(ready)
    second = processes(tmp_path, targets=["align"],
                       lock_contended=str(contended))
    wait_for(contended)
    assert second.poll() is None
    assert scheduler_jobs(tmp_path) == []
    release.touch()
    first_result, second_result = finish(first), finish(second)
    assert first_result == second_result
    assert len(scheduler_jobs(tmp_path)) == 1
    assert first_result["targets"]["align"]["job_id"] == "fake-job-1"


def test_crash_before_acceptance_recovers_intent_and_releases_lock(tmp_path, processes):
    finish(processes(tmp_path, targets=["align"], crash_before="align"), CRASH_EXIT)
    before = read_json(tmp_path / "project.json", None)["targets"]["align"]
    assert before["job_id"] is None
    assert scheduler_jobs(tmp_path) == []
    recovered = finish(processes(tmp_path, targets=["align"]))["targets"]["align"]
    assert recovered["attempt"] == before["attempt"]
    assert recovered["job_id"] == "fake-job-1"
    assert len(scheduler_jobs(tmp_path)) == 1


def test_crash_after_acceptance_reconciles_before_duplicate(tmp_path, processes):
    finish(processes(tmp_path, targets=["align"], crash_after="align"), CRASH_EXIT)
    before = read_json(tmp_path / "project.json", None)["targets"]["align"]
    accepted = scheduler_jobs(tmp_path)
    assert before["job_id"] is None
    assert len(accepted) == 1
    assert accepted[0]["attempt"] == before["attempt"]
    recovered = finish(processes(tmp_path, targets=["align"]))["targets"]["align"]
    assert recovered["job_id"] == accepted[0]["job_id"]
    assert scheduler_jobs(tmp_path) == accepted


def test_partial_submission_preserves_prior_mapping_and_finishes_plan(tmp_path, processes):
    targets = ["trim", "align", "index"]
    finish(processes(tmp_path, targets=targets, crash_after="align"), CRASH_EXIT)
    before = read_json(tmp_path / "project.json", None)["targets"]
    assert before["trim"]["job_id"] == "fake-job-1"
    assert before["align"]["job_id"] is None
    assert "index" not in before
    recovered = finish(processes(tmp_path, targets=targets))["targets"]
    assert recovered["trim"] == before["trim"]
    assert recovered["align"]["attempt"] == before["align"]["attempt"]
    assert [recovered[name]["job_id"] for name in targets] == [
        "fake-job-1", "fake-job-2", "fake-job-3",
    ]
    assert [job["target"] for job in scheduler_jobs(tmp_path)] == targets


def test_reconciliation_does_not_adopt_foreign_owner_token(tmp_path, processes):
    attempt = "same-visible-token"
    atomic_json(tmp_path / "project.json", {
        "targets": {"align": {"attempt": attempt, "job_id": None}},
    })
    foreign_id = scheduler_accept(tmp_path, "different-project", "align", attempt)
    result = finish(processes(tmp_path, targets=["align"]))["targets"]["align"]
    assert result["job_id"] != foreign_id
    jobs = scheduler_jobs(tmp_path)
    assert len(jobs) == 2
    assert jobs[1]["owner"] == OWNER
    assert jobs[1]["attempt"] == attempt


def test_atomic_replace_readers_and_crash_keep_complete_records(tmp_path, processes):
    atomic_json(tmp_path / "atomic.json", atomic_payload(0))
    reader = processes(tmp_path, mode="atomic_reader")
    wait_for(tmp_path / "reader-ready")
    writer = processes(tmp_path, mode="atomic_writer")
    assert finish(writer) == {"published": 64}
    read_result = finish(reader)
    assert read_result["observations"] >= 3
    assert {0, 1, 64} <= set(read_result["generations"])
    assert read_json(tmp_path / "atomic.json", None) == atomic_payload(64)
    finish(processes(tmp_path, mode="atomic_crash"), CRASH_EXIT)
    assert read_json(tmp_path / "atomic.json", None) == atomic_payload(64)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "worker":
        raise SystemExit("This file's executable mode is only for pytest fixture workers")
    print(json.dumps(run_worker(json.loads(sys.argv[2])), sort_keys=True))
