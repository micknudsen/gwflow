# gwflow

gwflow is an experimental Python layer for composing independently versioned
subpipelines on top of [gwf](https://gwf.app/). It is designed to preserve
completed subpipeline results after disposable intermediates are cleaned while
retaining gwf-compatible freshness and scheduler behaviour.

Phase 0 feasibility work and the Phase 1 planning foundation are implemented:
definition interfaces, deterministic identity, static graph validation, versioned
planning manifests, and an inspectable plan command. See the [implementation plan](docs/implementation-plan.md)
and [architecture](docs/architecture-proposal.md).

## Development status

The Python package and pure plan command are usable for inspecting intended work.
Phase 2 now includes host compute-job execution, retained evidence evaluation,
guarded static gwf/Slurm submission, scheduler-aware previews and active-work
attachment, and portable end-to-end submission demos. Complete recovery/protection coverage and live
qualification remain in progress. Image acquisition and cleanup are later phases.
A plan or manifest never certifies completion.
The accepted [Phase 2 specification](https://github.com/micknudsen/gwflow/issues/29)
and [preparation record](docs/phase2-planning.md) define the next milestone;
its remaining tickets track the unfinished runtime milestone.

## Preview Phase 2 runtime work

`run --dry-run` is a strictly read-only runtime preview. It emits versioned JSON
on stdout and diagnostics on stderr; it does not create project state, attempts,
tracking, or jobs. It evaluates retained evidence, file freshness, and successfully
queried scheduler observations, and blocks held command guards or uncertainty.
Preview is an observation, not a submission reservation. Pure `plan` does not
query files or the scheduler.

```sh
gwflow_preview_project=$(mktemp -d)
printf 'input\n' > "$gwflow_preview_project/reads.txt"
conda run --prefix .venv python -m gwflow run --dry-run examples.one_file:main \
  --project "$gwflow_preview_project" --bindings '{"source":"reads.txt"}'
```

Runtime execution is host-only in Phase 2. A runtime request containing a local
or registry image is rejected before any job can be submitted; pure `plan`
continues to inspect image declarations.

Runtime declaration records are described in [runtime records](docs/runtime-records.md).
Read-only reuse and recovery decisions are described in [runtime evaluation](docs/runtime-evaluation.md).
For a runnable native-command demo with real local gwf/Bash and no live jobs,
see [static Slurm submission](docs/slurm-submission.md):

```sh
conda run --prefix .venv python -m examples.static_submission_demo
```

For sequential active-job attachment, expired-history reuse, retained logs, and
query-failure diagnostics, see [scheduler observations](docs/scheduler-observation.md):

```sh
conda run --prefix .venv python -m examples.scheduler_attachment_demo
```

For actual execution, reuse after fixture intermediate removal, and selective
retry, see [runtime recovery](docs/runtime-recovery.md):

```sh
conda run --prefix .venv python -m examples.runtime_recovery_demo
```

For uncertain acceptance, use the explicit [manual recovery procedure](docs/manual-recovery.md).
Its portable demo checks ownership, quiescence, association repair, and safe retry:

```sh
conda run --prefix .venv python -m examples.manual_recovery_demo
```

## Run the current test suite

Create an isolated Conda environment from the repository root:

```sh
conda env create --prefix .venv --file experiments/phase0/environment.yml
conda run --prefix .venv python -m pytest -q experiments/phase0 tests
```

The tests use temporary directories and simulated scheduler/container services.
They do not submit Slurm jobs or download container images.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, pull-request, and manual
testing workflow.

## Inspect a Phase 1 plan

See [the planning guide](docs/phase1-planning.md) for the Python definition API,
local setup, and runnable examples. Plans describe intended work; they do not
establish completion or reuse.
