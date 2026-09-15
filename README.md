# gwflow

gwflow is an experimental Python layer for composing independently versioned
subpipelines on top of [gwf](https://gwf.app/). It is designed to preserve
completed subpipeline results after disposable intermediates are cleaned while
retaining gwf-compatible freshness and scheduler behaviour.

Phase 0 feasibility work is complete. Product implementation begins in Phase 1
with definition interfaces, deterministic identity, graph validation, and an
inspectable plan command. See the [implementation plan](docs/implementation-plan.md)
and [architecture](docs/architecture-proposal.md).

## Development status

gwflow is not yet a runnable package. The repository currently contains the
accepted design and portable feasibility probes used to validate the difficult
gwf integration seams.

## Run the current test suite

Create an isolated Conda environment from the repository root:

```sh
conda env create --prefix .venv --file experiments/phase0/environment.yml
conda run --prefix .venv python -m pytest -q experiments/phase0
```

The tests use temporary directories and simulated scheduler/container services.
They do not submit Slurm jobs or download container images.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, pull-request, and manual
testing workflow.

## Inspect a Phase 1 plan

See [the planning guide](docs/phase1-planning.md) for the Python definition API,
local setup, and runnable examples. Plans describe intended work; they do not
establish completion or reuse.
