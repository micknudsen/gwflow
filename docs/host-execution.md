# Host target execution

Phase 2 executes host-declaring targets through installed gwf's `gwf.exec` and
its default Bash executor. This preserves gwf's `set -e` envelope (without adding
`pipefail`), inherited host environment, and `GWF_TARGET_NAME`. The payload runs
in the computation's work directory. The scheduler name is a safe hash of the
computation identity, target name, and attempt token; domain target names need
not be valid Python identifiers.

## Preparation and compute-job boundary

`prepare_attempt` durably writes an internal invocation record, per-attempt log
diagnostic, and current-attempt selection before returning a job invocation.
It does not execute a payload or submit a job. An attempt token cannot be reused,
including after interrupted preparation. Submission owns the project guard and
active-job checks; this low-level preparation function does not replace them.

The compute-job entry point is:

```sh
python -m gwflow.host_execution /absolute/path/to/invocation.json
```

It verifies that the invocation is filed under its declared project, computation,
target, and attempt, checks current selection, then durably claims the attempt
once before starting the payload. A delayed old worker cannot select itself.
A replay cannot repeat the command or truncate the original payload logs.
Workers never write current-attempt selection. The invocation and claim are
internal execution metadata, not completion evidence or a public authoring API.

After a zero command exit, the worker verifies every declared output is a regular
file, rechecks current selection, and durably publishes the attempt's success
receipt. Outputless commands still execute and receive an empty output list.
Payload failures preserve their exit status. Wrapper failures are nonzero:

| Exit | Meaning |
| --- | --- |
| 72 | Required output missing or not a regular file |
| 73 | Required success-receipt publication failed |
| 74 | Invalid invocation, failed preparation/claim, lost selection, or launch failure |
| 75 | Attempt already started; payload not repeated |

These failures fail the compute job, so a scheduler `afterok` dependency cannot
pass them. A directory-sync failure after receipt replacement is still a failed
job even if the unacknowledged receipt is visible. Known scheduler failure takes
precedence over filesystem evidence.

Failed payloads can leave output files and diagnostic history but do not publish
a success receipt. Each attempt retains `stdout.log`, `stderr.log`, and
`diagnostic.json` under its own runtime-record directory. Replacing an attempt
does not remove that history; publishing a late old receipt cannot change the
current selection or certify its replacement.

## Portable demo (no scheduler submission)

Run the maintained integration harness with:

```sh
conda run --prefix .venv python -m examples.host_execution_demo
```

It creates a fresh temporary project for each case and invokes the actual
compute-job entry point with real gwf and Bash. The JSON report includes success
(exit 0), a command that writes then fails (31), a missing output (72), and a
receipt-publication failure (73), plus paths to retained logs and invocation
records. An optional positional argument chooses a new demo directory; an
existing directory is refused. No Slurm jobs are submitted. This harness is not
a local backend for `gwflow run`.

`tests/test_host_execution.py` also covers shell behavior, inherited environment,
durable-fence and post-replacement sync failures, outputless work, delayed old
workers, replay rejection, and a late actual old success receipt followed by
product runtime evaluation.
