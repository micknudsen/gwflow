"""Version 1 descriptor addressing; no filesystem observations."""
import hashlib
import json
import os
import re
from pathlib import Path

from .planner import PlanError

IDENTITY_VERSION = 1


def file_binding(value, root, label):
    if not isinstance(value, (str, Path)) or not str(value) or "\0" in str(value):
        raise PlanError(f"{label}: expected file path, got {value!r}")
    path = os.path.abspath(os.path.join(root, str(value)))
    contained = os.path.commonpath([root, path]) == root
    return path, {"kind": "file", "scope": "project" if contained else "external",
                  "path": os.path.relpath(path, root) if contained else path}


def address(name, version, bindings):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+", name):
        raise PlanError(f"subpipeline name {name!r}: use a globally qualified name such as package.definition")
    descriptor = {"identity_version": IDENTITY_VERSION,
                  "definition": {"name": name, "version": version}, "bindings": bindings}
    encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest(), descriptor
