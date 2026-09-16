# Phase 2 runtime declaration records

Phase 2 stores execution authority separately from schema-1 planning manifests.
An execution-computation declaration preserves a published definition for one
bound computation. It is not a success receipt and cannot establish subpipeline
completion. The other revisioned records have separate roles below.

## Location and revision

For computation `<digest>`, the record is
`.gwflow/runtime/v1/computations/<first-two-hex>/<digest>/manifest.json` under
the selected project. The envelope
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

JSON types remain significant: changing a computational parameter from `true`
to `1`, or from `1` to `1.0`, changes the declaration. File input/output list
order remains literal; only mapping and graph-relationship order is normalized.

Readers check envelope/revision types, the typed identity descriptor, interfaces
and parameters, and graph consistency. The pure graph compiler checks target
membership, dependency edges, environments, ownership, output kinds, and
entry/terminal membership. Project-scoped reads also check the selected identity
and owned paths. Detached validation infers the project from owned output slots;
an outputless detached declaration's resolved local-image path can only be
checked against its project when the project is supplied. None of this inspects
the filesystem during `plan`.

Malformed records (including duplicate JSON fields, non-finite numbers, invalid
UTF-8, and a manifest filed under the wrong computation) are not evidence of a
published-definition violation. Manifest readers report unusable evidence;
automatic-recovery and tracking-uncertainty policy belong to the runtime
evaluator and compatibility boundary (#33/#43).

## Durable publication

Both record writers use the same publication protocol: validate first, create
the containing directories, synchronize ancestor directory entries, write a
temporary file in the destination directory, flush and synchronize its contents,
atomically replace the destination, then synchronize its containing directory.
Any write, rename, or synchronization failure propagates to the caller. Temporary
files are removed after a handled failure. A post-replacement synchronization
failure can leave a visible new record, but is never acknowledged as a durable
commit; callers must not proceed as though publication succeeded.

This protocol requests POSIX host-filesystem durability. Portable fault tests
verify ordering and failure propagation, not survival of a particular storage
system's power loss. Site/shared-filesystem qualification remains opt-in in #42.

## Other required records

All maintained execution records use integer `record_revision: 1`. A **current attempt**
selects one attempt token for an identity/target. A **success receipt** names
that same attempt and records output paths with observed `mtime_ns` values. A
**job association** names that attempt and one scheduler job ID. An
**attempt diagnostic** names retained stdout/stderr paths but is not completion
authority. A **submission intent** lists identity/target/attempt entries and
scheduler-visible ownership tokens before scheduler acceptance. The later
executor/adapter tickets publish and consume these records in their required
ordering; this schema ticket neither claims job success nor writes them from a
planning command. Receipt output observations contain distinct normalized
absolute paths and integer nanosecond timestamps (not booleans); diagnostic
paths are also normalized and absolute. An empty receipt output list represents
an outputless target, not a reason to suppress its always-run behavior.

Selections are under `targets/<target>/current.json` in the computation's
directory; receipts and diagnostics are under
`targets/<target>/attempts/<attempt>/`. A simple ASCII component matching
`[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}` stays literal. Other target names and attempt
tokens use `~` followed by their UTF-8 SHA-256 digest as a single component.
The record itself retains the original literal name/token. This reserved prefix
keeps encoded and literal components disjoint, contains separators/traversal,
and supports long or Unicode names without changing computation identities.

`run --dry-run` reads an existing record and exits 2 on a changed declaration.
Submission publishes records in a later Phase 2 slice. A missing record is not a
version violation and remains an ordinary runtime-recovery condition.

## Demo

Run the complete portable demo (no payload execution or scheduler submission):

```sh
conda run --prefix .venv python -m examples.runtime_records_demo
```

It creates and reports a unique temporary directory, writes/reads declaration
records, and invokes the real product command. Expected case exits, in order:
`unchanged: 0`, `command-whitespace: 2`, `target-rename: 2`,
`resources-and-provenance: 0`, `different-binding: 0`, and
`boolean-to-integer-parameter: 2`. It also round-trips the five other record
schemas in a separate `schema-roundtrips/` directory. Those fixtures are not
execution evidence and are never placed at the authority paths. The demo exits
nonzero if a case disagrees with its expected result and retains its directory
for inspection. To choose a directory, pass `--project /path/to/new-directory`;
an existing directory is refused.

Separately, export a detached record without writing project state:

```sh
conda run --prefix .venv python -m gwflow plan examples.one_file:main \
  --project /tmp/gwflow-record-demo --bindings '{"source":"reads.txt"}' \
  --format execution-manifests
```

The public `execution_manifest` and `validate_execution_manifest` helpers make
this maintained record available to submission integration. The writer is not
a separate production CLI command. Submission must publish the required intent
and attempt records before scheduler acceptance, and publish tracking before
releasing its guard; preview never writes them. The demo's explicit fixture
setup does not claim that submission or successful execution occurred.
