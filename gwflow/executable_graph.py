"""Static ordering for execution, without adding computational file inputs."""
from graphlib import TopologicalSorter


def dependency_graph(plan):
    computations = {item["identity"]: item for item in plan["computations"]}
    dependencies = {}
    targets = {}
    for computation in plan["computations"]:
        identity = computation["identity"]
        for target in computation["targets"]:
            key = (identity, target["name"])
            targets[key] = (computation, target)
            required = {(identity, parent) for parent in target["dependencies"]}
            if target["name"] in computation["entry_targets"]:
                required.update((producer, terminal)
                                for producer in computation["whole_producer_dependencies"]
                                for terminal in computations[producer]["terminal_targets"])
            dependencies[key] = required
    order = tuple(TopologicalSorter(dependencies).static_order())
    return targets, dependencies, order
