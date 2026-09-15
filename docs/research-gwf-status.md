# gwf v2.1.1: Slurm status and freshness precedence

This note records verified gwf source behavior and separately labelled design
implications. gwflow must match gwf's handling of Slurm status rather than let
an in-job success record override it. Runtime feasibility results are recorded
separately in [Phase 0](phase0-results.md).

All gwf sources below are pinned to **v2.1.1, commit `f25685a781befe75ef23556110334039b274c066`**. They were read directly from upstream public raw files. This avoids the live website's mixture of a 2.1.1 banner and sections describing 3.0.0 features.

## Two distinct kinds of status

`TrackingBackend.status(target)` reports a `BackendStatus` for the tracked scheduler job. `schedule()` derives a workflow `Status` from dependencies, backend status, and freshness. A workflow `Status.COMPLETED` therefore does not necessarily mean Slurm returned `BackendStatus.COMPLETED`: missing scheduler history can also lead to it after the remaining checks pass. [Tracking backend][tracking], [scheduler][scheduling]

`get_status_map()` uses the same scheduler with a no-op submission function. It reports scheduling decisions without actually submitting work. `submit_workflow()` uses a real submission function, or a logging-only function for a dry run. [Scheduler][scheduling]

## Exact scheduling order

Before the table below, `schedule()` recursively considers the target's dependencies, unless `no_deps=True`. It records a dependency in `submitted_deps` when that dependency's returned workflow status is `SUBMITTED`, `RUNNING`, `SHOULDRUN`, `FAILED`, or `CANCELLED`. It caches each target's scheduling result within the invocation. The first matching row then determines the target's result. [Scheduler][scheduling]

| Order | Condition | Submission action in an ordinary run | Returned workflow status | File/spec freshness evaluated? |
| --- | --- | --- | --- | --- |
| 1 | `force=True` | Submit with `submitted_deps`, even if already active | `SHOULDRUN` | No |
| 2 | Own backend status is `SUBMITTED` | Do not submit again | `SUBMITTED` | No |
| 3 | Own backend status is `RUNNING` | Do not submit again | `RUNNING` | No |
| 4 | Own backend status is `FAILED` | Submit with `submitted_deps` | `FAILED` | No |
| 5 | Own backend status is `CANCELLED` | Submit with `submitted_deps` | `CANCELLED` | No |
| 6 | `submitted_deps` is nonempty | Submit with those dependencies | `SHOULDRUN` | No |
| 7 | `should_run()` returns true | Submit | `SHOULDRUN` | Yes |
| 8 | No preceding condition matched | Do not submit | `COMPLETED` | Yes |

Every row follows the branch order in [`schedule()`][scheduling]. `BackendStatus.COMPLETED` and `BackendStatus.UNKNOWN` have no dedicated branch: both proceed to dependency and freshness checks. Known failure/cancellation overrides current-looking outputs; known submission/running status also takes precedence over missing outputs or a changed script. The `FAILED`/`CANCELLED` values returned during a real run describe the branch taken, even though its submission call has already registered a replacement job as backend `SUBMITTED`. [Scheduler][scheduling], [tracking submission][tracking]

### Freshness order, only when reached

`should_run()` checks the following in order. [Scheduler][scheduling]

1. If the configured spec-hash mechanism reports a changed or previously unrecorded script, return true.
2. If any declared output is missing, return true.
3. Calculate the newest input modification time, defaulting to negative infinity for no inputs.
4. If the target has no outputs, return true.
5. Calculate the oldest output modification time. Return true only if the newest input is **strictly newer** than the oldest output.
6. Otherwise return false.

The filesystem abstraction reads existence and current `st_mtime`; it does not compare contents, size, or a saved input timestamp. Spec hashes are disabled by default. When enabled, they hash only `target.spec`, are keyed by target name, and are updated upon submission rather than completion. Separately, ordinary graph construction rejects an input that is missing and has no producer target; this happens before scheduling and is not bypassed by an active backend status. [Core][core], [defaults][config], [run command][run], [submission][scheduling]

## How Slurm status is obtained

`SlurmOps.get_job_states()` first queries accounting when enabled, then updates the result with `squeue`. Accounting is enabled by default in `create_backend()`. Consequently, an `squeue` entry overrides an accounting entry for the same job ID. [Slurm backend][slurm]

| Source | Exact command arguments in this release | Processing |
| --- | --- | --- |
| Accounting | `sacct --noheader --parsable2 --format=jobid,state --allocations --jobs <comma-separated IDs>` | Tracked IDs are requested in batches of up to 1024. The state is reduced to its first whitespace-delimited token, then translated using the fixed long-state mapping. |
| Queue | `squeue --noheader --format=%i;%t --all` | Returned rows are filtered to tracked IDs; short states are translated to backend states. |

These commands and their merge order are verified in [`SlurmOps`][slurm]. This source check establishes what gwf requests and parses, not any particular cluster's accounting retention or query coverage.

Selected mappings in the inspected release are:

