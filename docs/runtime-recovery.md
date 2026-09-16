# Completed-boundary reuse and ordinary recovery

The maintained `run` and `run --dry-run` interfaces combine evidence evaluation,
actual host jobs, and scheduler observations. Recovery needs no separate command
when independent tracking is trustworthy. Preview explains the target decisions;
submission reevaluates and submits only necessary compute jobs.

A successful boundary requires its execution manifest, each target's selected
attempt and successful receipt, real retained outputs, and eligible target-level
freshness/scheduler observations. After disposable intermediates are removed,
the entire completed boundary can reuse with no new jobs. No result file alone
establishes success, and retained outputs are never replaced by virtual timestamps.

Missing, corrupt, or unsupported required evidence triggers ordinary recovery:
an unavailable manifest regenerates the computation; a missing selection or
receipt affects that target and its dependent paths, while successful current
siblings with physical prerequisites remain intact. If recovery follows
intermediate removal, historical timestamps cannot supply inputs to actual
commands: regenerate the required physical prerequisite paths first.

Known failed/cancelled targets retry even when outputs or older receipts exist.
Every retry selects a fresh attempt before payload mutation. A scheduler-pending
dependent remains active until the scheduler reports otherwise; gwflow does not
cancel it or repair its dependency in Phase 2. The portable failed-retry case
explicitly supplies the selected cluster's terminal invalid-dependency observation
before retrying. Site-specific behavior still needs live qualification.

Ordinary freshness remains target-local: newer consumed inputs rebuild affected
paths, but equal timestamps, future outputs, and timestamp-preserving byte edits
do not invent staleness. Receipt file timestamps are not data timestamps. A
main-only version change preserves bound computations; a producer version change
changes consumer identities even when new output bytes are identical. Unrelated
branches retain their identity and reuse opportunity.

Missing per-attempt logs, diagnostic metadata, or superseded receipts does not
invalidate otherwise complete current evidence. The implementation does not
require an optional derived summary. No automatic history expiration, output
cleanup command, or result-file-only evidence reconstruction is introduced.

## Portable demo

```sh
conda run --prefix .venv python -m examples.runtime_recovery_demo
```

The demo uses native commands, installed gwf, real local Bash payloads, and private
external scheduler fixtures. It checks these accepted target sets:

| Case | Newly submitted targets |
| --- | --- |
| Initial execution | `a,b,c,d,e` |
| Disposable intermediates removed | None |
| Required receipt lost after removal | `a,b,c,d,e`, with real regenerated inputs |
| Required selection lost with files present | `b,e` |
| Left input made newer | `a,b,e`; independent right branch remains current |

The final retained file contains the updated left payload and the original right
payload. JSON includes job IDs, accepted target names, the retained result path,
and `real_slurm_jobs_submitted: 0`. `--project /path/to/new-directory` selects a
fresh demo root and refuses existing directories. Exact intermediate files are
removed only from that newly created disposable project; this is fixture setup,
not a Phase 4 cleanup API.

Additional native-command tests cover all three damage modes for each required
record, retained-result loss, post-output-check failure retry, missing optional
diagnostics, and main/upstream-version changes using `examples.recovery_versions`.
No live Slurm jobs are submitted. #42 remains the opt-in qualification gate, and
#40 separately delivers project-wide active-consumer replacement protection.
