# Planning manifest schema 1

`manifest(plan_result, computation_identity)` returns a detached dictionary.
`validate_manifest(record)` returns `None` for a valid record or raises
`PlanError` with a diagnostic. Both are public `gwflow` exports. The plan command
supports `--format manifests`, writing a JSON array to stdout. No file import
command, automatic persistence, metadata publication, or runtime observation is
performed. Callers may serialize dictionaries with ordinary JSON and validate
them after deserialization.

All fields below are required. Unknown fields are rejected within the schema's
fixed records. Named maps allow user-defined keys. Objects have string keys;
arrays are JSON lists. Interpretation numbers are integers, not booleans.

## Envelope

| Field | Contract |
| --- | --- |
| `kind` | Literal `planned-computation`. |
| `schema_version` | Integer 1. |
| `interpretation` | Exactly `identity: 1`, `definition_api: 1`. |
| `project` | Normalized absolute lexical project root. |
| `computation` | The record below. |
| `provenance` | `main` and `software` records from the plan. |
| `runtime_evaluation` | Literal `not evaluated`. |

Unknown schema or interpretation revisions fail. Compatible software and
package updates do not change schema/identity revisions automatically.

## Computation

| Fields | Contract |
| --- | --- |
| `identity`, `descriptor` | Full lowercase SHA-256 identity matching the canonical revision-1 descriptor. See ADR 0005 and ADR 0007. No attempt, job, payload digest, mtime or size fields. |
| `work_dir`, `result_dir` | Match project, identity, and the current-slot layout. |
| `definition` | Nonempty `name` and `version`; `package` is a map of strings to strings. |
| `input_interface`, `bindings` | Identical sets of named file/files/data inputs, matching typed descriptor bindings. File values are normalized absolute paths; lists preserve order/duplicates; data obeys the bounded JSON contract. |
| `computational_parameters` | Bounded JSON object with names separate from inputs. |
| `output_interface`, `retained_outputs` | Named relative output paths and their corresponding absolute result paths; every retained file has one target producer. |
| `targets` | Nonempty target array, described below. |
| `computational_edges` | Internal `producer`, `consumer`, `kind` records; `file` edges also have `path`. Explicit edges have no path. |
| `entry_targets`, `terminal_targets`, `internal_outputs` | Distinct string arrays consistent with the graph and retained interface. |
| `connections` | Records containing `input`, upstream `producer` identity, retained `output` name and absolute `path` in that producer's result slot. Match output-reference descriptors. |
| `whole_producer_dependencies` | Sorted distinct upstream computation identities matching connections. |
| `completion_obligations` | Each has `producer`, condition `whole-subpipeline completion`, nonempty distinct `required_targets` and `terminal_targets`, and evaluation `not evaluated`. Terminals are required members. |
| `occurrences` | Sorted distinct names selecting this computation in main provenance. |

Target fields are exactly `name`, `computation`, `command`, `inputs`, `outputs`,
`resources`, `environment`, `always_run`, `dependencies`, and `output_kinds`.
Names/commands are nonempty strings; membership must match computation identity.
Inputs/outputs/dependencies are string arrays. Resources use the operational
resource contract. Environment is one of:

- `{"kind":"host","declaration":null}`
- `{"kind":"local-sif","declaration":"relative/or/absolute.sif","path":"/normalized/path.sif"}`
- `{"kind":"registry","declaration":"docker://registry/image:tag"}` (also `oras://`)

`always_run` is a Boolean matching whether the target has no outputs.
`output_kinds` maps each output path to `retained` or `internal`. The validator
reconstructs the computational graph without executing commands and checks
cycles, ownership, declarations, producer links, dependencies and endpoints.

Main provenance contains `name`, `version`, a string-valued `package` map and
`occurrences` mapping names to `{identity, definition}`. Software provenance has
nonempty `gwflow` and either nonempty `gwf` or null if not installed. Package
releases may differ across occurrences without changing computation identity.

## Interpretation limits

Schema validation establishes structural and internal consistency, not the
truth of a declaration or execution success. A standalone consumer record
contains the declared upstream membership but cannot independently verify the
upstream builder or its whole graph; planning constructs those obligations from
the complete validated composition. Records are not signed attestations.
Required runtime evidence, retained-output validity, freshness and scheduler
state remain unevaluated. Saving a manifest cannot make outputless work cacheable
or certify subpipeline completion.

## Demo

```sh
conda run --prefix .venv python -m gwflow plan examples.manifests:main --project /tmp/gwflow-demo --format manifests
conda run --prefix .venv python -m examples.manifests
```

The export covers file lists, small data, fixed parameters, parallel terminals,
local/registry/host environments, resources and a retained-output consumer.
The second command validates both records and demonstrates rejection of schema
999. To validate a caller-saved JSON array, use `json.load` then call
`validate_manifest` on each member; the regression suite tests these round trips
and malformed/missing fields through this public boundary.
