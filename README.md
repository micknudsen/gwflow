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

The Python package and plan command are usable for inspecting intended work.
Target execution, scheduler integration, runtime reuse/recovery, image acquisition,
and cleanup remain later-phase work. A plan or manifest never certifies completion.

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
