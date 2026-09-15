# gwflow requirements

This document defines the intended first release. The
[architecture](architecture-proposal.md) describes the candidate mechanisms,
the [implementation plan](implementation-plan.md) maps the work to acceptance
criteria, and the [Phase 0 results](phase0-results.md) record the feasibility
evidence. Phase 1 is the next implementation phase.

## Product scope

- gwflow is a topic-agnostic layer on gwf. Existing gwf workflow definitions do
  not need to remain compatible unchanged; gwflow may require additional author
  declarations.
- Slurm is the first supported scheduler. The complete job graph and all
  dependencies are known before initial submission. Runtime discovery inside a
  planned job is allowed, but runtime creation of new scheduler jobs is not.
- The submission command submits the necessary graph and exits. Execution
  continues without a persistent controller or added orchestration jobs.
- Definitions are distributed as importable Python packages and may be
  installed editably during development. gwflow is a separate package,
  distributed through Conda with gwf as a dependency.
- Reuse is scoped to one explicitly selected project/reuse directory. Global,
  cross-project, and multi-user caches are outside the first release.

## Definitions and versioning

- Main pipelines, subpipelines, and software packages have separate version
  identities. A main-pipeline version records its composition, including the
  selected subpipeline versions.
- Published subpipeline versions are immutable. A version fixes commands,
  computational parameter values, retained-output declarations, and each
  target's image or environment declaration. Changing any of these requires a
  new version.
- Named input files, finite lists of files, and necessary small data values can
  vary between bindings of the same subpipeline version. Computational settings
  do not vary as caller overrides of a published version.
- Operational resources such as memory, walltime, partition, and account may
  change without a version bump when they do not change the computation.
- Main-pipeline version changes alone do not invalidate unchanged bound
  subpipelines. Relevant upstream computation-identity changes invalidate their
  consumers even when newly produced bytes happen to match.

## Subpipeline boundaries

- A subpipeline is the unit of completed reuse, but its internal gwf targets
  remain separate jobs with their own resources and dependencies.
- Subpipelines may have multiple independent terminal targets. Authors do not
  add artificial final compute targets merely to join them.
- A downstream subpipeline may consume only the producer's declared retained
  outputs. Exposing a previously internal file requires a new producer version.
- A downstream subpipeline waits for the whole required producer to succeed,
  even when the particular retained output it reads appears earlier.
- Retained outputs can appear gradually while work is incomplete. The first
  release does not promise atomic visibility of the whole result set to
  external readers.

## Completion, reuse, and freshness

- Completion requires all required work to succeed, all retained outputs to
  exist, and durable project-local evidence to support that conclusion after
  scheduler history expires.
- A command that creates outputs and then fails does not establish completion.
  Required output checks and evidence publication are part of the compute job's
  successful execution boundary.
- A completed subpipeline remains reusable after its disposable internal files
  are removed. Missing cleaned intermediates alone do not invalidate that
  completed boundary.
- Input-file checking follows gwf's existence and timestamp semantics. gwflow
  does not checksum input contents, compare size/mtime snapshots for equality,
  or otherwise impose stricter freshness checks.
- Freshness follows the actual target dependency graph. Inputs and outputs from
  independent branches are not pooled into a subpipeline-wide timestamp test.
- Available queued, running, failed, and cancelled scheduler states retain
  gwf's precedence. Durable evidence supports the fallback after history
  expires; it does not override a known scheduler state.
- Missing required outputs or evidence triggers automatic recovery. gwflow does
  not infer prior success solely from surviving result files. Missing external
  input data without a producer remains an ordinary input error.
- Incomplete subpipelines resume through ordinary gwf target scheduling and
  preserve successful current internal work where possible. Recovery after
  cleanup regenerates any physical prerequisites an executing command needs.
- Every execution attempt is fenced from earlier attempts so that late evidence
  cannot certify a replacement run.
- Each bound computation has one current result slot. Rebuilding after an input
  change need not retain historical copies of the previous result files.

## Submission and cleanup

- Later submissions reuse equivalent queued or running work and attach new
  downstream work to the tracked jobs instead of duplicating it.
- Concurrent submission commands coordinate project metadata updates.
  Interrupted submissions reconcile jobs that the scheduler may already have
  accepted before resubmitting.
- Replacing a failed upstream computation repairs obsolete dependencies for
  owned queued consumers without cancelling unrelated or running jobs.
