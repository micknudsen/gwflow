# Phase 0 results

The bounded feasibility gates are complete on the selected Linux, Slurm,
Apptainer, and BeeGFS environment. These are historical Phase 0 findings.
Phase 1 planning is now implemented and complete; Phase 2 execution is specified
in [issue #29](https://github.com/micknudsen/gwflow/issues/29) and awaits implementation. The [architecture](architecture-proposal.md) and
[implementation plan](implementation-plan.md) remain the baseline.

## Environment and reproducibility

The isolated Linux development environment uses the published
`gwforg::gwf=2.1.1` Conda package (`py_0`) on x86-64, with Python 3.11.16 and
pytest 9.1.1. The Conda solve/install, Python imports, and `gwf --help`
succeeded. This establishes one development configuration, not a supported
release matrix or a gwflow package build.

Run the probes with `conda run --prefix .venv python -m pytest -q experiments/phase0`; [setup and scope](../experiments/phase0/README.md) are documented alongside the scripts. Raw verification output and exact machine/package provenance are retained privately rather than published in this repository.

The complete portable suite result is **93 passed, exit status 0**. Passing
counts describe the asserted cases; they are not counts of
passed architecture gates. Real Slurm 25.11.6, Apptainer 1.5.3, and BeeGFS
observations and their raw machine/job records are retained privately.

| Probe group | Passed cases |
| --- | ---: |
| Freshness/evidence recovery with real gwf scheduling | 54 |
| Actual local execution to receipts, reuse, and recovery | 6 |
| Graph/submission/tracking with a simulated service | 10 |
| Local process coordination and simulated durable acceptance | 6 |
| Actual gwf/Bash runtime with fake Apptainer and host wrapper | 17 |

## Local findings

### E1 — target-level freshness after cleanup

The [freshness/recovery probe](../experiments/phase0/test_freshness_recovery.py) calls the installed gwf scheduler without changing its implementation. Chains, forks, joins, and independent branches are evaluated before cleanup and again with recorded output mtimes substituted only for absent disposable outputs. It checks six input timestamp positions per graph, live timestamps for remaining intermediates, equal/future timestamps, and timestamp-preserving input byte changes.

The local cases support the proposed evaluator: independent branches stay current, relevant changes propagate, and removed intermediates need not invalidate an otherwise complete subpipeline. Missing retained results are never virtualized. Once recovery is needed, real-file scheduling regenerates removed prerequisites.

Required evidence validity is tested through a disposable adapter to gwf's early `should_run` hook, using a non-hash sentinel for unavailable evidence. Computational input/output declarations remain unchanged, so receipt timestamps cannot introduce extra freshness comparisons. Outputless targets remain always-run. This demonstrates an integration seam; the precise production adapter API is not established by the fixture.

### E2 — evidence, status, and failure

The same probe exercises missing/corrupt/incompatible manifests, missing/corrupt/wrong-attempt target receipts, missing results, partial recovery, late old-attempt records, and optional summaries. Missing indispensable evidence schedules regeneration even when data files look current; an optional summary can be derived from intact target evidence.

All six gwf backend states are exercised. Known active jobs are retained despite unfinished files/evidence; failed/cancelled states override otherwise valid receipts; completed/unknown states fall through to the agreed freshness/evidence checks. A raised query error is not treated as absent history. These are supplied status values and query errors, not observations from a live Slurm service.

The [execution probe](../experiments/phase0/test_target_execution.py) reproduces stock gwf's successful exit despite a missing declared output. A disposable outer host wrapper then verifies outputs, writes and fsyncs a receipt, atomically replaces it, and fsyncs its parent directory. Payload failure, missing output, and a real receipt replacement error produce nonzero exits. This supports keeping the evidence obligation inside the existing compute job; the live probes below establish Slurm exit/accounting and downstream blocking.

The [execution-to-reuse integration](../experiments/phase0/test_execution_reuse.py) connects actual gwf/Bash payloads to timestamp receipts and the boundary evaluator. Its initial outputs and assumed receipts are deleted before execution. A successful chain remains reusable after intermediate cleanup; lost results or evidence cause actual prerequisite rebuilding. Payload, output-check, and receipt-publication failures prevent boundary certification while preserving successful physical prerequisites. The live retry probe below supplements the fixture's in-memory attempt expectations with persisted attempt fencing.

### E3 — graph submission and whole-subpipeline ordering

The [graph probe](../experiments/phase0/test_graph_submission.py) uses real gwf graph construction, scheduling, submission preparation, and tracking persistence with an in-memory backend service. Explicit control edges make a downstream entry depend on both upstream terminal jobs without adding computational file inputs or extra targets. Graph consistency and cycles are checked explicitly. A new consumer retains the IDs of already-active producers, and a rebuilt pruned graph uses actual retained files.

The simulated queue can progress after the submitting backend closes, with no further planning call. The live graphs below confirm the same ordering through Slurm.

### E4 — coordination and the retry gap

The graph probe reproduces a generic stock gwf limitation: if a failed upstream is replaced while its old consumer remains queued, the consumer retains the obsolete dependency ID. The selected cluster instead sets `DependencyParameters=kill_invalid_depend`, so an invalid consumer is automatically cancelled and normal gwf retry replaces it. A separate live controller-filtered cancellation probe covers the fallback safety mechanism.

Six local process/lock/crash probes pass: overlapping invocations submit equivalent work once, both acceptance crash windows recover, partial submission preserves prior mappings, foreign ownership is excluded, and concurrent readers see complete atomically replaced records. Reconciliation against an actual scheduler, token availability after interrupted submission, and cancellation restricted to still-queued owned jobs required the live cluster validation summarized below.

Official Slurm documentation describes state and ownership filters for `scancel`, and `--ctld` can send a filtered request to the controller. This supports controller-side pending-state filtering with explicit owned job IDs instead of a client status-check followed by unconditional cancellation. [Official scancel documentation](https://slurm.schedmd.com/scancel.html)

### E5 — target-specific executor integration

The execution probe serializes real gwf targets and launches `python -m gwf.exec` with a deliberately fake Apptainer executable. Separate targets receive cutadapt/bwa/samtools image references independently. Real local Bash execution covers the entire specification, working directory, flags, environment forwarding, stdout/stderr, subprocess failures, and gwf's default `set -e` without `pipefail` behavior.

The fake records arguments and executes on the host: it does not open SIF images, isolate commands, bind paths, fetch registry content, or manage a cache. The live probes below cover those obligations. The stock executor forwards local paths and registry URIs without the proposed preparation/preflight behavior, confirming that image preparation remains gwflow work.

## Live server findings and gate disposition

The selected setup used a project path visible across the tested compute nodes.
The complete command, job-ID, timestamp, artifact, and machine record is
retained privately; the portable implementation findings are summarized here.

| Gate | Live disposition |
| --- | --- |
| E1/E2 integration | **Supported.** Real jobs propagated required-output exit 72, receipt-publication exit 73, and post-receipt exit 74; every `afterok` consumer was cancelled. A running attempt-2 retry rejected a persisted late attempt-1 receipt, published attempt-2 evidence, and released its consumer. |
| E3 | **Supported.** Complete fork/join graphs continued after submission exit. A consumer waited for both producer terminals, a failed late terminal blocked it, retry retained successful work, and a later submission attached a consumer to two actual active job IDs. |
| E4 | **Supported with a filesystem-specific refinement.** Scheduler reconciliation, real overlap, partial-graph interruption, filtered owned-PENDING cancellation, and atomic metadata publication passed. BeeGFS cross-node `flock` and `lockf` failed; atomic directory creation passed and is the selected lock basis. Slurm's `kill_invalid_depend` automatically handles the ordinary failed-upstream consumer on this cluster. |
| E5 | **Supported with an image preflight refinement.** Distinct Ubuntu/Debian targets, repeated-image and host targets, mounts, cwd, environment, shell behavior, output/evidence publication, registry-to-SIF preparation, digest identity, cache hit/recovery/concurrency, interrupted acquisition, final-set expansion, missing-local failure, and networkless local-SIF compute execution passed. Images must provide literal `/bin/bash`; preparation must preflight it. |

### Refined mechanisms

- Use atomic directory creation plus owner/lease metadata, stale recovery, and publication fencing on the selected BeeGFS filesystem. Do not use advisory `flock`/`lockf` there.
- Serialize option-looking executor values as `--option=value`, and preflight the exact `/bin/bash` path required by gwf 2.1.1 before submission.
- On this Slurm configuration, automatic invalid-dependency cancellation followed by ordinary gwf retry is the primary queued-consumer repair. Keep controller-side owned-PENDING filtering as the demonstrated fallback for a supported configuration where obsolete consumers can remain queued.

These are implementation refinements within the required behavior; they add no
controller, orchestration/finalizer/preparation job, content scan, or weakened
scheduler semantics.  Phase 0 is complete for the selected configuration.
Phase 1 has since implemented production definitions, planning schemas, identity,
and graph inspection. Runtime evidence schemas, maintained execution adapters,
durable coordination, real alignment-tool images, and cleanup remain work for
Phases 2–4. See the [current preparation record](phase2-planning.md).
