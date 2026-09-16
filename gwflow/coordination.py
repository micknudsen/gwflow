"""Short command coordination, without automatic stale takeover."""
import os
from pathlib import Path
from .record_io import durable_rmdir, durable_unlink, publish_json, read_json
from .runtime_errors import RuntimeFailure
from .runtime_records import tracking_path


def guard_path(project):
    return Path(project) / ".gwflow" / "command-guard"


def marker_path(project):
    return Path(project) / ".gwflow" / "submission.json"


def blocking_reason(project):
    # Even malformed records and dangling links preserve the uncertainty block.
    if os.path.lexists(marker_path(project)):
        return "submission-uncertain", "a retained submission marker requires explicit manual recovery"
    if os.path.lexists(guard_path(project)):
        return "command-guard-held", "the project command guard is held; no automatic stale takeover is allowed"
    return None


def observation_generation(project):
    """Read the retained, uniquely named submissions without reserving state."""
    try:
        return frozenset(path.name for path in (tracking_path(project).parent / "submissions").iterdir())
    except FileNotFoundError:
        return frozenset()


def acquire_guard(project, owner):
    path = guard_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()  # Exclusive cross-node coordination operation.
    except FileExistsError as exc:
        raise RuntimeFailure("command-guard-held", "the project command guard is held; no automatic stale takeover is allowed") from exc
    publish_json(path / "owner.json", {"kind": "command-guard-owner", "record_revision": 1, "owner": owner})
    return path


def release_guard(path, owner):
    expected = {"kind": "command-guard-owner", "record_revision": 1, "owner": owner}
    if read_json(path / "owner.json") != expected:
        raise RuntimeFailure("guard-ownership-lost", "command guard ownership changed; refusing to release it")
    durable_unlink(path / "owner.json")
    durable_rmdir(path)
