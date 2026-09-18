# Protecting active consumers

Before replacing existing work, `run --dry-run` and `run` check every retained
job association in the selected project. A queued or running consumer protects
its producers even when that consumer is absent from the requested composition.
Submission repeats the check while holding the command guard, before publishing
an intent, selecting attempts, or submitting jobs. Preview remains read-only.

An affected consumer produces exit 1, JSON `outcome: blocked`, reason
`active-consumer-conflict`, and no computation decisions. The diagnostic names
the replacement and the active consumer's computation, target, job ID, and
scheduler state. A blocked submission accepts no jobs and releases its command
guard without changing retained runtime records or payloads. No jobs are
cancelled; retry after the affected consumers finish or an operator independently
resolves their scheduler state.

The check uses retained execution manifests and authoritative tracking:

- A whole-producer dependency protects the producer boundary while any target
  in that consumer is active, including recovery of an unconsumed producer branch.
- Within a computation, replacement of an active target's ancestors is blocked.
  Independent internal branches can recover. Declared input paths are also
  checked against the outputs selected for execution.
- Only already-active jobs block replacement. A producer and new consumers may
  be submitted together, and new consumers may attach to equivalent active
  producers using their existing IDs. Unrelated work remains allowed.
- Completed, failed, cancelled, or successfully expired consumer jobs do not
  impose an active-consumer block. Query failures retain their runtime-error
  behavior; missing authoritative tracking retains its uncertainty block.

For active work included in the request, the evaluated plan supplies the graph
after the normal definition-consistency check. Missing completion evidence
therefore still permits ordinary active attachment. For external active work,
an absent, corrupt, incompatible, or mismatched retained graph prevents proving
that replacement of an existing computation is unrelated. This returns
`active-consumer-state-unknown`; restore the execution manifest or wait for the
active work to finish. Brand-new result slots and requests that only attach or
reuse work remain possible. This check neither reconstructs execution success
nor makes logs or superseded receipts indispensable evidence.

## Portable demonstration

```sh
conda run --prefix .venv python -m examples.active_consumer_demo
```

The demo executes four producer jobs using real gwf/Bash payloads, then submits
a consumer. It removes the unconsumed producer terminal's receipt as controlled
test damage. Both a producer-only preview and submission are blocked, preserving
all remaining project files and scheduler jobs. An unrelated request still
submits. After the original consumer completes, the producer's missing evidence
is recovered by one new job.

The JSON report includes the conflicting job ID, diagnostic, unchanged-state
check, unrelated and replacement IDs, and `real_slurm_jobs_submitted: 0`.
Optional `--project /path/to/new-directory` retains the fixture at a chosen new
location. The external Slurm executables are private substitutes; no live jobs
are submitted. Live qualification remains a separate opt-in gate.
