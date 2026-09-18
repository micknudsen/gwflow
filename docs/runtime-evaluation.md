# Phase 2 runtime evaluation

`run --dry-run` reads the retained runtime declaration, current-attempt
selection, and selected attempt receipt without creating or updating state. It
returns target and computation decisions for `reuse`, `execute`, or `attach`.
A mixed computation with any newly required execution is `execute`, even if
some of its targets attach to existing jobs. Target decisions and job IDs retain
that distinction. Only an entirely reusable boundary is `reuse`.

The evaluator preserves target-level freshness: real outputs and intermediates
use live mtimes; only an absent disposable output can use the selected receipt's
recorded `mtime_ns` during a candidate completed-boundary evaluation. Every
required target must have eligible selected evidence, all retained outputs must
be real files, and **every target must evaluate reusable** before historical
timestamps can be accepted. If even one target is stale, failed, active,
outputless, or missing evidence, discard all virtual timestamps and reevaluate
the full internal graph against real files. This regenerates physical
prerequisites while preserving successful current work where those files remain.

Receipt file mtimes never enter computation freshness. Compare only a target's
actual newest input with its oldest output using strict `>`: equal timestamps,
future-dated outputs, and byte changes preserving mtimes retain gwf's behavior.
Do not pool timestamps across branches or inspect file contents.

Missing producerless external inputs are checked across the whole planned graph
before considering output existence or active status. A produced file that does
not exist yet is not a producerless input. Input errors return exit 1 with a JSON
`error` outcome, an empty computation list, and a readable stderr diagnostic.
Filesystem observation errors also fail without definitive execution proposals.

Scheduler observations are supplied at an explicit adapter seam. `submitted`
and `running` targets attach rather than duplicate work, while `failed` and
`cancelled` take precedence over receipts. Active/recovery decisions propagate
to internal dependents. Computations are evaluated in dependency order; a
pending whole producer propagates to a consumer's entry targets without adding
the producer's unconsumed files to freshness comparisons. A successfully queried
`unknown`/expired job state permits evidence/freshness fallback, not assumed
success. Query errors must never be converted to `unknown`.

Native preview and submission share the maintained gwf/Slurm observation adapter;
see [scheduler observations](scheduler-observation.md). Missing or incompatible
authoritative tracking blocks both commands, as described in
[evidence compatibility](evidence-compatibility.md). Completion receipts never
reconstruct missing job associations. Direct evaluator fixtures may still supply
explicit controlled statuses; native commands always query retained job IDs.

## Preview reasons and evidence

Revision-1 preview reasons are stable machine-readable codes; `message` is for
humans. Each target and computation includes `evidence` and `job_ids` arrays.

| Code | Meaning |
| --- | --- |
| `no-runtime-state` | No usable saved execution manifest. |
| `current-evidence` | This target's selected evidence and freshness permit reuse. |
| `complete-current-boundary` | All required internal work is reusable. |
| `missing-output-or-evidence` | A declared output is absent or is not a file. |
| `missing-required-evidence` | The current selection/receipt is unusable or mismatched. |
| `newer-input` | A consumed input is strictly newer than the oldest output. |
| `required-prerequisite` | An internal dependency needs execution/attachment or a produced input is absent. |
| `whole-producer-pending` | An entry target waits for a nonreusable whole producer. |
| `outputless-always-run` | Required outputless work must execute. |
| `submitted`, `running`, `failed`, `cancelled` | Scheduler precedence determines the target decision. |
| `active-target` | The computation has active work and needs no new execution. |
| `missing-external-input` | Producerless external input is absent; runtime error. |
| `filesystem-error`, `invalid-scheduler-observation`, `scheduler-query-failed` | Runtime observation failed. |
| `active-consumer-conflict` | Replacement conflicts with an already-active consumer; blocked without decisions. |
| `active-consumer-state-unknown` | An external active target's graph cannot establish safe replacement; blocked without decisions. |

Evidence entries identify an execution manifest, current-attempt selection, or
selected success receipt by `kind` and `path` (with `attempt` for the latter two).
File observations use `input-file`, `output-file`, or `historical-output` with
`path` and `mtime_ns`; `null` means absent/not a required regular output file.
Historical entries occur only on accepted reusable boundaries. Scheduler
observations include `status` and the adapter-supplied `job_ids`. These are
explanations, not a persisted reservation or a new completion-authority record.

Both native preview and submission apply [active-consumer protection](active-consumers.md)
across retained project state before allowing replacement, including consumers
outside the requested composition.

## Demo

Run the complete portable fixture demo:

```sh
conda run --prefix .venv python -m examples.runtime_evaluation
```

It creates a unique temporary project and explicitly seeds controlled evidence
fixtures; private scheduler executables report successfully expired history.
It executes no payload or scheduler job and claims no live execution.
Every observed case invokes the maintained `run --dry-run` command. It reports
and checks, in order: completed reuse; only `a,b,e` stale; reuse after intermediate
removal; all five targets regenerated after indispensable receipt loss following
cleanup; only `e` in a partial retry with real files; and missing external input
as exit 1. It fails if any expectation differs and keeps the directory for
inspection. `--project /path/to/new-directory` selects a new directory and
refuses to overwrite an existing one.
