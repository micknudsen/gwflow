# Completion evidence

This document explains the role and expected contents of durable completion
evidence. The [architecture](architecture-proposal.md) supplies the broader
design, and [Phase 0](phase0-results.md) validates the core failure and attempt
windows on the selected configuration. Phase 1 provides the [planning manifest schema](manifest-schema.md). Runtime
evidence schemas and maintained execution integration remain Phase 2 work.

## Purpose

Once internal intermediates have been intentionally removed, their absence cannot tell gwflow whether the subpipeline never finished or finished and was cleaned. Retained metadata links the declared result files to the particular subpipeline definition, inputs, and required internal work that produced them. It enables a candidate reuse check that consults current scheduler status and retained outputs without treating intentionally deleted intermediates as missing unfinished work.

Output files alone do not establish that all required work succeeded. Conversely, a record does not override an active, failed, or cancelled job, stale inputs, changed upstream computation, or missing retained outputs. The [gwf status research](research-gwf-status.md) documents the precedence that the integration must preserve.

## Proposed information

| Information | Example or purpose |
| --- | --- |
| Definition identity | Subpipeline name and published version, plus the relevant compatibility/version metadata. Computational parameter values are already part of that definition. |
| Named input bindings | File references and small data values, such as a reference file and dataset identifier; upstream result references where applicable. |
| Retained-output interface | Which named result files are expected to remain after cleanup. |
| Required internal work | Target identities and their dependency relationships, so a partial branch is not mistaken for whole-subpipeline completion. |
| Execution evidence | Attempt/job identifiers and evidence that the corresponding command and required checks reached their success point. Old attempt evidence must not certify a newer failed attempt. |
| Scheduler observations | The status observed for a tracked job and when it was observed, if retained for provenance. A saved observation is not automatically the job's current state or a permanent override of gwf's unknown-status fallback. |
| Freshness information | Phase 0 demonstrated per-target output timestamps and dependency relationships for evaluating the agreed rules after internal outputs are deleted. The production record format remains unresolved; input-content checksums and strict input-metadata-snapshot equality are not introduced. |

Phase 2 has selected three distinct required records: the computation manifest,
a durable per-target record selecting the current attempt, and that attempt's
success receipt. These records are evaluated alongside scheduler status and
freshness; no Boolean completion flag is the sole authority. The directory,
exact formats, and compatibility details remain design choices. See
[ADR 0010](adr/0010-current-attempt-evidence.md).

## How it could be produced

The submission command can record the expected plan and job IDs. Existing compute jobs could record their own command outcomes, with required output checks and durable evidence publication succeeding before the job exits successfully. Failure of either must fail the job so Slurm's `afterok` dependencies remain blocked. Later submission, status, or cleanup commands can evaluate the records together with gwf's backend states and current result/freshness checks. No additional orchestration job or persistent controller is implied by this proposal.

These are separate types of information: a saved plan says what was intended; a command record says what that command reached; a scheduler observation says what gwf observed at a particular time; subpipeline completion is a derived conclusion. In particular, command success must not override a known Slurm failure. Phase 0 demonstrated disposable evidence and graph-integration mechanisms, including live failure and attempt-fencing behavior. A maintained product protocol and adapter are not yet implemented.

## Concrete example

Suppose `mapping` version `1.2` uses named input files and a dataset identifier, runs alignment and sorting, and retains an alignment file and its index. The alignment/sorting intermediates are later cleaned.

On a new submission, gwflow would use retained metadata to identify the same definition/input bindings and the work required to produce that result. It would still consult relevant tracked-job states, verify the retained files, and apply the agreed freshness/provenance checks. If those checks permit reuse, it could omit the internal targets that would otherwise rerun merely because their intermediate files are gone. This is the intended behavior, not proof that the proposed mechanism already works.

## Accepted Phase 2 history policy

Retain per-attempt metadata and stdout/stderr logs through Phase 2 without
automatic expiration, including attempts superseded by retries. Keep diagnostic
history separate from the current attempt evidence eligible for reuse. This
does not retain historical result payloads or make an old receipt eligible for a
replacement attempt. Exact record fields, storage, and compatibility rules remain
to be settled in [Phase 2 preparation](phase2-planning.md).

Logs, superseded receipts, and derived summaries are diagnostic records; their
loss alone does not trigger recomputation. The selected current-attempt record
and its required receipt are indispensable evidence. A surviving historical
receipt cannot nominate itself as current when that selection record is lost.

## Lost or missing records

Normal gwflow cleanup preserves this metadata. Lost records include accidental deletion, corruption, or copying only the visible result files to a project location without the metadata that explains their provenance and prior completion.

A missing success record for a target that has not finished is ordinary incomplete work, not necessarily lost metadata. Normal internal recovery still applies. If a result's necessary evidence is irrecoverably missing, gwflow cannot safely invent a success record merely because files survived.

Missing required evidence or retained outputs causes automatic recovery or recomputation rather than an interactive recovery stop. Required evidence existence is a concrete rerun condition even when ordinary result files still look current. Metadata outputs or an equivalent validity predicate are candidate mechanisms, but receipt timestamps must be excluded from computational freshness comparisons. Preserve successful current internal work with usable evidence where possible; if cleaned prerequisites must be regenerated, their producers rerun too.

Known queued/running equivalent targets retain gwf's active-job precedence and must not be duplicated simply because their outputs/records are not yet present. The original exception also remains: missing disposable intermediates do not cause a rerun of an otherwise reusable completed subpipeline. Missing producerless external inputs are normal input errors, not data that gwflow can invent.

Lost authoritative job associations and uncertain submission acceptance are not
ordinary evidence loss. Receipts cannot establish the absence of an untracked
newer job. Phase 2 blocks submission pending manual reconciliation, which
requires quiescence of the affected submission, restoration of verifiable job
associations, and invalidation of unverifiable evidence. Unknown ownership or
activity keeps the block. Ordinary missing-evidence recovery remains automatic
when job tracking is trustworthy and scheduler observations permit it.

An optional derived status summary can be reconstructed from complete underlying required evidence; it is not itself a required completion record. Partial retries and virtual freshness after cleanup were exercised by the Phase 0 gates in the [implementation plan](implementation-plan.md). The planning schema is implemented; runtime evidence schemas and maintained execution integration remain Phase 2 work.
