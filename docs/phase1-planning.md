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

## Deterministic addresses

The [identity contract](adr/0005-descriptor-addressing.md) specifies exact
canonicalization, qualified names, lexical paths, and current result slots.
The plan exposes `identity`, `descriptor`, `work_dir`, and `result_dir`.
Run `conda run --prefix .venv python -m examples.identity_demo`: original,
repeat and main-version lines have identical addresses; new-binding and
sub-version lines differ. No files are needed.

To demonstrate in-place input changes without changing identity:

```sh
mkdir -p /tmp/gwflow-demo
printf first > /tmp/gwflow-demo/reads.txt
conda run --prefix .venv python -m examples.identity_demo
printf 'changed contents' > /tmp/gwflow-demo/reads.txt
conda run --prefix .venv python -m examples.identity_demo
```

The two runs agree: identity is distinct from later freshness evaluation.

## Finite file lists

Declare `"files"` and bind a Python list or tuple (a JSON array in the CLI).
Order and duplicates are significant; list and tuple with the same elements
are equivalent. Empty lists are allowed and are still required named bindings.
Every element follows the single-file path policy. Generators and scalar
paths are rejected. Diagnostics use zero-based element indices. Builders see
a list of normalized absolute paths; the descriptor uses `kind: files` and an
ordered `items` array of file descriptors. This additive form uses identity
revision 1 and leaves existing file descriptors unchanged.

```sh
conda run --prefix .venv python -m gwflow plan examples.file_list:main --project /tmp/gwflow-demo --bindings '{"reads":["a","b"]}'
conda run --prefix .venv python -m gwflow plan examples.file_list:main --project /tmp/gwflow-demo --bindings '{"reads":["b","a"]}'
conda run --prefix .venv python -m gwflow plan examples.file_list:main --project /tmp/gwflow-demo --bindings '{"reads":["a","b","b"]}'
conda run --prefix .venv python -m gwflow plan examples.file_list:main --project /tmp/gwflow-demo --bindings '{"reads":["a",7]}'
```

Repeating a command keeps identity; reordering, replacing, adding, removing or
duplicating a file changes it. The last command exits 2 naming `reads` element 1.
The entire list is known during planning; this adds no runtime discovery.

## Small data and fixed computational parameters

Declare input kind `"data"`. Values are JSON null, booleans, strings, integers
from `-(2**53-1)` to `2**53-1`, finite floats, lists, or dictionaries with string
keys. Subclasses and non-JSON Python objects are unsupported. Nesting is limited
to depth 16 (root depth 0), and each value's canonical ASCII JSON is at most
16384 bytes. Cyclic values exceed the depth limit. Object key order is
irrelevant; list order/duplicates matter. Null, bool, int, float and string
remain distinct; `1` differs from `1.0`, and `0.0` differs from `-0.0`.
Strings preserve code points. The descriptor is `{"kind":"data","value":...}`.
Planning copies values and does not treat strings inside data as file paths.

`Subpipeline(..., parameters={"threshold": 5})` fixes computational parameters
under its version. Builders read `ctx.parameters`; the plan displays
`computational_parameters` separately from `bindings`. Parameters use the same
bounded JSON contract, and their names cannot overlap inputs. Changing a
parameter requires a new definition version. Input bindings cannot override it.

```sh
conda run --prefix .venv python -m gwflow plan examples.small_data:main --project /tmp/gwflow-demo --bindings '{"sample":"A"}'
conda run --prefix .venv python -m gwflow plan examples.small_data:main --project /tmp/gwflow-demo --bindings '{"sample":"B"}'
conda run --prefix .venv python -m gwflow plan examples.small_data:main --project /tmp/gwflow-demo --bindings '{"sample":"A","threshold":10}'
conda run --prefix .venv python -m gwflow plan examples.small_data:revised --project /tmp/gwflow-demo --bindings '{"sample":"A"}'
```

The first two retain threshold 5 with different dataset identities. The third
exits 2; the fourth selects version 2 with threshold 10 and a new identity.

## Composition and explicit exports

Use `MainPipeline(name, version, uses={"sample_a": Use(definition,
{"source": "a.txt"}), ...})` for composition. Occurrence names are unique,
nonempty strings in a mapping; ordering is incidental. `plan` accepts optional
binding overrides nested by occurrence; CLI `--bindings` uses the same shape.
The one-subpipeline shorthand continues to use flat named bindings.

Select a concrete `Subpipeline`, or `DefinitionRef("module:export",
"package.definition", "explicit-version")`. References check both exported name
and version before planning; missing exports and mismatches fail. Ordinary
installed/editable imports are used without an online registry. Development
versions (for example `1.dev1`) are opaque explicit versions too: revise them
when changing computation. Package versions are separate provenance.

Equivalent occurrences share one computation and result slot, with their names
listed in `occurrences`; `main.occurrences` records each selection and package
provenance. Within a plan, one published name/version must have equal declared
input/output interfaces and parameters, and the same builder callable. Repeated
identical bindings must compile to the same targets. This conservative visible
conflict check requires authors to export a shared builder rather than create
fresh wrapper functions for equivalent definitions. It does not inspect hidden
scripts, compare installed software, or detect mutations across saved plans.

```sh
conda run --prefix .venv python -m gwflow plan examples.composition:main --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.composition:main_only --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.composition:report_changed --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.composition:repeated --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.composition:unavailable --project /tmp/gwflow-demo
```

The first plans two datasets and independent reporting. Main-only changes
preserve all identities; reporting changes preserve both dataset identities.
The repeated case shows four occurrences sharing three computations. The last
exits 2 explaining the unavailable requested version 99.
