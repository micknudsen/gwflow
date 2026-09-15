# Contributing

All repository changes are developed on a branch and merged into `master`
through a pull request. Keep each pull request to one independently testable
behaviour and use squash merge so it becomes one commit on `master`.

## Development loop

1. Start a branch from the latest `master` for one GitHub ticket.
2. Add or update tests at the highest practical behavioural seam.
3. Implement the ticket and run the required test command locally.
4. Open a pull request with the observable change and exact manual test steps.
5. Wait for required CI checks and resolve all review conversations.
6. Let the project owner test the pull-request branch before squash merging.

The pull request remains the unit of delivery. Work-in-progress commits may be
as granular as useful because they will not be preserved on `master`.

## Current test command

```sh
conda run --prefix .venv python -m pytest -q experiments/phase0 tests
```

Create `.venv` first if necessary:

```sh
conda env create --prefix .venv --file experiments/phase0/environment.yml
```

GitHub Actions runs the same pytest command on Linux. Live Slurm, Apptainer, or
shared-filesystem verification is opt-in and must be recorded separately in a
pull request when its behaviour is in scope.

## Ticket and pull-request scope

Phase work is recorded in a parent specification issue. Implementation tickets
are vertical tracer bullets: each must deliver a narrow observable path, own
the tests that grade it, and state its blockers. A pull request closes one such
ticket and includes a short demo that another person can run after checking out
the branch.
