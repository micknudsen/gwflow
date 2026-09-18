"""Read-only replacement checks against project-wide active consumers."""
from .evaluator import ACTIVE
from .runtime_records import UnsupportedEvidence, read_execution_manifest


def replacement_block(plan, evaluated, statuses, job_ids):
    """Return a blocking diagnosis before any new attempt can replace outputs.

    Whole-producer dependencies protect a bound computation's completion
    boundary. Inside that boundary, only ancestors of an active target conflict;
    independent branches can still recover. New consumers have no active job
    observation and therefore do not block normal static graph submission.
    """
    executing = {(identity, target["name"])
                 for identity, computation in evaluated.items()
                 for target in computation["targets"]
                 if target["decision"] == "execute"}
    if not executing:
        return None
    replacing = {identity for identity, _ in executing}
    planned = {item["identity"]: item for item in plan["computations"]}
    outputs = {path for identity, name in executing
               for target in planned[identity]["targets"] if target["name"] == name
               for path in target["outputs"]}
    declarations = {}
    for (identity, name), status in sorted(statuses.items()):
        if status not in ACTIVE:
            continue
        job = job_ids.get((identity, name), "unknown")
        label = f"{identity}/{name} (job {job}, {status})"
        if identity not in declarations:
            if identity in planned:
                # The evaluator already checked visible definition consistency.
                # Missing completion evidence must not prevent attachment.
                declarations[identity] = planned[identity]
            else:
                try:
                    saved = read_execution_manifest(plan["project"], identity)
                except UnsupportedEvidence:
                    saved = None
                declarations[identity] = saved["computational_declaration"] if saved else None
        declaration = declarations[identity]
        targets = {target["name"]: target for target in declaration["targets"]} if declaration else {}
        if name not in targets:
            # With no usable graph, an existing slot's replacement cannot be
            # proved unrelated. Brand-new slots cannot replace consumed files.
            if replacing & {owner for owner, _ in statuses}:
                return ("active-consumer-state-unknown",
                        f"cannot establish dependencies of active target {label}; "
                        "restore its execution manifest or wait for it to finish before replacing existing work")
            continue
        producers = replacing & set(declaration["whole_producer_dependencies"])
        pending = list(targets[name]["dependencies"])
        ancestors = set()
        while pending:
            parent = pending.pop()
            if parent not in ancestors:
                ancestors.add(parent)
                pending.extend(targets[parent]["dependencies"])
        internal = {parent for parent in ancestors if (identity, parent) in executing}
        consumed = outputs & set(targets[name]["inputs"])
        if producers or internal or consumed:
            affected = sorted(producers | {f"{identity}/{parent}" for parent in internal} | consumed)
            return ("active-consumer-conflict",
                    f"replacement of {', '.join(affected)} conflicts with active consumer {label}; "
                    "wait for the consumer to finish; no jobs were cancelled")
    return None
