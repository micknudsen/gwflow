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
    resources: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Context:
    inputs: Mapping[str, object]
    work_dir: str
    result_dir: str
    retained: Mapping[str, str]
    parameters: Mapping[str, object] = field(default_factory=dict)

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
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DefinitionRef:
    selector: str
    name: str
    version: str


@dataclass(frozen=True)
class Use:
    definition: Subpipeline | DefinitionRef
    bindings: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MainPipeline:
    name: str
    version: str
    subpipeline: Subpipeline | None = None
    package: Mapping[str, str] = field(default_factory=dict)
    uses: Mapping[str, Use] = field(default_factory=dict)


def _load_export(selector):
    if not isinstance(selector, str):
        raise PlanError("definition selector must be a string")
    module, sep, entry = selector.partition(":")
    if not sep or not module or not entry:
        raise PlanError(f"definition selector {selector!r}: expected module:attribute")
    try:
        return getattr(importlib.import_module(module), entry)
    except Exception as exc:
        raise PlanError(f"cannot load definition {selector!r}: {exc}") from exc


def load(selector: str) -> MainPipeline:
    """Load an exported main pipeline using module:attribute."""
    obj = _load_export(selector)
    if not isinstance(obj, MainPipeline):
        raise PlanError(f"definition {selector!r} must export a MainPipeline")
    return obj


def _named(value, label):
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{label} must be a nonempty string")


def _compile(sub, bindings, root, resource_overrides=None):
    from .resources import resources
    from .identity import address, file_binding
    from .data import small_data
    for label, value in [("subpipeline name", sub.name), ("subpipeline version", sub.version)]:
        _named(value, label)
    if not isinstance(bindings, Mapping):
        raise PlanError(f"{sub.name}: bindings must be a mapping")
    missing, unknown = set(sub.inputs) - set(bindings), set(bindings) - set(sub.inputs)
    if missing or unknown:
        raise PlanError(f"{sub.name}: missing bindings {sorted(missing)}; unknown bindings {sorted(unknown)}")
    if not isinstance(sub.parameters, Mapping) or set(sub.parameters) & set(sub.inputs):
        raise PlanError(f"{sub.name}: computational parameters must be a mapping separate from input names")
    parameters = small_data(dict(sub.parameters), f"{sub.name} computational parameters")
    resolved, descriptors = {}, {}
    for name, kind in sub.inputs.items():
        value = bindings[name]
        label = f"{sub.name} binding {name!r}"
        if kind == "file":
            resolved[name], descriptors[name] = file_binding(value, root, label)
        elif kind == "files":
            if not isinstance(value, (list, tuple)):
                raise PlanError(f"{label}: expected finite file list, got {value!r}")
            items = [file_binding(item, root, f"{label} element {i}") for i, item in enumerate(value)]
            resolved[name] = [path for path, _ in items]
            descriptors[name] = {"kind": "files", "items": [desc for _, desc in items]}
        elif kind == "data":
            resolved[name] = small_data(value, label)
            descriptors[name] = {"kind": "data", "value": small_data(value, label)}
        else:
            raise PlanError(f"{label}: unsupported input kind {kind!r}")
    identity, descriptor = address(sub.name, sub.version, descriptors)
    ctx = Context(resolved, os.path.join(root, "work", identity[:2], identity),
                  os.path.join(root, "results", identity[:2], identity), sub.outputs,
                  small_data(parameters, f"{sub.name} computational parameters"))
    retained = {name: ctx.path(path) for name, path in sub.outputs.items()}
    try:
        targets = list(sub.build(ctx))
    except Exception as exc:
        raise PlanError(f"{sub.name}: builder failed: {exc}") from exc
    if len(targets) != 1 or not isinstance(targets[0], Target):
        raise PlanError(f"{sub.name}: this planning slice requires one Target")
    target = targets[0]
    _named(target.name, f"{sub.name} target name")
    overrides = {} if resource_overrides is None else resource_overrides
    if not isinstance(overrides, Mapping) or set(overrides) - {target.name}:
        raise PlanError(f"{sub.name}: resource overrides must name existing targets")
    requested = resources(target.resources, f"{sub.name}/{target.name}")
    requested.update(resources(overrides.get(target.name, {}), f"{sub.name}/{target.name}"))
    _named(target.command, f"{sub.name}/{target.name} command")
    if not set(retained.values()) <= set(target.outputs):
        raise PlanError(f"{sub.name}: retained outputs must be produced by its target")
    return {
            "identity": identity, "descriptor": descriptor,
            "work_dir": ctx.work_dir, "result_dir": ctx.result_dir,
            "definition": {"name": sub.name, "version": sub.version, "package": dict(sub.package)},
            "input_interface": dict(sub.inputs), "bindings": resolved,
            "computational_parameters": parameters,
            "retained_outputs": retained,
            "targets": [{"name": target.name, "command": target.command,
                         "inputs": list(target.inputs), "outputs": list(target.outputs), "resources": requested}],
    }


