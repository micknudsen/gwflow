"""Declared target environments; resolution and acquisition are deferred."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
from .planner import PlanError


@dataclass(frozen=True)
class LocalImage:
    path: str | Path


@dataclass(frozen=True)
class RegistryImage:
    reference: str


def environment(image, project, label):
    if image is None:
        return {"kind": "host", "declaration": None}
    if isinstance(image, LocalImage):
        value = image.path
        if not isinstance(value, (str, Path)) or "\0" in str(value) or not str(value).endswith(".sif") or "://" in str(value):
            raise PlanError(f"{label}: local image must declare a .sif path")
        return {"kind": "local-sif", "declaration": str(value),
                "path": os.path.abspath(os.path.join(project, str(value)))}
    if isinstance(image, RegistryImage):
        value = image.reference
        if not isinstance(value, str) or not re.fullmatch(r"(?:docker|oras)://[A-Za-z0-9](?:[A-Za-z0-9._/:@+\-]*[A-Za-z0-9])?", value):
            raise PlanError(f"{label}: registry image requires a nonempty docker:// or oras:// reference")
        return {"kind": "registry", "declaration": value}
    raise PlanError(f"{label}: image must be LocalImage, RegistryImage, or None")
