# Scheduler observations and sequential attachment

Native `run --dry-run` and `run` query the same maintained gwf/Slurm adapter for
every retained job association, including work absent from the current composition.
They never infer missing associations from receipts. No query is needed when
trustworthy tracking contains no job IDs. `plan` remains pure and does not query
the scheduler, even if accounting is unavailable.

Preview brackets all observations with the command-guard and submission-generation
checks. It creates no files, attempts, or jobs. A submission overlapping its
observations invalidates its decisions. Submission acquires the guard and
reevaluates; preview is not a reservation.

| Observed gwf state | Target behavior |
| --- | --- |
| `submitted`, `running` | Attach to the tracked ID, even if completion evidence is absent. |
| `failed`, `cancelled` | Require execution; a success receipt cannot override scheduler knowledge. |
| `completed` | Evaluate required evidence and freshness; scheduler completion alone is insufficient. |
| `unknown` after successful empty queries | Evaluate required evidence and freshness, without assuming success. |

The adapter uses gwf 2.1.1's accounting and current-queue state mapping, with
current queue observations taking precedence. A failed query, malformed reply,
or unrecognized returned state is `scheduler-query-failed`, not expired history.
Native commands return exit 1, JSON `outcome: error` and no computation decisions,
plus a readable stderr diagnostic. A submission-side query failure happens
before a new intent or attempt is prepared; the command releases its own guard.

## Existing producer IDs and retained history

A later sequential composition can add a new consumer to equivalent active
producers. It submits only the new work and uses the producers' actual tracked
terminal IDs as `afterok` prerequisites, preserving whole-producer completion.
It neither duplicates active jobs nor changes computational file inputs.

Completed reusable targets contribute no new jobs. Their independent associations
remain tracked, including associations absent from the requested composition.
Per-attempt invocation records, selections' history, receipts, diagnostic metadata,
and stdout/stderr logs are not expired or rewritten by pruning. Required evidence
and the live filesystem still decide whether a completed target is reusable.

Project-wide replacement protection against already-active consumers is a separate
Phase 2 slice (#40). This interface does not cancel jobs, repair obsolete queued
dependencies, or provide automatic interruption reconciliation.

## Portable demo

```sh
conda run --prefix .venv python -m examples.scheduler_attachment_demo
```

The demo submits four producer jobs, then adds one consumer depending on the
original terminal IDs. A native preview reports attachments. Actual installed
gwf and local Bash execute all five payloads after submission; subsequent native
commands reuse the results both with completed status and controlled expired
history. The report verifies five retained associations and unchanged attempt
history after pruning the absent consumer and all completed execution work.
Finally an injected accounting-service failure produces exit 1 and no decisions.

Only external Slurm executables are replaced by private fixtures. No live Slurm
jobs are submitted; the demo prints `real_slurm_jobs_submitted: 0` and its project
path. Optional `--project /path/to/new-directory` chooses a fresh root. Live
qualification remains opt-in under #42; portable results do not qualify site
accounting, scheduler, or shared-filesystem behavior.
