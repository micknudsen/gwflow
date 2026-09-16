# Host target execution

Phase 2 executes host-declaring targets with Bash. Before Bash starts, gwflow
publishes the target's selected current attempt. It retains per-attempt stdout,
stderr, and a diagnostic record. After a zero command exit it verifies every
declared output is a real file, then atomically publishes the selected attempt's
success receipt. Missing output and receipt-publication failures return 72 and
73 respectively, so a scheduler `afterok` dependency cannot pass them.

Failed commands may leave files and diagnostic history but never receive a
success receipt. A later attempt replaces the current-attempt selection before
it can mutate outputs; an old receipt therefore cannot certify the replacement.

Run the successful maintained demo with:

```sh
conda run --prefix .venv python -m examples.host_execution_demo /tmp/gwflow-host-execution-demo
```

It prints the exit and retained output path. `tests/test_host_execution.py`
also covers failed-after-output, missing-output, receipt-publication, and
attempt-fencing behavior through the maintained executor.