def plan(main: MainPipeline, bindings: Mapping | None = None, *, project: str | Path, resources: Mapping | None = None) -> dict:
    """Plan one explicitly selected project without observing runtime state."""
    from . import __version__
    from .data import small_data
    if not isinstance(main, MainPipeline):
        raise PlanError("definition must be a MainPipeline")
    _named(main.name, "main name")
    _named(main.version, "main version")
    root = os.path.abspath(os.fspath(project))
    bindings = {} if bindings is None else bindings
    if not isinstance(bindings, Mapping):
        raise PlanError(f"{main.name}: bindings must be a mapping")
    if main.subpipeline is not None:
        if main.uses or not isinstance(main.subpipeline, Subpipeline):
            raise PlanError(f"{main.name}: select either one subpipeline or named uses")
        uses = {"main": Use(main.subpipeline, bindings)}
    else:
        if not isinstance(main.uses, Mapping) or not main.uses:
            raise PlanError(f"{main.name}: requires named uses")
        unknown = set(bindings) - set(main.uses)
        if unknown:
            raise PlanError(f"{main.name}: unknown occurrences {sorted(unknown)}")
        uses = {}
        for name, use in main.uses.items():
            _named(name, "occurrence name")
            if not isinstance(use, Use) or not isinstance(use.bindings, Mapping):
                raise PlanError(f"occurrence {name!r}: expected Use with named bindings")
            overrides = bindings.get(name, {})
            if not isinstance(overrides, Mapping):
                raise PlanError(f"occurrence {name!r}: bindings must be a mapping")
            uses[name] = Use(use.definition, {**use.bindings, **overrides})
    resources = {} if resources is None else resources
    if not isinstance(resources, Mapping) or set(resources) - set(uses):
        raise PlanError(f"{main.name}: resource overrides must name existing occurrences")
    definitions, computations, occurrences = {}, {}, {}
    for name, use in sorted(uses.items()):
        sub = use.definition
        if isinstance(sub, DefinitionRef):
            exported = _load_export(sub.selector)
            if not isinstance(exported, Subpipeline) or (exported.name, exported.version) != (sub.name, sub.version):
                raise PlanError(f"occurrence {name!r}: export {sub.selector!r} does not match requested {sub.name}@{sub.version}")
            sub = exported
        if not isinstance(sub, Subpipeline):
            raise PlanError(f"occurrence {name!r}: unresolved subpipeline definition")
        key = (sub.name, sub.version)
        visible = (dict(sub.inputs), dict(sub.outputs), small_data(dict(sub.parameters), f"{sub.name} parameters"), sub.build)
        if key in definitions and definitions[key] != visible:
            raise PlanError(f"occurrence {name!r}: conflicting immutable definition {sub.name}@{sub.version}")
        definitions[key] = visible
        comp = _compile(sub, use.bindings, root, resources.get(name, {}))
        identity = comp["identity"]
        if identity in computations:
            previous = computations[identity]
            if [t["resources"] for t in previous["targets"]] != [t["resources"] for t in comp["targets"]]:
                raise PlanError(f"occurrence {name!r}: conflicting resources for equivalent computation")
            if previous["targets"] != comp["targets"]:
                raise PlanError(f"occurrence {name!r}: conflicting compiled definition {sub.name}@{sub.version}")
            previous["occurrences"].append(name)
        else:
            comp["occurrences"] = [name]
            computations[identity] = comp
        occurrences[name] = {"identity": identity, "definition": comp["definition"]}
    try:
        gwf_version = version("gwf")
    except PackageNotFoundError:
        gwf_version = None
    return {
        "kind": "plan", "project": root,
        "main": {"name": main.name, "version": main.version, "package": dict(main.package), "occurrences": occurrences},
        "software": {"gwflow": __version__, "gwf": gwf_version},
        "computations": [computations[key] for key in sorted(computations)],
        "runtime_evaluation": "not evaluated", "external_input_existence": "not evaluated",
    }
