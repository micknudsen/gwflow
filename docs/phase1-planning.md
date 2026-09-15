# Phase 1 planning

From the checkout, create the development environment as described in
[Contributing](../CONTRIBUTING.md), then run:

```sh
conda run --prefix .venv python -m gwflow plan examples.one_file:main --project /tmp/gwflow-demo --bindings '{"source":"reads.txt"}'
conda run --prefix .venv python -m gwflow plan examples.one_file:main --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan invalid:main --project /tmp/gwflow-demo
```

The first emits JSON identifying main/subpipeline versions, package/software
provenance, the named input, command, and retained `copy` output. The others
exit 2 with a missing-binding or import diagnostic. Success exits 0.

`Subpipeline(name, version, inputs, outputs, build, package=...)` declares the
versioned interface. Inputs currently use `"file"`; outputs map public names to
relative filenames. The builder receives a `Context`: `inputs` contains bound
paths, and `path(relative)` locates generated files. Return a list containing a
`Target(name, command, inputs=..., outputs=...)`. A `MainPipeline` selects the
subpipeline. `plan(main, bindings, project=...)` returns an inspectable dictionary.

Files are not required to exist: planning does not inspect external inputs or
create generated outputs or directories. Input existence remains unevaluated;
execution will require real external inputs. No target command, scheduler,
container runtime, attempt, coordination, or cleanup is involved. Importing a
Python definition and calling its builder runs trusted author code: builders
must be deterministic and avoid side effects. Commands are descriptions only.

Definitions use ordinary Python imports. For editable development, the minimal
package metadata allows `python -m pip install --no-build-isolation -e .` in an
environment with pip and setuptools. The bundled `examples.one_file` module is
then importable from other working directories; edit it and re-run the command.
No environment solving or registry is part of the planner. Conda release
packaging and execution remain later-phase work.
