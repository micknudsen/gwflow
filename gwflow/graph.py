"""Static computational graph validation, independent of scheduler APIs."""
from collections.abc import Mapping
from graphlib import CycleError, TopologicalSorter
import os
from pathlib import Path

from .planner import PlanError, Target, _named
from .resources import resources


def contained(path, root):
    return os.path.commonpath([path, root]) == root


def relative_output(path):
    if not isinstance(path, str) or not path or "\0" in path or Path(path).is_absolute() or ".." in Path(path).parts:
        raise PlanError(f"output path must be relative and contained: {path!r}")
    normalized = os.path.normpath(path)
    if normalized == ".":
        raise PlanError(f"output path must name a file: {path!r}")
    return normalized


def interface(value, label):
    if not isinstance(value, Mapping):
        raise PlanError(f"{label}: expected named interface mapping")
    for name in value:
        _named(name, f"{label} name")


def acyclic(dependencies, label):
    try:
        return list(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise PlanError(f"{label}: cycle {' -> '.join(exc.args[1])}") from exc


def compile_graph(targets, ctx, identity, retained, overrides, label):
    if not targets or any(not isinstance(t, Target) for t in targets):
        raise PlanError(f"{label}: builder must return a nonempty finite list of Targets")
    by_name = {}
    for target in targets:
        _named(target.name, f"{label} target name")
        _named(target.command, f"{label}/{target.name} command")
        if target.name in by_name:
            raise PlanError(f"{label}: duplicate target {target.name!r}")
        by_name[target.name] = target
    if not isinstance(overrides, Mapping) or set(overrides) - set(by_name):
        raise PlanError(f"{label}: resource overrides must name existing targets")
    records, producers, dependencies, edges = {}, {}, {}, []
    for name, target in sorted(by_name.items()):
        paths = {}
        for role, values in (("inputs", target.inputs), ("outputs", target.outputs)):
            if not isinstance(values, (tuple, list)):
                raise PlanError(f"{label}/{name}: {role} must be a finite file list")
            paths[role] = []
            for value in values:
                if not isinstance(value, (str, Path)) or not str(value) or "\0" in str(value):
                    raise PlanError(f"{label}/{name}: invalid {role} path {value!r}")
                path = os.path.abspath(os.path.join(ctx.work_dir, str(value)))
                if role == "outputs":
                    if not any(contained(path, root) and path != root for root in (ctx.work_dir, ctx.result_dir)):
                        raise PlanError(f"{label}/{name}: output outside owned work/result paths: {path}")
                    if path in producers:
                        raise PlanError(f"{label}: ambiguous producer for {path}: {producers[path]}, {name}")
                    producers[path] = name
                paths[role].append(path)
        if not isinstance(target.depends_on, (tuple, list)) or any(not isinstance(d, str) for d in target.depends_on):
            raise PlanError(f"{label}/{name}: depends_on must list target names")
        unknown = set(target.depends_on) - set(by_name)
        if unknown:
            raise PlanError(f"{label}/{name}: unknown target references {sorted(unknown)}")
        dependencies[name] = set(target.depends_on)
        edges.extend({"producer": d, "consumer": name, "kind": "explicit"} for d in sorted(set(target.depends_on)))
        requested = resources(target.resources, f"{label}/{name}")
        requested.update(resources(overrides.get(name, {}), f"{label}/{name}"))
        records[name] = {"name": name, "computation": identity, "command": target.command,
                         **paths, "resources": requested, "always_run": not bool(paths["outputs"])}
    for path in producers:
        for parent in Path(path).parents:
            if str(parent) in producers:
                raise PlanError(f"{label}: output file/path collision: {parent} and {path}")
    if len(set(retained.values())) != len(retained):
        raise PlanError(f"{label}: duplicate retained-output paths")
    for name, path in retained.items():
        if path not in producers:
            raise PlanError(f"{label}: retained output {name!r} has no target producer: {path}")
    for name, record in records.items():
        for path in record["inputs"]:
            if path in producers:
                producer = producers[path]
                dependencies[name].add(producer)
                edges.append({"producer": producer, "consumer": name, "kind": "file", "path": path})
            elif any(contained(path, root) for root in (ctx.work_dir, ctx.result_dir)):
                raise PlanError(f"{label}/{name}: unresolved internal input {path}")
        record["dependencies"] = sorted(dependencies[name])
        record["output_kinds"] = {p: "retained" if p in retained.values() else "internal" for p in record["outputs"]}
    acyclic(dependencies, label)
    used = {d for values in dependencies.values() for d in values}
    return {"targets": list(records.values()), "computational_edges": edges,
            "entry_targets": sorted(n for n, d in dependencies.items() if not d),
            "terminal_targets": sorted(set(records) - used),
            "internal_outputs": sorted(set(producers) - set(retained.values()))}
