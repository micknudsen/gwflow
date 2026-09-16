"""Atomic, durable JSON publication on the host filesystem.

Callers own record validation and recovery policy. An error is never a durable
commit, even if replacement already happened before a directory sync failed.
"""
import json
import os
from pathlib import Path
import tempfile


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_json(path, record):
    """Return only after data and its directory entry have been synchronized.

    Synchronize ancestor entries too: a previous interrupted publication may
    have created a directory without persisting its name. Never assume an
    existing directory proves that the complete path is durable.
    """
    encoded = json.dumps(record, ensure_ascii=True, separators=(",", ":"),
                         sort_keys=True, allow_nan=False) + "\n"
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in path.parent.parents:
        _sync_directory(parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".record-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def read_json(path):
    """Reject ambiguous JSON instead of letting the last duplicate key win."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate record field {key!r}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"non-finite record value {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique_object, parse_constant=invalid_constant)


def durable_unlink(path):
    """Remove one known record and synchronize its containing directory."""
    path = Path(path)
    path.unlink()
    _sync_directory(path.parent)


def durable_rmdir(path):
    """Remove one empty coordination directory and synchronize its parent."""
    path = Path(path)
    path.rmdir()
    _sync_directory(path.parent)
