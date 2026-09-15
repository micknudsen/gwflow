"""Operational requests kept outside definition builders and identity."""
from collections.abc import Mapping
from .planner import PlanError


def resources(value, label):
    if not isinstance(value, Mapping):
        raise PlanError(f"{label}: resources must be a mapping")
    result = dict(value)
    for name, item in result.items():
        if name in ("memory_mb", "walltime_seconds"):
            valid = type(item) is int and item > 0
        elif name in ("partition", "account"):
            valid = isinstance(item, str) and bool(item.strip()) and not any(c.isspace() for c in item)
        else:
            raise PlanError(f"{label}: unsupported resource {name!r}")
        if not valid:
            raise PlanError(f"{label}: invalid resource {name!r}: {item!r}")
    return result