- Cleanup is explicit. It removes only eligible, inactive, gwflow-managed
  temporary work and preserves retained outputs, required completion evidence,
  provenance, and external paths.

## Target environments

- Apptainer images are declared per target; there is no subpipeline-wide image
  default or inheritance. Different targets in one subpipeline may use separate
  cutadapt, bwa, and samtools images.
- Targets may use existing local SIF files or published registry references.
  gwflow prepares and caches missing published images before job submission,
  including OCI-to-SIF conversion when required.
- gwflow does not solve Conda environments, build custom image recipes, or add
  image-preparation jobs. A target without an image uses the prepared host
  environment.

## File-freshness baseline

For a target with inputs and outputs, ordinary gwf freshness is based on real
file existence and the strict comparison between the newest input mtime and the
oldest output mtime. Equal timestamps remain current. A byte edit that preserves
timestamps is not guaranteed to be detected. A changed input mtime matters only
in relation to the relevant outputs. Outputless targets keep gwf's always-run
behavior.

Required evidence is an additional condition for subpipeline reuse, but its own
mtime is not a computational input or output. For completed-boundary evaluation,
valid evidence may supply the historical mtime of a cleaned internal output.
Actual recovery always uses real files for anything a command will read.

## Acceptance scenarios

1. **Reuse after cleanup.** A subpipeline completes, its disposable internal
   files are removed, and a later submission reuses it while retained outputs
   remain valid and inputs remain fresh.
2. **Fork and join.** A completes before B and C, B and C can run concurrently,
   and D waits for both after the submission command has exited.
3. **Partial composition change.** Changing only reporting in a main-pipeline
   version preserves reusable mapping and analysis. Changing mapping identity
   invalidates dependent analysis even if the new mapping bytes match.
4. **New downstream file requirement.** A consumer cannot reach into cleaned
   upstream work. A revised upstream version explicitly exposes the file as a
   retained output.
5. **Failure after output creation.** A target creates retained files and exits
   nonzero. The subpipeline remains incomplete and cannot be reused as complete.
6. **Equivalent active work.** A later submission attaches consumers to an
   equivalent queued or running computation instead of submitting a duplicate.
7. **Software upgrade.** Compatible gwflow or gwf changes preserve reusable
   evidence; incompatible evidence triggers regeneration under a documented
   compatibility policy.
8. **Timestamp-preserving input edit.** Input bytes change without becoming
   newer than the relevant outputs. No content scan is added to detect the edit.
9. **Independent-branch freshness.** With `x=9 -> a=10` and `y=11 -> b=12`,
   both branches remain current; the unrelated `11 > 10` comparison causes no
   rerun.
10. **Computational parameter change.** Changing a filtering threshold requires
    a new subpipeline version and invalidates affected consumers.
11. **Partial retry.** Eight targets succeed and a ninth fails. A later
    submission keeps current successful work and schedules what recovery needs.
12. **Parallel endings.** A producer has two independent terminal targets. A
    consumer of the faster branch still waits for the whole producer without an
    artificial join job.
13. **Expired scheduler history.** Retained outputs and durable evidence allow
    reuse evaluation after scheduler history has expired.
14. **Gradual output visibility.** One terminal output appears before another.
    The visible partial set neither establishes reuse nor releases consumers.
15. **Explicit cleanup.** Cleanup preserves results and evidence and excludes
    active or incomplete work.
16. **Scheduler status precedence.** Current files and an in-job success record
    do not override a known failed or cancelled scheduler state. Active jobs
    retain active-job behavior.
17. **No historical snapshots.** Rebuilding changed inputs may replace the
    current result slot without preserving the previous payload bytes.
18. **Missing completion metadata.** Missing required evidence schedules
    affected work automatically without fabricating success or duplicating
    equivalent active jobs.
19. **Multiple images.** Cutadapt, bwa, and samtools targets in one subpipeline
    run their complete commands in independently declared images.
20. **Image acquisition.** Local SIF and published registry references work
    without worker-side fetching, a preparation job, or environment creation.

The acceptance matrix in the [implementation plan](implementation-plan.md)
assigns stable identifiers and implementation phases to these behaviors.
Consequential trade-offs are recorded in [ADR 0001](adr/0001-static-job-graph.md),
[ADR 0002](adr/0002-retained-output-boundaries.md),
[ADR 0003](adr/0003-gwf-compatible-input-freshness.md), and
[ADR 0004](adr/0004-subpipeline-reuse-across-main-versions.md).
