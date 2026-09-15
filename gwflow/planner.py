"""Compile trusted Python definitions into descriptions of intended work."""
from dataclasses import dataclass, field
import importlib
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
from typing import Callable, Mapping


class PlanError(ValueError):
    """An invalid definition, binding, or plan request."""


@dataclass(frozen=True)
class Target:
    name: str
    command: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Context:
    inputs: Mapping[str, str]
    work_dir: str
    result_dir: str
    retained: Mapping[str, str]

    def path(self, relative: str) -> str:
        """Locate a declared output (retained files go in the result slot)."""
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise PlanError(f"output path must be relative and contained: {relative!r}")
        root = self.result_dir if relative in self.retained.values() else self.work_dir
        return os.path.normpath(os.path.join(root, relative))


@dataclass(frozen=True)
class Subpipeline:
    name: str
    version: str
    inputs: Mapping[str, str]
    outputs: Mapping[str, str]
    build: Callable[[Context], list[Target]]
    package: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MainPipeline:
    name: str
    version: str
    subpipeline: Subpipeline
    package: Mapping[str, str] = field(default_factory=dict)


def load(selector: str) -> MainPipeline:
    """Load an exported main pipeline using module:attribute."""
    module, sep, entry = selector.partition(":")
    if not sep or not module or not entry:
        raise PlanError(f"definition selector {selector!r}: expected module:attribute")
    try:
        obj = getattr(importlib.import_module(module), entry)
    except Exception as exc:
        raise PlanError(f"cannot load definition {selector!r}: {exc}") from exc
    if not isinstance(obj, MainPipeline):
        raise PlanError(f"definition {selector!r} must export a MainPipeline")
    return obj


def _named(value, label):
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{label} must be a nonempty string")


def plan(main: MainPipeline, bindings: Mapping, *, project: str | Path) -> dict:
    """Plan without reading input payloads, checking existence, or creating files."""
    from . import __version__
    from .identity import address, file_binding
    if not isinstance(main, MainPipeline) or not isinstance(main.subpipeline, Subpipeline):
        raise PlanError("main pipeline must select a Subpipeline")
    sub = main.subpipeline
    for label, value in [("main name", main.name), ("main version", main.version),
                         ("subpipeline name", sub.name), ("subpipeline version", sub.version)]:
        _named(value, label)
    if not isinstance(bindings, Mapping):
        raise PlanError(f"{sub.name}: bindings must be a mapping")
    missing, unknown = set(sub.inputs) - set(bindings), set(bindings) - set(sub.inputs)
    if missing or unknown:
        raise PlanError(f"{sub.name}: missing bindings {sorted(missing)}; unknown bindings {sorted(unknown)}")
    root = os.path.abspath(os.fspath(project))
    resolved, descriptors = {}, {}
    for name, kind in sub.inputs.items():
        value = bindings[name]
        if kind != "file" or not isinstance(value, (str, Path)) or not str(value):
            raise PlanError(f"{sub.name} binding {name!r}: expected file path, got {value!r} (kind {kind!r})")
        resolved[name], descriptors[name] = file_binding(value, root, f"{sub.name} binding {name!r}")
    identity, descriptor = address(sub.name, sub.version, descriptors)
    ctx = Context(resolved, os.path.join(root, "work", identity[:2], identity),
                  os.path.join(root, "results", identity[:2], identity), sub.outputs)
    retained = {name: ctx.path(path) for name, path in sub.outputs.items()}
    try:
        targets = list(sub.build(ctx))
    except Exception as exc:
        raise PlanError(f"{sub.name}: builder failed: {exc}") from exc
    if len(targets) != 1 or not isinstance(targets[0], Target):
        raise PlanError(f"{sub.name}: this planning slice requires one Target")
    target = targets[0]
    _named(target.name, f"{sub.name} target name")
    _named(target.command, f"{sub.name}/{target.name} command")
    if not set(retained.values()) <= set(target.outputs):
        raise PlanError(f"{sub.name}: retained outputs must be produced by its target")
    try:
        gwf_version = version("gwf")
    except PackageNotFoundError:
        gwf_version = None
    return {
        "kind": "plan", "project": root,
        "main": {"name": main.name, "version": main.version, "package": dict(main.package)},
        "software": {"gwflow": __version__, "gwf": gwf_version},
        "computations": [{
            "identity": identity, "descriptor": descriptor,
            "work_dir": ctx.work_dir, "result_dir": ctx.result_dir,
            "definition": {"name": sub.name, "version": sub.version, "package": dict(sub.package)},
            "input_interface": dict(sub.inputs), "bindings": resolved,
            "retained_outputs": retained,
            "targets": [{"name": target.name, "command": target.command,
                         "inputs": list(target.inputs), "outputs": list(target.outputs)}],
        }],
        "runtime_evaluation": "not evaluated",
        "external_input_existence": "not evaluated",
    }
