"""Retained-output connections and lexical boundaries within a planned graph."""
from .graph import acyclic, contained
from .planner import OutputRef, PlanError


def order_uses(uses):
    dependencies = {}
    for name, use in sorted(uses.items()):
        refs = [v for v in use.bindings.values() if isinstance(v, OutputRef)]
        dependencies[name] = set()
        for ref in refs:
            if not isinstance(ref.occurrence, str) or ref.occurrence not in uses:
                raise PlanError(f"occurrence {name!r}: unknown producer {ref.occurrence!r}")
            if not isinstance(ref.output, str) or not ref.output:
                raise PlanError(f"occurrence {name!r}: invalid retained output name {ref.output!r}")
            dependencies[name].add(ref.occurrence)
    return acyclic({n: sorted(d) for n, d in dependencies.items()}, "main composition")


def resolve_connections(use, planned, name):
    connections = {}
    for binding, ref in use.bindings.items():
        if not isinstance(ref, OutputRef):
            continue
        producer = planned[ref.occurrence]
        if ref.output not in producer["retained_outputs"]:
            raise PlanError(f"occurrence {name!r} binding {binding!r}: producer {ref.occurrence!r} has no retained output {ref.output!r}; internal intermediates are private")
        connections[binding] = {"input": binding, "producer": producer["identity"],
                                "output": ref.output, "path": producer["retained_outputs"][ref.output]}
    return connections


def check_boundaries(computations):
    """Require explicit connections even when a raw path names a retained file."""
    edges = []
    for consumer in computations:
        connections = {c["input"]: c for c in consumer["connections"]}
        paths = []
        for name, kind in consumer["input_interface"].items():
            if name in connections or kind == "data":
                continue
            value = consumer["bindings"][name]
            paths.extend((path, f"binding {name!r}", False) for path in ([value] if kind == "file" else value))
        for target in consumer["targets"]:
            paths.extend((p, f"target {target['name']!r}", p in {c["path"] for c in connections.values()}) for p in target["inputs"])
        for path, context, connected in paths:
            for producer in computations:
                if producer["identity"] == consumer["identity"]:
                    continue
                if any(contained(path, producer[key]) for key in ("work_dir", "result_dir")) and not connected:
                    raise PlanError(f"{consumer['definition']['name']} {context}: raw path {path} bypasses producer {producer['definition']['name']} retained-output interface; use OutputRef")
        for connection in connections.values():
            producer = next(c for c in computations if c["identity"] == connection["producer"])
            producing_target = next(t["name"] for t in producer["targets"] if connection["path"] in t["outputs"])
            for target in consumer["targets"]:
                if connection["path"] in target["inputs"]:
                    edges.append({"producer": producer["identity"], "producer_target": producing_target,
                                  "consumer": consumer["identity"], "consumer_target": target["name"],
                                  "output": connection["output"], "path": connection["path"]})
    return edges


def describe_obligations(computations):
    by_id = {c["identity"]: c for c in computations}
    for consumer in computations:
        consumer["completion_obligations"] = [
            {"producer": identity, "condition": "whole-subpipeline completion",
             "required_targets": [t["name"] for t in by_id[identity]["targets"]],
             "terminal_targets": list(by_id[identity]["terminal_targets"]),
             "evaluation": "not evaluated"}
            for identity in consumer["whole_producer_dependencies"]
        ]
