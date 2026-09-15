"""Bounded, type-preserving JSON values for data and fixed parameters."""
import json
import math
from .planner import PlanError


def small_data(value, label):
    def check(item, depth):
        if depth > 16:
            raise PlanError(f"{label}: small data exceeds depth 16")
        kind = type(item)
        if item is None or kind in (str, bool):
            return
        if kind is int and abs(item) <= 2**53 - 1:
            return
        if kind is float and math.isfinite(item):
            return
        if kind is list:
            for child in item:
                check(child, depth + 1)
            return
        if kind is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise PlanError(f"{label}: unsupported small data type or value {type(item).__name__}")
    check(value, 0)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(encoded) > 16384:
        raise PlanError(f"{label}: small data exceeds 16384 encoded bytes")
    return json.loads(encoded)
