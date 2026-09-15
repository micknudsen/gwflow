# gwflow feasibility and implementation plan

Execution evidence and remaining gates: [Phase 0 results](phase0-results.md).

Phase 0 is complete on the selected Slurm, Apptainer, and BeeGFS configuration.
Phase 1 is the next implementation phase. This plan accompanies the
[architecture](architecture-proposal.md) and [requirements](design.md).

The first deliverable was evidence that the difficult integration points work
under the agreed constraints. Source inspection supported the candidates but
did not establish that their combination worked. Phase 0 supplied that evidence
and refined the mechanisms; changes to agreed behavior still require renewed
agreement.

## Phase 0 — bounded feasibility experiments

**Complete for the selected configuration.** See the
[gate disposition](phase0-results.md#live-server-findings-and-gate-disposition).
The selected BeeGFS lock is a fenced atomic-directory lease rather than
`flock`/`lockf`; container preparation preflights gwf 2.1.1's literal
`/bin/bash`; and this Slurm deployment's `kill_invalid_depend` behavior plus
normal retry handles the ordinary failed-dependency replacement case.

The phase used small disposable graphs and files, starting with controlled file timestamps and a fake scheduler against the pinned gwf release and then exercising the integration on a disposable Slurm allocation with Apptainer. Local simulations cannot establish real scheduler, container, or shared-filesystem behavior. Exact machine and scheduler evidence is retained privately; the public result summary records the observations and limitations needed for implementation.

### E1 — cleanup-tolerant freshness

Compare the candidate boundary evaluator with ordinary gwf target decisions before cleanup; repeat with disposable internal outputs removed and their historical output timestamps supplied by valid target evidence. Include chains, forks, joins, and independent branches `x=9 → a=10` and `y=11 → b=12`.

Vary relevant input mtimes, equal timestamps, future-dated outputs, missing retained outputs, and an input byte edit that preserves its timestamp. Include an internal file that remains present but has changed mtime. Check that required receipt existence is enforced without allowing receipt mtimes to affect computational freshness. An outputless target must retain gwf's always-run behavior, not become cacheable accidentally.

**Pass:** completed-boundary reuse agrees with the original per-target freshness rules except for the explicitly allowed removal of disposable intermediates and the required-evidence condition. Changed inputs propagate through the correct dependency paths. No content scan, size comparison, input snapshot equality check, or pooled subpipeline timestamp test appears. Actual recovery uses real prerequisite files.

### E2 — evidence loss, failure, and retry

Run a multi-step fixture with one failing target. Inject failure after data output creation, during required output checks or receipt publication, and after receipt publication but before successful job termination. Exercise retry attempt invalidation and a late record from an old attempt. Remove one required receipt, the required manifest, a retained output, and an optional derived status summary in separate cases.

Cover gwf's queued/running/failed/cancelled/completed/unknown states. Distinguish successfully queried expired history from a failed scheduler query. After full completion, remove internal intermediates and repeat the relevant recovery cases.

**Pass:** known scheduler states retain their precedence. Required output-check or receipt-publication failure makes the existing compute job fail and prevents `afterok` consumers from starting. Active jobs are not duplicated because files/evidence are unfinished. Missing indispensable evidence causes automatic recomputation of affected work, with successful current internal work preserved where ordinary recovery permits. A lost optional summary is rebuilt from intact required evidence. Old receipts cannot certify a new failed attempt. No result-file-only reconstruction fabricates execution success. Missing external inputs without producers remain ordinary input errors.

### E3 — complete submission and whole-subpipeline barriers

Use a fork/join graph and an upstream subpipeline with two independent terminal targets. Its downstream consumer reads an output of the faster terminal only. Submit the complete graph once, let the command exit, and observe both success and late-branch failure cases. Repeat with a reusable upstream and with already-active upstream jobs.

**Pass:** downstream execution waits for every required upstream terminal. Slurm dependencies enforce this after submission exits, with no added collector/finalizer job. Scheduler-only control edges preserve the computational file-freshness comparisons. Graph dependency/dependent maps, endpoint selection, producer mappings, and cycle validation remain consistent after pruning and edge insertion.

### E4 — overlapping and interrupted submissions

Run two submission commands against the same project, including a new downstream consumer of an existing active computation. Interrupt submission before `sbatch`, after scheduler acceptance but before job-ID persistence, and partway through a graph. Confirm that stable ownership/attempt tags permit unambiguous reconciliation with the real scheduler.

Then fail an upstream job while its downstream consumer is queued against the old dependency ID. Retry the upstream and exercise the proposed cancellation/resubmission of obsolete gwflow-owned queued consumers, including the race where an inspected job changes state.

**Pass:** commands coordinate without holding a lock for compute-job lifetimes. Equivalent active work is reused, returned job IDs survive subsequent invocations, and ambiguous submissions are reconciled before duplication. Owned obsolete queued consumers acquire the replacement dependency chain. Unrelated or running jobs are not cancelled; uncertain ownership/state causes a clear diagnosis. The selected filesystem must support the demonstrated lock and atomic metadata-publication behavior.

### E5 — target-specific images and preparation

Use the alignment example with separate cutadapt, bwa, and samtools images, or minimal test images with distinguishable commands before the real tool example. Exercise both existing local SIF paths and registry references. Prepare missing registry images before submission, then run with compute-node registry access disabled. Test a cache hit, missing cached image, interrupted acquisition, concurrent requests for one image, and a missing local SIF without a source. Change scheduler state during preparation so the final coordinated evaluation selects additional work; require its image to be prepared before that work is submitted.

Exercise commands with pipelines, redirection, and multiple statements; use external reference paths, symlink destinations, declared helpers, the generated execution script, and writable output directories. Check the container working directory, environment propagation, command exit status, and evidence publication outside the tool image. Include two targets using the same image and a target using the prepared host environment.

**Pass:** every target executes its full command in its own selected image, with usable mounts. There is no subpipeline image inheritance, environment creation, custom recipe build, extra Slurm preparation job, or worker-side registry dependency for prepared images. Cache recovery preserves the recorded image identity. gwf's shell/exit semantics are preserved; author-specified stricter shell handling remains possible.

**Phase 0 exit:** evidence for E1–E5 supports a concrete adapter/executor approach, or a revised proposal explicitly identifies the failed assumptions. Do not proceed as though a failed gate passed. Cluster-dependent checks run in the selected Slurm/Apptainer environment; the portable suite runs in the isolated Linux development environment.

## Phase 1 — definitions, identity, and inspectable plans

Implement the agreed Python definition interfaces, named input/output bindings, static graph validation, and separate main/subpipeline/software versions. Add deterministic descriptor-based paths and required manifest schemas. Keep attempt identities separate from reusable computation identities. Provide plan output explaining graph membership, dependencies, target images, retained outputs, and proposed reuse/recovery reasons.

Validate a main-only version change, a changed upstream definition, changed computational parameter values under a new subpipeline version, multiple datasets, and invalid access to an internal intermediate. Reuse must not depend on input-content hashing. This phase provides an inspectable plan, not a claim of a complete runnable release.

## Phase 2 — execution, retained evidence, and reuse

Implement the demonstrated gwf adapter, target evidence publication, whole-boundary evaluation/pruning, scheduler ordering, and ordinary partial retry. Preserve gwf job tracking and logs when reusable targets disappear from the executable graph. Integrate required-evidence recovery and attempt invalidation.

Turn the meaningful E1–E3 fixtures into maintained behavioral regression checks. Demonstrate completion, cleanup-tolerant reuse, failed-target retry, missing-evidence regeneration, and expired-history fallback end to end. Do not add a completion job or a persistent observer.

## Phase 3 — image-backed target execution

Implement the demonstrated per-target image resolver, registry preparation/cache, mount planning, and executor integration. Record declared/resolved image references as provenance; tie deliberate image changes to the definition-version contract. Keep acquisition separate from Conda environment management and custom image builds.

Retain E5 coverage for the supported runtime. Publish an example alignment subpipeline whose trimming, alignment, and BAM processing select their own images. Container support is required for the initial release, even though implementation is staged.

## Phase 4 — coordinated operation and cleanup

Complete project coordination, submission journaling, ambiguous-submission reconciliation, and obsolete queued-consumer repair established by E4. Add status/recovery explanations and explicit cleanup with a dry-run. Recheck activity and ownership before deleting managed work; preserve retained data, required metadata, provenance, and external symlink destinations.

Demonstrate repeated and simultaneous invocations, interruption recovery, inactive-only cleanup, and rebuilding after in-place input changes without promising historical payload snapshots. Result visibility may be gradual, while downstream execution remains gated by the whole-subpipeline contract.

## Phase 5 — distribution and release qualification

Apply the packaging pattern documented in the
[source findings](source-findings.md#skua-verified-packaging-reference): Python
package layout and version helper, matching conda recipe, import/CLI smoke
checks, and build/test CI. Validate installation with the actual
`gwforg::gwf=2.1.1` artifact and the required dependency channels. Publish
gwflow through the `micknudsen` channel. Test the selected Python matrix before
claiming support.

Exercise installation into a clean Conda environment, imports, CLI help, editable definition-package development, and an installed example's complete plan/run/reuse/cleanup cycle on the supported Slurm setup. Verify compatible metadata reuse across a software update and automatic regeneration when required evidence is incompatible; reject incompatible definition APIs before scheduling with an actionable diagnostic.

Document first-release boundaries, required host tooling/filesystem capabilities, image/reference immutability, recovery behavior, and the distinction between package releases and explicit definition versions. Record the tested gwf, Python, Slurm, and Apptainer versions. Configure tag-triggered publication only as authorized release work; no credentials or publishing have been used in this design phase.

**Release exit:** all applicable acceptance scenarios below have passing evidence on the declared supported configuration. Installation and smoke checks supplement the behavioral tests; they do not replace them.

## Acceptance matrix

“Gate/phase” identifies the planned evidence point. Current Phase 0
dispositions are recorded in [the results](phase0-results.md#live-server-findings-and-gate-disposition).
Candidate protocols remain feasibility mechanisms until implemented in the
corresponding product phase.

| ID | Observable acceptance | Gate/phase |
| --- | --- | --- |
| A01 | A complete static fork/join graph continues after the submission command exits, without an orchestration process or extra orchestration job. | E3; Phase 2 |
| A02 | A completed subpipeline is reused after disposable intermediates are deleted. | E1–E2; Phase 2 |
| A03 | Relevant newer inputs trigger rebuilding; equal timestamps and timestamp-preserving byte edits follow ordinary gwf limits. | E1; Phase 2 |
| A04 | Independent fresh branches remain current; neither pooled timestamps nor receipt timestamps create additional staleness. | E1; Phase 2 |
| A05 | Main-only version changes reuse unchanged computations; changed upstream identity invalidates consumers even if output bytes match. | Phase 1–2 |
| A06 | Computational parameter/image changes belong to a new immutable subpipeline version; input data can vary under that version. | Phase 1, 3 |
| A07 | Downstream definitions can reference only declared retained outputs; adding an output requires a revised upstream interface/version. | Phase 1 |
| A08 | A failed step does not certify completion; ordinary partial retry retains current successful internal work. | E2; Phase 2 |
| A09 | Multiple terminal targets need no artificial join target; a consumer of one branch still waits for the whole producer. | E3; Phase 2 |
| A10 | Known queued/running/failed/cancelled states retain gwf precedence; expired history follows the gwf-compatible fallback with retained evidence. | E2; Phase 2 |
| A11 | Missing required outputs/evidence causes automatic recovery; a missing optional summary is reconstructed from intact proof. | E2; Phase 2 |
| A12 | Recovery after intermediate cleanup regenerates physical prerequisites needed by executing targets. | E1–E2; Phase 2 |
| A13 | A later submission reuses active jobs and attaches new consumers to their actual job IDs. | E3–E4; Phase 4 |
| A14 | Overlapping commands and interrupted submissions preserve tracking and reconcile potentially accepted jobs before resubmitting. | E4; Phase 4 |
| A15 | Replacing a failed upstream repairs obsolete owned queued dependencies without cancelling unrelated or running jobs. | E4; Phase 4 |
| A16 | Explicit cleanup removes only eligible owned temporary work and preserves results, required evidence, provenance, and external paths. | Phase 4 |
| A17 | Partial result sets may become visible; they neither release downstream execution early nor establish complete reuse. | E2–E3; Phase 4 |
| A18 | Rebuilding updated inputs can replace the current result slot without retaining previous result bytes as history. | Phase 4 |
| A19 | Cutadapt, bwa, and samtools targets within one subpipeline use independently declared images with the required paths available. | E5; Phase 3 |
| A20 | Local SIF and published registry sources work, with automatic cache preparation/recovery and no new environments or preparation jobs. | E5; Phase 3 |
| A21 | gwflow installs through Conda with its real gwf dependency; definition packages support normal imports and editable development. | Phase 5 |
| A22 | Compatible software updates preserve reuse; incompatible required evidence triggers regeneration under a documented policy. | Phase 5 |

## Implementation boundary

Phase 0 establishes integration feasibility, not finished product behavior.
Product implementation begins with Phase 1. Broader backends, dynamic graphs,
global caches, environment creation, and other deferred scope are not
prerequisites for this release.
