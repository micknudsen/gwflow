# Phase 2 preparation

This records the completed execution, retained-evidence, and reuse interview.
The project owner confirmed shared understanding on 2026-09-16, and the accepted
parent specification is [GitHub issue #29](https://github.com/micknudsen/gwflow/issues/29).
This is a decision record, not an implemented runtime guide. Implementation
tracer-bullet tickets belong under that parent according to the repository's
[issue-tracker rules](agents/issue-tracker.md). No implementation tickets were
created as part of publishing the parent specification.

## Current implementation and evidence

Phase 1 is complete: parent issue #3 and all twelve implementation tickets are
closed. The package implements definitions, computation identity, composition,
static graph validation, declared target environments, planning manifests, and
pure plan explanations. `plan` does not observe runtime state or publish project
metadata. `run`, runtime previews, execution receipts, and reuse evaluation are
not yet product features.

Phase 0 demonstrated the candidate runtime mechanisms on the selected
configuration. Its probes are disposable experiments, not runtime schemas or
maintained product adapters. Its historical portable result is 93 passes; the
reported completed Phase 1 baseline is 222 passing tests. A preparation rerun
on 2026-09-16 inside the agent sandbox produced 215 passes and seven 20-second
subprocess timeouts in the execution probes. The same seven tests passed outside
the sandbox in 10.98 seconds using
`conda run --prefix .venv python -m pytest -q experiments/phase0/test_execution_reuse.py experiments/phase0/test_target_execution.py::test_stock_runtime_does_not_check_declared_outputs`.
The discrepancy was not reproduced outside the sandbox; its precise cause has
not been established. This was a focused rerun, not a new full-suite pass.
These observations do not change the accepted
semantics or retroactively change the historical Phase 0 result.

## Settled requirements

- Subpipeline completion requires all required work to succeed, real retained
  outputs, and durable completion evidence. Consumers wait for the whole
  producer without a completion job or persistent controller.
- Freshness preserves gwf's target-level existence/timestamp comparisons and
  dependency propagation. Receipt timestamps are not computational timestamps.
  Historical timestamps may substitute only for absent disposable outputs when
  evaluating whole-subpipeline reuse.
- If a boundary cannot be reused, ordinary recovery uses its full internal graph
  and real prerequisite files. Missing indispensable evidence causes automatic
  recovery; surviving result files alone do not establish success.
- Known scheduler states retain precedence. Query failures are not expired
  history. Active work is not duplicated because its outputs or evidence are
  unfinished. Outputless required targets remain always-run.
- Execution attempts are fenced, independently of computation identity. A late
  old record cannot certify a replacement attempt. There is one current result
  slot, without historical payload snapshots.
- Phase 1 identity, retained-output interfaces, and planning schemas remain the
  contracts in ADRs 0005–0008. Containers remain part of the first release, with
  implementation staged in Phase 3.

See [requirements](design.md), [architecture](architecture-proposal.md), and
[Phase 0 evidence](phase0-results.md) for the full baseline.

## Implementation facts constraining Phase 2

Inspection of the installed gwf 2.1.1 source during preparation found:

- `gwf/backends/base.py`, `TrackingBackend`, loads tracking independently of
  the current graph. Pruning targets does not inherently require deleting their
  job mappings. Submission updates an in-memory mapping after the scheduler
  returns; `close()` writes the JSON directly. This leaves the accepted-before-
  persistence interruption window and does not itself provide atomic tracking
  publication.
- Closing that backend rewrites tracking even if nothing was submitted. Stock
  `gwf/cli.py` also creates metadata/log directories. A strictly read-only
  preview must avoid these incidental writes.
- `gwf/conf.py` defaults `clean_logs` to true, and `gwf/plugins/run.py` removes
  logs for targets absent from the graph. `gwf/backends/slurm.py` uses target-name
  log paths rather than attempt-specific paths. The maintained adapter must
  preserve logs across pruning and retries to satisfy Q4.
- Stock tracking contains target names and job IDs, not gwflow attempt ownership.
  It cannot by itself establish ownership or safe reconciliation.
- Phase 1 manifests retain bound commands and paths. Those may legitimately
  differ across datasets; comparing complete compiled targets across different
  bindings would reject valid definitions. The within-plan Python builder-object
  comparison is not a portable historical record. See `gwflow/planner.py` and
  `gwflow/manifests.py` for the implemented contracts.

These are source observations and integration constraints, not newly accepted
runtime protocols.

The decisions below remain accepted even where an earlier round lists a then-open
follow-up; later rounds resolve those entries.

## Accepted interview decisions — round 1

The project owner accepted Q1–Q5 on 2026-09-16.

| Question | Accepted decision | Still to specify |
| --- | --- | --- |
| Q1: operational promise | Phase 2 is a controlled development milestone for sequential submissions with intact tracking, including preservation of and attachment to known active jobs. Uncertain submission state cannot cause blind resubmission. Full concurrency and automatic interruption reconciliation remain Phase 4. | Q6 selects the guard; the operator recovery procedure and partial-submission handling remain open. |
| Q2: runtime inspection | Add `run` and `run --dry-run` backed by a shared runtime evaluator. Keep `plan` pure. Preview reports observed decisions without publishing attempts or submitting jobs; actual submission reevaluates. Broader project status remains Phase 4. | Q7 selects strictly read-only JSON with computation/target decisions; error/exit details remain open. |
| Q3: saved-definition consistency | Compare visible computational definitions against saved predecessors and reject mismatches under the same published version. Resource overrides and provenance-only differences remain allowed. No hidden-code inspection. | Q8 selects per-bound-computation comparison; normalization remains open. See [ADR 0009](adr/0009-persisted-definition-consistency.md). |
| Q4: attempt history | Retain per-attempt metadata and stdout/stderr logs, including failed and superseded attempts, without automatic expiration in Phase 2. Diagnostic history is separate from current evidence eligible for reuse. | Q10 selects required versus diagnostic records; fields, storage, and compatibility details remain open. |
| Q5: qualification | Require maintained portable E1–E3 regressions plus a fresh opt-in live Slurm demonstration through the product interface covering whole-producer barriers, failure blocking, partial retry, and cleanup-tolerant reuse. Use controlled scheduler observations for expired-history fallback. | Concrete reproducible scenarios and their allocation to implementation tickets. |

Documentation is updated with each resolved decision and implementation finding.
Accepted-but-unimplemented behavior must remain labeled as such. Glossary
changes belong in `CONTEXT.md` only when terminology is resolved; durable
consequential trade-offs belong in ADRs. No new domain term was needed in round 1.

## Accepted interview decisions — round 2

The project owner accepted Q6–Q10 on 2026-09-16.

| Question | Accepted decision | Still to specify |
| --- | --- | --- |
| Q6: command guard | Use an exclusive atomic-directory command guard and a durable marker established before submission can begin. Uncertain interruption blocks further submission until an operator reconciles jobs and tracking. No automatic stale takeover in Phase 2. Release after durable tracking publication, not compute-job completion. | Operator recovery procedure, partial-submission behavior, and missing/corrupt authoritative tracking. |
| Q7: runtime preview | Emit JSON with stable decision/reason codes at computation and target level, relevant job IDs, and supporting evidence for reuse, execution, or active-job attachment. Strictly read-only: create/update no directories, manifests, attempts, or tracking files. Preview is an observation, not a reservation; submission reevaluates. | Error/exit contract and behavior while a guard or uncertainty marker prevents a coherent assessment. |
| Q8: historical comparison scope | Compare computational declarations only for repeated uses of the same bound computation. Exclude operational resources and provenance-only differences. No project-wide definition registry; cross-dataset immutability remains an author contract. | Exact computational field comparison and normalization. |
| Q9: environment staging | Phase 2 execution is host-only. Reject any image-declaring plan before submitting any jobs, including mixed plans; never substitute host execution silently. Pure planning still inspects image declarations. Image execution remains Phase 3 and first-release scope. | Routine preflight implementation and diagnostics. |
| Q10: evidence authority | Require a computation manifest, durable per-target current-attempt selection, and the selected attempt's success receipt, published after command success and output checks. Evaluate with scheduler status and freshness. Logs, superseded receipts, and derived summaries are diagnostic; their loss alone does not trigger recomputation. | Concrete runtime schema, publication protocol, and job-association authority. See [ADR 0010](adr/0010-current-attempt-evidence.md). |

`CONTEXT.md` now defines **Current attempt** without prescribing a storage
mechanism. ADR 0009 records Q8's scope; ADR 0010 records Q10's separation of
current authority from retained history. These decisions are not implemented.

## Additional interruption evidence

The Phase 0 local coordination fixture publishes an attempt token before fake
scheduler acceptance. Before-acceptance and accepted-before-persistence crashes
leave identical local state: a known attempt without a saved job ID. Its partial
submission case includes saved jobs, an accepted-but-unsaved job, and unvisited
targets. The fake service exposes owner/target/attempt tags perfectly; this is
not evidence that one empty live scheduler query proves nonacceptance.

Stock gwf Slurm submission uses the target name as the scheduler job name, with
no separate gwflow ownership/attempt tag supplied by the resource interface.
Stock status queries retrieve IDs and states, not the ownership associations
needed for operator reconciliation. Phase 2 must deliberately preserve enough
submission intent and scheduler-visible identification for its manual recovery
procedure. Live Phase 0 tagging/reconciliation was demonstrated, but those
site-bound programs are private.

Missing required completion evidence with trustworthy tracking follows automatic
recovery and active-job precedence. Missing authoritative job associations or
uncertain acceptance cannot be interpreted as expired history or repaired from
success receipts alone: those receipts cannot exclude an untracked newer job.
Q11 below selects the manual recovery contract.

## Accepted interview decisions — round 3

The project owner accepted Q11–Q14 on 2026-09-16.

| Question | Accepted decision |
| --- | --- |
| Q11: interrupted-submission recovery | Require quiescence of the affected submission. Persist enough intent and scheduler-visible identification to locate its jobs. The operator confirms none remain queued/running, restores verifiable job associations, and invalidates unverifiable completion evidence before explicitly clearing the block. Unknown ownership or remaining activity keeps the block. Never manufacture success from surviving outputs. Live recovery preserving affected active jobs remains Phase 4. |
| Q12: active-consumer protection | Check affected owned computations and consumers across the project using retained graphs and tracking, including active consumers outside the requested composition. Reject conflicting replacement before submission. Permit unrelated work and attachment to equivalent active jobs. Unknown ownership/activity blocks; Phase 2 does not cancel conflicting jobs. |
| Q13: comparison strictness | Compare command strings literally; whitespace changes and internal target renames require a new version. Normalize representation-only ordering of mappings and graph relations; exclude operational resources and provenance. No shell-equivalence analysis. Missing/malformed saved evidence triggers recovery when tracking permits, not an inferred version violation. |
| Q14: runtime outcome contract | JSON stdout and readable stderr diagnostics. Exit 0 for a valid preview or successful submission plus durable tracking publication, including all-reused requests, never as a claim that compute jobs finished. Exit 2 for invalid definitions/bindings, unsupported images, or visible version violations. Exit 1 for runtime/query failures, blocked/uncertain state, or partial submission failure; report known accepted job IDs. A held guard or interruption marker produces a blocked preview without definitive execution/reuse decisions. Pure planning remains available. |

## Recovery boundaries

These distinctions reconcile the accepted decisions; they are not new choices:

- **Ordinary evidence recovery:** missing or incompatible completion evidence
  requests regeneration only under trustworthy job associations and the normal
  scheduler precedence. Preserve known active attempts rather than duplicating
  them. Q11 does not impose manual recovery or quiescence on this ordinary path.
- **Uncertain job associations:** missing, corrupt, or incompatible authoritative
  tracking, or an unresolved acceptance window, blocks submission for Q11's
  manual procedure. A successful query with expired history for a known tracked
  job is different and follows the accepted evidence/freshness fallback.
- **Active consumers:** Q12 protects files needed by already-active affected
  consumers, including those outside the requested composition. It must still
  permit a producer and its new downstream jobs to be submitted together and
  new consumers to attach to equivalent active producers under whole-producer
  scheduler dependencies.
- **Compatibility:** ordinary gwflow/gwf release changes do not by themselves
  invalidate identity or compatible evidence. Unsupported required-evidence
  revisions cause regeneration when tracking permits; unsupported authoritative
  job-association records cannot be treated as an empty scheduler history.

## Design tree disposition

| Branch | Disposition |
| --- | --- |
| Operational scope, command guard, and interruption recovery | Settled by Q1, Q6, Q11. |
| Existing active consumers and equivalent-job attachment | Settled by baseline E3 semantics and Q12. |
| Pure planning, runtime preview, and command outcomes | Settled by Q2, Q7, Q14. |
| Historical definition comparison | Settled by Q3, Q8, Q13; ADR 0009. |
| Attempt history and indispensable evidence | Settled by Q4, Q10 and baseline fencing/status/freshness semantics; ADR 0010. |
| Host/image staging | Settled by Q9; images remain required in Phase 3 and the first release. |
| Product qualification | Settled by Q5 and E1–E3 acceptance behavior. |

The product frontier is closed and shared understanding is confirmed. The
accepted specification is published as [#29](https://github.com/micknudsen/gwflow/issues/29)
with the canonical `ready-for-agent` label: triage is complete, and the parent
provides context for separate implementation tickets. Phase 2 runtime
implementation has not started. Documentation updates remain local on
`docs/phase2-preparation` until delivered through a pull request.

## Specification presentation and testing seams

On 2026-09-16, the existing parent issue was updated using the requested
`to-spec` format: Problem Statement, Solution, User Stories, Implementation
Decisions, Testing Decisions, Out of Scope, and Further Notes. It now contains
80 user stories and retains the same 20 acceptance criteria. This synthesis
does not reopen Q1–Q14 or create a duplicate phase specification.

The primary testing seam is the public command boundary for pure planning,
runtime preview, and submission. Preserve existing public Python planning and
manifest tests. Portable runtime tests use real gwf/Bash execution with a
test-only scheduler substitute at the adapter boundary; narrow fault injection
supports failure and interruption scenarios. The live Slurm gate uses the same
product commands. Harness facilities are not new public execution backends,
and the Phase 0 fixture internals are not production API requirements.

## Implementation-ticket choices and constraints

The following are explicit technical work, not silently selected product
contracts. Each affected ticket must record and test its concrete choice before
implementation depends on it; any conflict with the accepted behavior returns
for a product decision.

- Runtime record fields, filenames, supported schema/interpretation revisions,
  and compatibility diagnostics. Preserve schema-1 planning manifests and their
  unevaluated-runtime meaning; do not silently turn exported plans into proof.
- Current-attempt and job-association storage, stable logical target identities,
  scheduler-visible ownership/attempt tags, and reconciliation instructions.
  An absent saved job ID never proves nonacceptance. Manual recovery must be
  executable from documented records and scheduler queries on the supported
  deployment, not from private Phase 0 scripts.
- Atomic publication and ordering of attempt selection, receipts, submission
  intent, and job tracking. Fence before work can modify outputs; make output
  checks and durable receipt publication part of the compute job's successful
  exit. Never hold a command guard for compute-job lifetimes.
- The concrete gwf 2.1.1 adapter/executor seam, resource mapping, graph mutation
  and pruning strategy, and filesystem view for completed-boundary evaluation.
  Preserve target-level freshness, gwf shell/exit behavior, active-job IDs, and
  attempt logs; do not inherit stock log cleanup or dry-run tracking writes.
- JSON envelope fields and stable decision/reason code enumeration covering the
  accepted outcomes. Preserve blocked/partial/error diagnostics and the strict
  read-only preview; never promise a reserved plan.
- Exact computational comparison projection and canonical mapping/graph
  ordering. Preserve literal commands and meaningful binding-list order; avoid
  rejecting provenance/resource changes or legitimate cross-dataset differences.
- Maintained portable fixtures, opt-in live commands, and ticket dependencies.
  Tests own the accepted behavior through product seams; manual intermediate
  removal in disposable fixtures demonstrates cleanup-tolerant reuse without
  claiming a product cleanup command. Each implementation PR delivers one
  independently testable tracer bullet.

Phase 3 still owns image preparation/execution. Phase 4 still owns full
coordination, automatic interrupted-submission reconciliation, automatic obsolete
queued-consumer repair, broader status tooling, and product cleanup. Phase 5
still owns distribution and full release qualification. The narrow Phase 2 guard,
intent records, and manual recovery do not claim those later-phase capabilities.
