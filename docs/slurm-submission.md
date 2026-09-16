# Static host submission through gwf and Slurm

`python -m gwflow run <definition> --project <directory>` now uses the maintained
gwf/Slurm adapter. There is no local-backend flag. A successful command submits
the complete necessary graph, durably publishes tracking, releases the command
guard, and exits without waiting for payload completion. Only declared compute
jobs are submitted: no controller, join, observer, or finalizer job is added.

The release-sensitive integration is in `gwflow/slurm_adapter.py`, tested with
installed gwf 2.1.1. It uses gwf's target serialization, Slurm script generation,
`sbatch --parsable`, `afterok`, and status operations. It does not use gwf's
permissive missing-file tracking reader or replace gwflow's independent durable
association map. Log path directives are quoted within the adapter, so spaces
in project paths do not split Slurm options. Installed gwf is not patched.

## Static dependencies and host execution

All target dependencies are known before the first scheduler acceptance. Submit
needed targets in topological order. Internal dependencies and every independent
producer terminal contribute scheduler IDs when they execute or are already
active. Completed reusable prerequisites contribute no job. A consumer's entry
targets wait for every required producer terminal even if the one retained file
they read already exists. These barriers do not add computational file inputs,
pool branch timestamps, or introduce artificial join targets.

Each Slurm job uses gwf to invoke the maintained host worker. The worker uses
gwf's default Bash executor for the original command, preserving its shell
behavior and computation work directory. Output checks and receipt publication
are part of the same compute job; their failures therefore block `afterok`.
The original computational inputs/outputs remain unchanged.

The current interpreter, installed gwf, shared gwflow package/source checkout,
project, and invocation files must be accessible on the compute nodes. The job
explicitly carries the package/source root in `PYTHONPATH`, preserving any
existing entries, and uses the submission interpreter's absolute path. gwflow
does not create environments or install software on compute nodes. Container
declarations remain unsupported for runtime execution in Phase 2.

## Operational resources

| Declared request | gwf option / Slurm request |
| --- | --- |
| `memory_mb` | `memory`, rendered as `<value>M` (Slurm mebibytes per node) |
| `walltime_seconds` | `walltime`, rendered as `HH:MM:SS` or `D-HH:MM:SS` |
| `partition` | `queue` / `-p` |
| `account` | `account` / `-A` |

Absent requests use gwf 2.1.1 defaults: one CPU, `1g` memory, and one hour.
Slurm rounds time requests up to whole minutes; the seconds-valued declaration
is translated without changing computation identity. See the official
[sbatch resource/time documentation](https://slurm.schedmd.com/sbatch.html).
Resources do not enter computation identity or historical declaration checks.

The adapter validates parsable job-ID responses (including an optional cluster
suffix) and retains the numeric job ID for the selected Slurm context. Invalid
acceptance responses preserve submission uncertainty instead of guessing an ID.
Multi-cluster routing is not introduced by this adapter.

## Portable executable demo

```sh
conda run --prefix .venv python -m examples.static_submission_demo
```

This invokes native `gwflow run` commands with private `sbatch`/`sacct`/`squeue`
fixture executables on their process PATH. The production adapter, gwf scripts,
and real local Bash payloads all run; only the external scheduler is replaced.
The fixture starts jobs after the submission command exits and enforces their
declared `afterok` relationships.

The success case submits exactly five jobs, then repeats with no new IDs. The
late-failure case produces the early retained output but leaves its consumer
unexecuted. The JSON report shows job IDs, dependencies, states, and fixture
paths. Optional `--project /path/to/new-directory` selects the root; existing
directories are refused. No real Slurm jobs are submitted.

Live qualification remains opt-in under #42. Portable behavior does not prove
site-specific scheduler or shared-filesystem behavior. Scheduler precedence and
preview queries are described in [scheduler observations](scheduler-observation.md); ordinary recovery and project-wide
active-consumer protection have their own Phase 2 tickets.