| Slurm state | Backend status |
| --- | --- |
| `PENDING` / `PD`, and short `CF` | `SUBMITTED` |
| `RUNNING` / `R`, short `CG`, and `SUSPENDED` / `S` | `RUNNING` |
| `COMPLETED` / `CD` | `COMPLETED` |
| `FAILED` / `F`, `TIMEOUT` / `TO`, `NODE_FAIL` / `NF`, `OUT_OF_MEMORY` / `OOM`, `BOOT_FAIL` / `BF`, `DEADLINE` / `DL`, `PREEMPTED` / `PR` | `FAILED` |
| `CANCELLED` / `CA` | `CANCELLED` |

This is a selected mapping table, not a claim of complete compatibility with all Slurm states. Unknown short codes use a `defaultdict` fallback to `UNKNOWN`; unknown accounting long-state tokens instead index an ordinary dictionary and can raise `KeyError`. Command lookup/execution errors raise `BackendError`; they are not converted into successfully fetched empty history. In particular, unavailable accounting commands or query failures must not be equated with no returned job record. [State mappings and parsers][slurm], [command wrapper][backend-utils]

## Missing history and tracking persistence

The tracking backend loads `.gwf/slurm-backend-tracked.json` as a target-name-to-job-ID map. If the file is absent, the map is empty. It then fetches statuses for those IDs once when initialized. `status(target)` looks up the target's job ID and returns the corresponding in-memory state, defaulting to `UNKNOWN`. Submission adds the new ID and `SUBMITTED` status to those in-memory maps. Closing the backend saves the ID map, **not the fetched outcome states**. [Tracking backend][tracking]

| Situation | Result of `TrackingBackend.status(target)` |
| --- | --- |
| Target has no stored job ID | `UNKNOWN` |
| Stored job ID has no returned accounting or queue entry | `UNKNOWN` |
| Stored job ID has a returned, mapped completed entry | `COMPLETED` |
| Stored job ID has another returned, mapped state | That backend state |

These cases follow directly from [`status()` and initialization][tracking]. Expired history is one possible reason a stored ID has no returned entry; gwf does not identify the reason. Missing history is neither affirmative success nor affirmative failure. With `UNKNOWN`, no triggering dependencies, and passing spec/file checks, the scheduler can nevertheless return workflow `COMPLETED`. This is baseline gwf behavior, not durable proof of a historical successful Slurm exit. [Tracking][tracking], [scheduler][scheduling]

## Active jobs and dependency reconciliation

During a later submission command, an upstream target reported as queued or running is included in a new downstream target's dependency list. `TrackingBackend.submit()` converts dependency target names to their stored job IDs; Slurm submission uses `--dependency=afterok:<IDs>`. Thus a new downstream job can wait on an already active upstream job. [Scheduler][scheduling], [tracking submission][tracking], [Slurm submission][slurm]

The target's **own** active status wins over dependency-triggered resubmission. For example, if an upstream failed job is resubmitted while an existing downstream job is still reported `SUBMITTED`, the scheduler leaves that downstream job in place; the inspected path contains no cancellation or dependency-rebinding step for it. It must not be assumed that this already queued job automatically follows the replacement upstream job ID. This is a source-based consequence requiring a focused Slurm test if the adapter relies on such recovery. [Branch order][scheduling], [ID replacement on submission][tracking], [submission-only dependency assignment][slurm]

## Implications for gwflow pruning — not a selected implementation

- A durable completion record must not bypass checks of the relevant tracked job states. Otherwise gwflow could omit an internally failed, cancelled, queued, or running target that ordinary gwf would still treat as failed, cancelled, or active. Output existence or an in-job receipt does not override those statuses in the baseline scheduler. [Precedence evidence][scheduling]
- Reuse evaluation must also consider dependency-triggered scheduling before treating freshness as decisive. A subpipeline-level shortcut that checks only final outputs can hide an internal or upstream trigger that target-level gwf would propagate. Preserving cleanup-tolerant reuse while respecting this precedence is an adapter design problem; running unmodified freshness checks over deliberately deleted intermediates does not itself solve it. [Dependency traversal and propagation][scheduling]
- Preserve target/job identity and active dependencies when omitting completed computation. Returning a cached subpipeline result must not erase the mapping needed to observe its jobs or attach downstream work to an existing job. [Tracking and dependency IDs][tracking]
- Distinguish successfully queried missing history from query/parser failure. A fallback that treats every status lookup failure as reusable would diverge from the inspected release. [Slurm parsing][slurm], [command errors][backend-utils]
- Durable success evidence must be reconciled with the baseline's `UNKNOWN` fallback. gwf itself stores no durable final outcome and can accept current-looking outputs after an unobserved historical failure disappears from scheduler queries. Any stricter historical evidence must be explicit rather than presented as exact baseline parity. [Tracking persistence][tracking], [scheduler fallback][scheduling]

The Phase 0 checks cover known failed or cancelled jobs with complete-looking outputs, active jobs with missing outputs, missing history versus query failure, recovery with an already queued dependent, and completion-record pruning that still honors the relevant backend and dependency states.

[scheduling]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/scheduling.py
[tracking]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/base.py
[slurm]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/slurm.py
[backend-utils]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/utils.py
[core]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/core.py
[config]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/conf.py
[run]: https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/plugins/run.py
