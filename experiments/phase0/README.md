# Phase 0 feasibility probes

Disposable experiments for the accepted architecture. These are not a product
package or a production adapter. They exercise installed **gwf 2.1.1** with
controlled files and deliberately simulated scheduler and container services.
The [results and remaining gates](../../docs/phase0-results.md) distinguish
direct execution evidence from simulations.

## Run

From the repository root, create an isolated development environment:

```sh
CONDA_PKGS_DIRS="$PWD/.cache/conda/pkgs" CONDA_NUMBER_CHANNEL_NOTICES=0 \
  conda create --prefix "$PWD/.venv" --override-channels \
  --channel gwforg --channel conda-forge python=3.11 gwf=2.1.1 pytest --yes
.venv/bin/python -m pytest -q experiments/phase0
```

The environment specification is recorded in [environment.yml](environment.yml).
`gwforg` supplies gwf; this setup does not alter the user's base environment or
implement automatic workflow tool-environment creation.

Tests use disposable temporary directories, fake job stores, and a fake `apptainer` placed only on test subprocess paths. They submit no real Slurm jobs and fetch no container images. The target execution tests do run real local Bash commands through gwf's host runtime. All files those commands modify belong to their test scratch directories.

## Questions answered locally

| File | Scope |
| --- | --- |
| [test_freshness_recovery.py](test_freshness_recovery.py) | Real gwf scheduling with historical output timestamps for deleted intermediates, separate required-evidence validity, scheduler precedence, partial retry, and missing/corrupt evidence. |
| [test_execution_reuse.py](test_execution_reuse.py) | Real gwf/Bash execution through a disposable host wrapper, generating timestamp receipts that drive cleanup-tolerant reuse and physical recovery. |
| [test_graph_submission.py](test_graph_submission.py) | Real gwf graph/scheduler/tracking with a simulated service: whole-subpipeline control edges, active-job IDs, pruning, and reproduction of obsolete queued dependencies after upstream retry. |
| [test_target_execution.py](test_target_execution.py) | Real gwf runtime and Bash, fake Apptainer: target-specific invocation, exit handling, and a disposable host wrapper for output/evidence publication obligations. |
| [test_local_coordination.py](test_local_coordination.py) | Local filesystem/process coordination with a fake durable scheduler: overlapping invocations and interrupted-submission reconciliation. |

`live_target_envelope.py` is portable test support for the disposable custom
executor exercised by `test_target_execution.py`. Site-bound programs used for
the live Slurm, Apptainer, image-cache, and shared-filesystem checks are retained
privately. Their implementation-relevant conclusions are summarized in the
[Phase 0 results](../../docs/phase0-results.md).
