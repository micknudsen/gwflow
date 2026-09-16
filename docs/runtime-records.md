# Phase 2 runtime declaration records

Phase 2 stores execution authority separately from schema-1 planning manifests.
This document specifies the first maintained retained record: an execution
computation declaration. It is not a success receipt and cannot establish
subpipeline completion.

## Location and revision

For computation `<digest>`, the record is
`.gwflow/runtime/v1/computations/<first-two-hex>/<digest>/manifest.json` under
the selected project. Publication is atomic within that directory. The envelope
is `execution-computation`, record revision 1, the revision-1 descriptor and
identity, and `computational_declaration`.

The declaration contains the published definition name/version, interfaces and
computational parameters, targets, declared environments, and graph relations.
It deliberately excludes operational resources and main/package/software
provenance. Object maps, target order, and graph-relation order are canonical;
target names and command strings are literal. Thus a whitespace-only command
change or target rename is a visible change, but map/relationship ordering and
resource/provenance changes are not. Records are compared only when the bound
computation identity already agrees; different bindings are not a definition
registry.

## Other required records

All maintained execution records use `record_revision: 1`. A **current attempt**
selects one attempt token for an identity/target. A **success receipt** names
that same attempt and records output paths with observed `mtime_ns` values. A
**job association** names that attempt and one scheduler job ID. An
**attempt diagnostic** names retained stdout/stderr paths but is not completion
authority. A **submission intent** lists identity/target/attempt entries and
scheduler-visible ownership tokens before scheduler acceptance. The later
executor/adapter tickets publish and consume these records in their required
ordering; this schema ticket neither claims job success nor writes them from a
planning command.

`run --dry-run` reads an existing record and exits 2 on a changed declaration.
Submission publishes records in a later Phase 2 slice. A missing record is not a
version violation and remains an ordinary runtime-recovery condition.

## Demo

Export a detached record without writing project state:

```sh
conda run --prefix .venv python -m gwflow plan examples.one_file:main \
  --project /tmp/gwflow-record-demo --bindings '{"source":"reads.txt"}' \
  --format execution-manifests
```

The public `execution_manifest` and `validate_execution_manifest` helpers make
this maintained record available to the later submission integration. Their
writer is intentionally not a CLI command: only successful durable submission
may publish runtime state.

`examples.runtime_records:main` and `:changed` demonstrate that a saved
definition followed by a literal whitespace-only command edit under the same
published subpipeline version is rejected by `run --dry-run`.
