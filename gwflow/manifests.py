"""Versioned planning records, never execution evidence."""
from copy import deepcopy
import os
import re

from .data import small_data
from .environments import LocalImage, RegistryImage
from .graph import compile_graph, contained, relative_output
from .identity import address, file_binding
from .planner import Context, PlanError, Target

SCHEMA_VERSION = 1
COMPUTATION_FIELDS = (
    "identity descriptor work_dir result_dir definition input_interface bindings "
    "computational_parameters connections whole_producer_dependencies retained_outputs "
    "output_interface targets computational_edges entry_targets terminal_targets "
    "internal_outputs occurrences completion_obligations"
).split()


def _fail(label, detail):
    raise PlanError(f"manifest {label}: {detail}")


def _object(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        _fail(label, f"expected fields {sorted(keys)}")


def _string(value, label):
    if type(value) is not str or not value or "\0" in value:
        _fail(label, "expected nonempty string")


def _strings(value, label):
    if type(value) is not list:
        _fail(label, "expected string array")
    for item in value:
        _string(item, label)


def _mapping(value, label):
    if type(value) is not dict:
        _fail(label, "expected named object")
    for key in value:
        _string(key, label)


def _string_map(value, label):
    _mapping(value, label)
    for item in value.values():
        if type(item) is not str:
            _fail(label, "expected string values")


def _definition(value, label):
    _object(value, ("name", "version", "package"), label)
    _string(value["name"], label + ".name")
    _string(value["version"], label + ".version")
    _string_map(value["package"], label + ".package")


def _descriptor_binding(value, label):
    if type(value) is not dict:
        _fail(label, "expected typed binding")
    kind = value.get("kind")
    if kind == "file":
        _object(value, ("kind", "scope", "path"), label)
        _string(value["path"], label + ".path")
        if value["scope"] not in ("project", "external"):
            _fail(label, "unsupported file scope")
    elif kind == "files":
        _object(value, ("kind", "items"), label)
        if type(value["items"]) is not list:
            _fail(label, "expected file descriptor array")
        for item in value["items"]:
            if type(item) is not dict or item.get("kind") != "file":
                _fail(label, "file lists require file elements")
            _descriptor_binding(item, label)
    elif kind == "data":
        _object(value, ("kind", "value"), label)
        small_data(value["value"], "manifest " + label)
    elif kind == "output":
        _object(value, ("kind", "computation", "output"), label)
        _identity(value["computation"], label)
        _string(value["output"], label)
    else:
        _fail(label, "unsupported binding kind")


def _identity(value, label):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail(label, "expected SHA-256 computation identity")


def manifest(plan, identity):
    """Return a detached schema-1 record for one computation in a public plan."""
    try:
        computation = next(c for c in plan["computations"] if c["identity"] == identity)
        record = {"kind": "planned-computation", "schema_version": SCHEMA_VERSION,
                  "interpretation": {"identity": 1, "definition_api": 1},
                  "project": plan["project"],
                  "computation": {k: deepcopy(computation[k]) for k in COMPUTATION_FIELDS},
                  "provenance": {"main": deepcopy(plan["main"]), "software": deepcopy(plan["software"])},
                  "runtime_evaluation": "not evaluated"}
    except (KeyError, TypeError, StopIteration) as exc:
        raise PlanError(f"manifest: missing computation or plan fields for {identity!r}") from exc
    validate_manifest(record)
    return record


def validate_manifest(record):
    """Validate structure and internal consistency without observing any files."""
    _object(record, ("kind", "schema_version", "interpretation", "project", "computation", "provenance", "runtime_evaluation"), "record")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        _fail("schema_version", "unsupported revision; expected 1")
    _object(record["interpretation"], ("identity", "definition_api"), "interpretation")
    if any(type(v) is not int or v != 1 for v in record["interpretation"].values()):
        _fail("interpretation", "unsupported revision; expected identity=1 and definition_api=1")
    if record["kind"] != "planned-computation" or record["runtime_evaluation"] != "not evaluated":
        _fail("record", "must describe planned work with runtime evaluation not evaluated")
    root = record["project"]
    _string(root, "project")
    if not os.path.isabs(root) or os.path.normpath(root) != root:
        _fail("project", "expected normalized absolute lexical path")
    c = record["computation"]
    _object(c, COMPUTATION_FIELDS, "computation")
    _identity(c["identity"], "computation.identity")
    _definition(c["definition"], "definition")
    d = c["descriptor"]
    _object(d, ("identity_version", "definition", "bindings"), "descriptor")
    if type(d["identity_version"]) is not int or d["identity_version"] != 1:
        _fail("descriptor", "unsupported identity revision")
    _object(d["definition"], ("name", "version"), "descriptor.definition")
    if d["definition"] != {k: c["definition"][k] for k in ("name", "version")}:
        _fail("definition", "does not match descriptor")
    _mapping(d["bindings"], "descriptor.bindings")
    for name, binding in d["bindings"].items():
        _descriptor_binding(binding, f"binding {name!r}")
    expected, _ = address(d["definition"]["name"], d["definition"]["version"], d["bindings"])
    if expected != c["identity"]:
        _fail("identity", "does not match canonical descriptor")
    for field, folder in (("work_dir", "work"), ("result_dir", "results")):
        if c[field] != os.path.join(root, folder, expected[:2], expected):
            _fail(field, "does not match project and identity")
    for field in ("input_interface", "output_interface", "retained_outputs"):
        _string_map(c[field], field)
    _mapping(c["bindings"], "bindings")
    _mapping(c["computational_parameters"], "computational_parameters")
    small_data(c["computational_parameters"], "manifest computational_parameters")
    if set(c["input_interface"]) & set(c["computational_parameters"]):
        _fail("computational_parameters", "overlaps input interface")
    if set(c["bindings"]) != set(d["bindings"]) or set(c["bindings"]) != set(c["input_interface"]):
        _fail("bindings", "must match input interface and descriptor")
    if type(c["connections"]) is not list:
        _fail("connections", "expected array")
    connections = {}
    for connection in c["connections"]:
        _object(connection, ("input", "producer", "output", "path"), "connection")
        for key in connection:
            _string(connection[key], "connection." + key)
        _identity(connection["producer"], "connection.producer")
        if connection["input"] in connections:
            _fail("connections", "duplicate input connection")
        connections[connection["input"]] = connection
    for name, kind in c["input_interface"].items():
        value, binding = c["bindings"][name], d["bindings"][name]
        if binding["kind"] == "output":
            connection = connections.get(name)
            if kind != "file" or connection != {"input": name, "producer": binding["computation"], "output": binding["output"], "path": value}:
                _fail(name, "output descriptor requires matching file connection")
            _string(value, name)
            producer_root = os.path.join(root, "results", binding["computation"][:2], binding["computation"])
            if not os.path.isabs(value) or value != os.path.normpath(value) or not contained(value, producer_root) or value == producer_root:
                _fail(name, "connection path must be in the producer result slot")
        elif kind == "file":
            normalized, desc = file_binding(value, root, "manifest " + name)
            if value != normalized or binding != desc:
                _fail(name, "file binding does not match normalized descriptor")
        elif kind == "files":
            if type(value) is not list:
                _fail(name, "expected file array")
            items = [file_binding(p, root, "manifest " + name) for p in value]
            if value != [p for p, _ in items] or binding != {"kind": "files", "items": [d for _, d in items]}:
                _fail(name, "file list does not match descriptor")
        elif kind == "data":
            small_data(value, "manifest " + name)
            # Python equality equates bool/int and int/float: compare canonical JSON.
            import json
            if json.dumps({"kind": "data", "value": value}, sort_keys=True) != json.dumps(binding, sort_keys=True):
                _fail(name, "data value does not match typed descriptor")
        else:
            _fail(name, "unsupported input kind")
    if set(connections) != {n for n, b in d["bindings"].items() if b["kind"] == "output"}:
        _fail("connections", "must match output descriptor bindings")
    for field in ("whole_producer_dependencies", "entry_targets", "terminal_targets", "internal_outputs", "occurrences"):
        _strings(c[field], field)
        if len(set(c[field])) != len(c[field]):
            _fail(field, "duplicate members")
    producers = sorted({v["producer"] for v in connections.values()})
    if c["whole_producer_dependencies"] != producers or c["identity"] in producers:
        _fail("whole_producer_dependencies", "must match distinct upstream connections")
    ctx = Context(c["bindings"], c["work_dir"], c["result_dir"], c["output_interface"], c["computational_parameters"], root)
    if any(relative_output(p) != p for p in c["output_interface"].values()) or c["retained_outputs"] != {n: ctx.path(p) for n, p in c["output_interface"].items()}:
        _fail("retained_outputs", "must match declared output interface")
    if type(c["targets"]) is not list or type(c["computational_edges"]) is not list:
        _fail("graph", "expected target and edge arrays")
    explicit = {}
    for edge in c["computational_edges"]:
        if type(edge) is not dict or edge.get("kind") not in ("file", "explicit"):
            _fail("edge", "expected file or explicit computational edge")
        _object(edge, ("producer", "consumer", "kind", "path") if edge["kind"] == "file" else ("producer", "consumer", "kind"), "edge")
        for item in edge.values():
            _string(item, "edge")
        if edge["kind"] == "explicit":
            explicit.setdefault(edge["consumer"], []).append(edge["producer"])
    targets = []
    for t in c["targets"]:
        _object(t, ("name", "computation", "command", "inputs", "outputs", "resources", "environment", "always_run", "dependencies", "output_kinds"), "target")
        _string(t["name"], "target.name")
        _string(t["command"], "target.command")
        if t["computation"] != c["identity"] or type(t["always_run"]) is not bool:
            _fail("target", "invalid computation membership or always_run flag")
        for field in ("inputs", "outputs", "dependencies"):
            _strings(t[field], "target." + field)
        _string_map(t["output_kinds"], "target.output_kinds")
        env = t["environment"]
        if type(env) is not dict or env.get("kind") not in ("host", "local-sif", "registry"):
            _fail("environment", "unsupported declaration")
        _object(env, ("kind", "declaration", "path") if env["kind"] == "local-sif" else ("kind", "declaration"), "environment")
        image = None if env["kind"] == "host" else LocalImage(env["declaration"]) if env["kind"] == "local-sif" else RegistryImage(env["declaration"])
        targets.append(Target(t["name"], t["command"], t["inputs"], t["outputs"], t["resources"], explicit.get(t["name"], []), image))
    graph = compile_graph(targets, ctx, c["identity"], c["retained_outputs"], {}, "manifest graph")
    if any(c[key] != value for key, value in graph.items()):
        _fail("graph", "compiled paths, environments, edges, membership or constraints are inconsistent")
    if type(c["completion_obligations"]) is not list:
        _fail("completion_obligations", "expected array")
    seen = []
    for obligation in c["completion_obligations"]:
        _object(obligation, ("producer", "condition", "required_targets", "terminal_targets", "evaluation"), "obligation")
        if obligation["condition"] != "whole-subpipeline completion" or obligation["evaluation"] != "not evaluated":
            _fail("obligation", "must express unevaluated whole-subpipeline completion")
        for field in ("required_targets", "terminal_targets"):
            _strings(obligation[field], "obligation." + field)
            if not obligation[field] or len(set(obligation[field])) != len(obligation[field]):
                _fail("obligation", "expected nonempty distinct target membership")
        if not set(obligation["terminal_targets"]) <= set(obligation["required_targets"]):
            _fail("obligation", "terminal targets must be required members")
        seen.append(obligation["producer"])
    if seen != producers:
        _fail("obligations", "must match upstream producers")
    p = record["provenance"]
    _object(p, ("main", "software"), "provenance")
    _object(p["software"], ("gwflow", "gwf"), "software")
    _string(p["software"]["gwflow"], "software.gwflow")
    if p["software"]["gwf"] is not None:
        _string(p["software"]["gwf"], "software.gwf")
    m = p["main"]
    _object(m, ("name", "version", "package", "occurrences"), "main")
    _definition({k: m[k] for k in ("name", "version", "package")}, "main")
    _mapping(m["occurrences"], "main.occurrences")
    members = []
    for name, occurrence in m["occurrences"].items():
        _object(occurrence, ("identity", "definition"), "occurrence")
        _identity(occurrence["identity"], "occurrence.identity")
        _definition(occurrence["definition"], "occurrence.definition")
        if occurrence["identity"] == c["identity"]:
            if any(occurrence["definition"][k] != c["definition"][k] for k in ("name", "version")):
                _fail("occurrence", "selected definition does not match computation")
            members.append(name)
    if not set(producers) <= {o["identity"] for o in m["occurrences"].values()}:
        _fail("connections", "upstream producers must belong to the main composition")
    if not members or sorted(members) != c["occurrences"]:
        _fail("occurrences", "membership must match main provenance")
