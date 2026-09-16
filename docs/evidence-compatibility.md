# Runtime evidence compatibility

Execution records intentionally exclude gwflow and gwf release provenance from
completion authority. Compatible software upgrades therefore do not invalidate
otherwise valid retained evidence.

## Recovery versus uncertainty

An absent, corrupt, or unsupported indispensable computation manifest,
current-attempt selection, or selected success receipt is never interpreted as
success. With independent trustworthy job associations it enters ordinary
recovery, preserving unaffected successful targets and known active work. Lost
logs, superseded receipts, and other optional history do not require rerunning
completed work. A valid historical declaration that visibly disagrees with the
same bound computation is still a definition violation, not evidence loss.

Missing, corrupt, or unsupported authoritative job tracking is different. It
cannot exclude an untracked active job, so runtime preview returns exit 1,
`outcome: "blocked"`, reason `untrustworthy-job-tracking`, and an empty
`computations` list. It emits a readable stderr diagnostic and writes nothing.
No receipt, retained file, or receipt timestamp can restore an association.
Manual recovery must establish quiescence and reconcile authority (#39); this
ticket does not clear uncertainty automatically.

## Authoritative association format

`.gwflow/runtime/v1/tracking.json` has the exact envelope:

```json
{"kind":"job-tracking","tracking_revision":1,"associations":{}}
```

Each association map key is `<64-hex-computation-identity>:<literal-target-name>`.
Its value is a validated revision-1 `job-association` record, containing the same
identity and target, the latest accepted attempt, and its scheduler job ID. One
job cannot be associated with multiple targets. Boolean or unsupported revisions,
wrong record kinds, mismatched map keys, ambiguous JSON, and invalid UTF-8 are
rejected. Writers use the shared durable-publication protocol.

This independent authority is not a substitute for current-attempt completion
selection: a valid receipt still needs its own matching selection. Conversely,
missing or malformed selection does not erase the independent job association.
A valid selection naming a different, untracked attempt is an uncertainty block.
Retained target directories without associations also block, including targets
outside the requested composition. Merely omitting reused targets from a new
executable graph must not remove their tracking. Replacing an association is a
submission operation after active-job checks, never a reader's repair action.

A fresh project without retained runtime state needs no tracking file. Once
retained runtime state exists, absent tracking cannot mean "no jobs". An explicit
valid empty association set represents an initialized project with no accepted
jobs; it cannot cover retained attempt history. An unrecognized retained runtime
namespace also blocks rather than silently ignoring possible authority from a
newer implementation. Preview never initializes tracking; pure `plan` ignores
runtime state entirely.

The static scheduler adapter and scheduler-query handling are delivered by
#35/#36. Portable fixtures here explicitly supply synthetic associations and
expired-history observations; they are not claims that real Slurm jobs ran.
Known active/failed observations continue to take precedence through the
maintained evaluator. Query failure must not be converted to expired history.

## Runnable portable demo

```sh
conda run --prefix .venv python -m examples.evidence_compatibility_demo
```

The demo writes controlled fixtures, then invokes the product preview command
for each case: compatible release provenance reuses all targets; an unsupported
selected receipt recovers only `b` and its dependent `e`; a corrupt manifest
recovers the full graph; missing, corrupt, and unsupported tracking each block
with no decisions. The printed report includes the simulated prior and installed
software versions. An optional `--project /path/to/new-directory` selects a new
directory; an existing directory is refused. No scheduler jobs are submitted.
