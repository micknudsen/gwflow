# Submission guard and interruption intent

Phase 2 serializes each project's mutation/submission section using exclusive
creation of `.gwflow/command-guard/`. Its durably published `owner.json` has
`kind: command-guard-owner`, integer `record_revision: 1`, and a random owner
token. It is a short command guard, not a compute-job lifetime lock or a lease.
There is no automatic stale takeover, timeout, or job cancellation.

Before accepting any jobs, submission durably publishes
`.gwflow/submission.json`: `kind: submission-marker`, integer
`record_revision: 1`, `submission` (the guard owner token), and `intent` (an
absolute path). The intent is a revision-1 `submission-intent` at
`.gwflow/runtime/v1/submissions/<submission>/intent.json`. It lists the complete
intended target set, each with computation identity, literal target name,
fresh attempt token, and scheduler-visible ownership name. Ownership is the
host executor's safe attempt-specific scheduler name, not a completion claim.

The maintained submission module takes a pure plan and a scheduler adapter at
one internal seam. The adapter observes specified job IDs and accepts prepared
jobs. Tests substitute that external scheduler; no public local execution
backend is exposed. Ordinary `run` now uses the maintained
[static gwf/Slurm adapter](slurm-submission.md) and dependency lowering.

## Publication order

1. Acquire and durably identify the exclusive guard.
2. Read trustworthy tracking, query observations, and reevaluate the request
   under the guard. A prior preview is not a reservation.
3. Durably publish the marker and the complete intent before scheduler calls.
4. Publish retained declarations and prepare all fresh attempts, including
   their durable current selections, before the first acceptance call.
5. Accept jobs and durably retain each returned association in per-attempt
   `job.json` and the independent authoritative tracking map. Preserve unrelated,
   reused, and attached associations rather than rebuilding tracking from the
   executable subset.
6. Durably publish final tracking, retire the marker, then release the guard.
   Compute jobs may still be queued or running. Even an all-reused/attached
   request passes the tracking-publication obligation.

Failures after marker publication preserve uncertainty. Before-acceptance,
accepted-before-ID-persistence, and partial-graph interruptions cannot cause an
automatic retry. Returned IDs already known to the command appear in
`accepted_job_ids`, even when their durable publication failed. Acceptance that
did not return an ID remains unknown; neither the missing ID nor an empty query
proves nonacceptance. Durable intent/ownership supports the separate manual
recovery procedure in #39.

## Command results

`run` emits `kind: runtime-submission`, integer `submission_revision: 1`, project,
outcome, and accepted job IDs. Successful submission adds its submission token,
intent path, and the evaluated computation/target decisions. Exit 0 means IDs
and tracking were durably published, not that payloads finished. Failure emits
exit 1 with a stable reason and stderr diagnostic; a partial failure preserves
known accepted IDs and the intent path.

`run --dry-run` checks coordination without creating or modifying any records.
A retained marker gives `submission-uncertain`; a held guard gives
`command-guard-held`. Both produce a blocked outcome and no computation/target
decisions. Even a malformed marker or dangling link preserves the block.
Pure `plan` ignores these records and remains available. Only the command that
still owns a guard may release it; failed or interrupted guards are not silently
reclaimed.

Preview checks coordination again after evaluating. It also compares the set
of retained, uniquely named submission-intent directories before and after its
observations. If a submission completed entirely during evaluation, preview
returns `runtime-observation-changed` with no decisions and asks for a fresh
observation. This uses Phase 2's retained history; it adds no lease, reservation,
automatic retry, or runtime writer. Inputs can still change after observation,
so submission must always reevaluate under its own guard.

## Portable interruption demo

```sh
conda run --prefix .venv python -m examples.submission_guard_demo
```

The demo creates three independent projects and abruptly exits real submission
processes at controlled scheduler-fixture windows. All three retain the complete
five-target intent and block the next product preview. Before acceptance it has
zero fixture jobs/zero tracked IDs; accepted-before-return has one/zero; partial
graph has two/one. The report prints intent paths and block reasons. This is an
external scheduler simulation, not a payload executor or a public submission
backend; no Slurm jobs run. Optional `--project /path/to/new-directory` chooses
the demo root and refuses an existing directory. The retained guards/markers
are intentional artifacts for inspection, not stale state to auto-delete.
