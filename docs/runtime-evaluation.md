# Phase 2 runtime evaluation

`run --dry-run` reads the retained runtime declaration, current-attempt
selection, and selected attempt receipt without creating or updating state. It
returns target and computation decisions for `reuse`, `execute`, or `attach`.

The evaluator preserves target-level freshness: real outputs and intermediates
use live mtimes; only an absent disposable output can use the selected receipt's
recorded `mtime_ns`, and only when every target has valid current evidence and
all retained outputs are real. Receipt file mtimes never enter computation
freshness. Missing retained results or indispensable evidence falls back to
ordinary real-file recovery; outputless targets always execute. Missing
producerless external files are runtime errors.

Scheduler observations are supplied at an explicit adapter seam. `submitted`
and `running` targets attach rather than duplicate work, while `failed` and
`cancelled` take precedence over receipts. The gwf/Slurm adapter that obtains
these observations is delivered separately; the initial CLI has no fabricated
scheduler observation.

## Demo

The maintained `tests/test_evaluator.py` fixture publishes a completed record
using the public runtime-record writer, then invokes:

```sh
conda run --prefix .venv python -m gwflow run --dry-run examples.one_file:main \
  --project /tmp/gwflow-evaluator-demo --bindings '{"source":"reads.txt"}'
```

With a valid maintained record and current retained output the JSON decision is
`reuse`; a newer input, missing retained output, or missing selected receipt
changes it to `execute` without virtualizing real retained files.
