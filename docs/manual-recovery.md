# Manual recovery of an uncertain submission

`python -m gwflow recover` inspects durable intent and scheduler ownership while
leaving the submission blocked. `recover --apply resolution.json` explicitly
repairs the affected submission and clears its block only after the conditions
below hold. It never submits, cancels, or executes jobs. Ordinary missing-evidence
recovery with trustworthy tracking continues through `run` automatically.

## Establish ownership and quiescence

1. Stop the interrupted submission command on its original host, and establish
   that it cannot resume or issue another scheduler request. Coordinate with other
   operators. A dead client does not imply its accepted jobs have finished.
2. Read `.gwflow/submission.json` and its retained
   `.gwflow/runtime/v1/submissions/<submission>/intent.json`. The complete intent
   lists each identity, target, attempt, and exact scheduler job name (`ownership`).
   Do not remove the marker or command guard to enable another submission.
3. Choose an accounting start time preceding the entire interrupted submission.
   Query the correct cluster/account as a user who can see all affected jobs:

   ```sh
   python -m gwflow recover --project /absolute/project \
     --since 2026-09-17T00:00:00 > inspection.json
   ```

   This is read-only: JSON includes the full intent, accounting/queue rows, and
   an uncertified resolution template. Exit 0 means inspection succeeded; it does
   not mean recovery is safe. Inspection/query errors return exit 1, a JSON reason,
   and a diagnostic on stderr.

   For direct scheduler inspection, use the comma-separated exact `ownership`
   names from the intent (do not truncate them):

   ```sh
   sacct --noheader --parsable2 --allocations --duplicates \
     --starttime 2026-09-17T00:00:00 --name "$ownership_names" \
     --format=JobIDRaw,JobName%128,State%64
   squeue --noheader --states=all --name "$ownership_names" --format='%i|%j|%T'
   ```

   The command uses these same queries. See Slurm's maintained
   [sacct options](https://slurm.schedmd.com/sacct.html) and
   [squeue formats](https://slurm.schedmd.com/squeue.html). Accounting time range,
   retention, visibility, and cluster selection are operator responsibilities;
   inspection cannot certify that an absent job was never accepted.
4. Wait for every affected accepted job to become terminal, or arrange explicit
   cancellation through the site's normal procedure and then verify termination.
   Pending, running, completing, suspended, unfamiliar states, ambiguous multiple
   IDs for one ownership, and query failures keep recovery blocked. Unrelated
   jobs need not finish. Recovery does not cancel them or inspect unrelated
   ownership names.
5. Establish the complete acceptance inventory. Match positive scheduler job IDs
   to the exact intent ownership. For an intended request with no visible job,
   obtain affirmative evidence of nonacceptance from an exhaustive scheduler
   administrator audit or a submission-client audit establishing that the
   request was never issued/was definitively rejected. Record the audit reference.
   An empty queue/accounting query, missing saved ID, elapsed time, surviving
   output, or success receipt is insufficient. If acceptance or activity remains
   unknown (including expired accounting without an authoritative audit), stop
   and retain the block.

## Certify and apply the resolution

Copy `inspection.json`'s `resolution` object into a separate `resolution.json`.
Set `command_stopped` and `ownership_complete` to true only after completing the
steps above. Fill `evidence` with the operator/site audit reference and coverage
(time interval, cluster/account, visibility, submitter termination). Cover each
intent ownership exactly once using one of these forms:

```json
{
  "submission": "<submission token from inspection>",
  "command_stopped": true,
  "ownership_complete": true,
  "evidence": "Operator/site audit reference and inspection coverage",
  "targets": [
    {"ownership": "<exact accepted attempt name>", "job_id": "12345"},
    {
      "ownership": "<exact never-accepted attempt name>",
      "not_accepted": {
        "source": "scheduler-admin-audit",
        "reference": "Site audit confirming no acceptance for this exact attempt"
      }
    }
  ]
}
```

The alternative nonacceptance source is `submission-client-audit`. These are
explicit operator attestations, not facts inferred by software from the free
text. Do not certify unknown ownership as nonacceptance. If an accepted ID no
longer has verifiable scheduler ownership/state, the command keeps the block.

```sh
python -m gwflow recover --project /absolute/project \
  --since 2026-09-17T00:00:00 --apply resolution.json
```

Apply acquires an exclusive `.gwflow/recovery-guard/`, re-reads intent and tracking,
re-queries accounting and the live queue, and checks complete resolution coverage.
It requires the interrupted command guard's owner to match the submission.
A missing guard is reacquired while the marker still blocks ordinary submission;
a different or unknown owner cannot be taken over. A concurrent recovery blocks.

Before repairing records, apply durably saves the resolution, query observations,
accounting start time, and previous tracking in
`submissions/<submission>/recoveries/<token>.json`. It restores each verified
association in per-attempt `job.json` and authoritative tracking. It preserves an
existing current selection only for the verified attempt with completed scheduler
observations. Missing/malformed/mismatched selections and failed/cancelled attempt
selections cannot establish completion; no receipt or selection is fabricated
from result files.
An operator resolution cannot contradict an already retained accepted job ID,
even when that job has disappeared from scheduler queries.

A certified never-accepted attempt gets an authoritative `unsubmitted-attempt`
record in the tracking map, with revision 1, identity, target, attempt, and the
recovery audit token. Its current selection is removed, fencing any old receipt
and forcing ordinary execution. It has no scheduler job ID and can never support
attachment or completion. This explicit record allows retained attempt history
to remain without inventing a job association. Older readers reject this new
record kind rather than treating it as compatible authority. Logs, old receipts,
invocations, manifests, and payload files are preserved for diagnosis.

Only after tracking is durably published and full retained target coverage is
verified does apply release the interrupted command guard and retire the marker.
It then releases the recovery guard. Exit 0 with `outcome: recovered` includes the
audit path, restored IDs, and invalidated targets. Run the ordinary preview and
submission commands again; they reevaluate current files and scheduler state.
Exit 1 leaves a block and diagnostic; a partially applied repair is safe to retry
with the same resolution after investigating the failure.

## Damaged records and interrupted recovery

The command requires the original complete marker/intent and a schema-valid
independent tracking map. Restore damaged authority from a verified backup or
site audit before applying this procedure; do not replace it with an empty map
or reconstruct it from output/receipt existence. Unrelated missing associations,
unsupported runtime namespaces, or unknown command-guard ownership remain
blocked. The command does not claim to recover ownership when the underlying
intent and authoritative inventory have been lost.

An abruptly killed recovery can leave the empty `.gwflow/recovery-guard/`.
After establishing that **all recovery commands have stopped** and coordinating
exclusive operator access, explicitly remove that empty directory with
`rmdir /absolute/project/.gwflow/recovery-guard` and retry inspection/application.
Keep the submission marker and original command guard. If recovery already
committed and retired both before dying, retiring this empty recovery guard is
its final manual step; inspect the retained audit/tracking first. There is no
timeout, automatic stale takeover, or live recovery preserving affected jobs.

## Portable demonstration

```sh
conda run --prefix .venv python -m examples.manual_recovery_demo
```

The demo loses the second acceptance reply through private Slurm executables,
leaving two accepted jobs but only one saved ID. Native recovery inspection finds
both ownerships and all five intended attempts. Application while jobs are active
fails. The fixture then executes the accepted jobs with installed gwf and real
Bash, certifies its exhaustive acceptance ledger, and applies recovery. Two
associations are restored, three never-accepted selections are invalidated, and
ordinary submission executes just those three targets. The next run reuses all
work. JSON reports the project, audit, and `real_slurm_jobs_submitted: 0`.
`--project /path/to/new-directory` chooses a fresh demo root. No private Phase 0
programs, live Slurm jobs, or public local-execution backend are involved.
