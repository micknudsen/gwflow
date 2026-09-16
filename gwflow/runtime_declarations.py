"""Pure validation and normalization of retained computational declarations."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from .data import small_data
from .environments import LocalImage, RegistryImage
from .graph import compile_graph, relative_output
from .identity import address
from .planner import Context, PlanError, Target


TARGET_FIELDS = {"name", "command", "inputs", "outputs", "dependencies",
                 "output_kinds", "always_run", "environment"}
GRAPH_FIELDS = {"targets", "computational_edges", "entry_targets",
                "terminal_targets", "internal_outputs"}


def _fail(detail):
    raise PlanError(f"runtime record: {detail}")


def canonical(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True, allow_nan=False)


def normalized(declaration):
    """Normalize relations, but preserve command text, file lists and data types."""
    value = deepcopy(declaration)
    value["targets"].sort(key=lambda target: target["name"])
    for target in value["targets"]:
        target["dependencies"].sort()
    value["computational_edges"].sort(key=canonical)
    for field in ("entry_targets", "terminal_targets", "internal_outputs",
                  "whole_producer_dependencies"):
        if field in value:
            value[field].sort()
    return value


def _object(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        _fail(f"{label} has unexpected fields")


def _string(value, label):
    if type(value) is not str or not value or "\0" in value:
        _fail(f"invalid {label}")


def _strings(value, label):
    if type(value) is not list:
        _fail(f"invalid {label}")
    for item in value:
        _string(item, label)


def _mapping(value, label):
    if type(value) is not dict:
        _fail(f"invalid {label}")
    for key in value:
        _string(key, label)


def _absolute(path):
    _string(path, "absolute path")
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        _fail("expected normalized absolute path")


def _binding(binding):
    if type(binding) is not dict:
        _fail("invalid binding")
    kind = binding.get("kind")
    if kind == "file":
        _object(binding, {"kind", "scope", "path"}, "file binding")
        _string(binding["path"], "file path")
        if binding["scope"] == "external":
            _absolute(binding["path"])
        elif binding["scope"] != "project" or os.path.isabs(binding["path"]) or ".." in Path(binding["path"]).parts or os.path.normpath(binding["path"]) != binding["path"]:
            _fail("invalid project file binding")
    elif kind == "files":
        _object(binding, {"kind", "items"}, "file-list binding")
        if type(binding["items"]) is not list:
            _fail("invalid file-list binding")
        for item in binding["items"]:
            if type(item) is not dict or item.get("kind") != "file":
                _fail("invalid file-list element")
            _binding(item)
    elif kind == "data":
        _object(binding, {"kind", "value"}, "data binding")
        small_data(binding["value"], "runtime record data binding")
    elif kind == "output":
        _object(binding, {"kind", "computation", "output"}, "output binding")
        _string(binding["computation"], "producer identity")
        if not re.fullmatch(r"[0-9a-f]{64}", binding["computation"]):
            _fail("invalid producer identity")
        _string(binding["output"], "output name")
    else:
        _fail("invalid binding kind")


def _graph(record, project, *, compare_image_paths=True):
    """Recompile retained declarations with the same pure graph rules as plan."""
    declaration, identity = record["computational_declaration"], record["identity"]
    ctx = Context({}, os.path.join(project, "work", identity[:2], identity),
                  os.path.join(project, "results", identity[:2], identity),
                  declaration["output_interface"], declaration["computational_parameters"], project)
    explicit = {}
    for edge in declaration["computational_edges"]:
        if edge["kind"] == "explicit":
            explicit.setdefault(edge["consumer"], []).append(edge["producer"])
    targets = []
    for target in declaration["targets"]:
        env = target["environment"]
        image = None if env["kind"] == "host" else LocalImage(env["declaration"]) if env["kind"] == "local-sif" else RegistryImage(env["declaration"])
        targets.append(Target(target["name"], target["command"], target["inputs"],
                              target["outputs"], {}, explicit.get(target["name"], []), image))
    graph = compile_graph(targets, ctx, identity,
                          {name: ctx.path(path) for name, path in declaration["output_interface"].items()},
                          {}, "runtime record graph")
    graph["targets"] = [{key: target[key] for key in TARGET_FIELDS} for target in graph["targets"]]
    if not compare_image_paths:
        saved_targets = {target["name"]: target for target in declaration["targets"]}
        for target in graph["targets"]:
            if target["environment"]["kind"] == "local-sif":
                target["environment"]["path"] = saved_targets[target["name"]]["environment"]["path"]
    saved_graph = {key: declaration[key] for key in GRAPH_FIELDS}
    if canonical(normalized(graph)) != canonical(normalized(saved_graph)):
        _fail("inconsistent target declarations or graph relationships")


def validate(record, *, project=None):
    _object(record, {"kind", "record_revision", "identity", "descriptor", "computational_declaration"}, "execution manifest")
    if record["kind"] != "execution-computation" or type(record["record_revision"]) is not int or record["record_revision"] != 1:
        _fail("unsupported execution-manifest revision")
    descriptor = record["descriptor"]
    _object(descriptor, {"identity_version", "definition", "bindings"}, "identity descriptor")
    if type(descriptor["identity_version"]) is not int or descriptor["identity_version"] != 1:
        _fail("unsupported identity descriptor")
    _object(descriptor["definition"], {"name", "version"}, "definition")
    for value in descriptor["definition"].values():
        _string(value, "definition")
    _mapping(descriptor["bindings"], "bindings")
    for binding in descriptor["bindings"].values():
        _binding(binding)
    identity, _ = address(descriptor["definition"]["name"], descriptor["definition"]["version"], descriptor["bindings"])
    if record["identity"] != identity:
        _fail("identity does not match descriptor")
    declaration = record["computational_declaration"]
    _object(declaration, GRAPH_FIELDS | {"definition", "input_interface", "output_interface",
                                       "computational_parameters", "whole_producer_dependencies"}, "computational declaration")
    if declaration["definition"] != descriptor["definition"]:
        _fail("declaration definition does not match descriptor")
    for field in ("input_interface", "output_interface", "computational_parameters"):
        _mapping(declaration[field], field)
    small_data(declaration["computational_parameters"], "runtime record parameters")
    if set(declaration["input_interface"]) != set(descriptor["bindings"]) or set(declaration["input_interface"]) & set(declaration["computational_parameters"]):
        _fail("input interface, parameters and bindings disagree")
    for name, kind in declaration["input_interface"].items():
        binding_kind = descriptor["bindings"][name]["kind"]
        if kind not in ("file", "files", "data") or kind != ("file" if binding_kind == "output" else binding_kind):
            _fail("input interface disagrees with typed bindings")
    for path in declaration["output_interface"].values():
        if relative_output(path) != path:
            _fail("output interface is not normalized")
    for field in ("entry_targets", "terminal_targets", "internal_outputs", "whole_producer_dependencies"):
        _strings(declaration[field], field)
    producers = sorted({binding["computation"] for binding in descriptor["bindings"].values() if binding["kind"] == "output"})
    if sorted(declaration["whole_producer_dependencies"]) != producers or identity in producers:
        _fail("whole-producer dependencies disagree with bindings")
    if type(declaration["targets"]) is not list or not declaration["targets"]:
        _fail("invalid target declarations")
    for target in declaration["targets"]:
        if type(target) is not dict or set(target) != TARGET_FIELDS:
            _fail("invalid target declaration")
        _string(target["name"], "target name")
        _string(target["command"], "target command")
        for field in ("inputs", "outputs", "dependencies"):
            _strings(target[field], "target " + field)
        for path in target["inputs"] + target["outputs"]:
            _absolute(path)
        _mapping(target["output_kinds"], "output kinds")
        if any(kind not in ("retained", "internal") for kind in target["output_kinds"].values()):
            _fail("invalid output kinds")
        if type(target["always_run"]) is not bool:
            _fail("invalid always-run declaration")
        env = target["environment"]
        if type(env) is not dict or env.get("kind") not in ("host", "local-sif", "registry"):
            _fail("invalid environment")
        _object(env, {"kind", "declaration", "path"} if env["kind"] == "local-sif" else {"kind", "declaration"}, "environment")
        if env["kind"] == "host":
            if env["declaration"] is not None:
                _fail("host environment cannot declare an image")
        else:
            _string(env["declaration"], "image declaration")
            if env["kind"] == "local-sif":
                _absolute(env["path"])
    if type(declaration["computational_edges"]) is not list:
        _fail("invalid graph relationships")
    for edge in declaration["computational_edges"]:
        if type(edge) is not dict or edge.get("kind") not in ("file", "explicit"):
            _fail("invalid graph relationship")
        _object(edge, {"kind", "producer", "consumer", "path"} if edge["kind"] == "file" else {"kind", "producer", "consumer"}, "graph relationship")
        for value in edge.values():
            _string(value, "graph relationship")
    if project is not None:
        _graph(record, os.path.abspath(project))
        return
    # The envelope intentionally excludes project/provenance. For detached
    # validation, infer possible roots from the owned output slots. On reads
    # and writes the selected project is supplied and checked explicitly.
    outputs = [path for target in declaration["targets"] for path in target["outputs"]]
    roots = [str(parent.parent.parent.parent) for parent in Path(outputs[0]).parents
             if parent.name == identity and parent.parent.name == identity[:2]
             and parent.parent.parent.name in ("work", "results")] if outputs else ["/"]
    for root in roots:
        try:
            # Outputless detached records do not reveal a project root. Their
            # image declaration and absolute path are shape-checked here; the
            # path/declaration association is checked on project-scoped I/O.
            _graph(record, root, compare_image_paths=bool(outputs))
            return
        except PlanError:
            continue
    _fail("inconsistent target declarations or graph relationships")
