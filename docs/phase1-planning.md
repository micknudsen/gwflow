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
versioned interface. Inputs use `"file"`, `"files"`, or `"data"`; outputs map public names to
relative filenames. The builder receives a `Context`: `inputs` contains bound
paths, and `path(relative)` locates generated files. Return a finite list of
`Target(name, command, inputs=..., outputs=...)` declarations. A `MainPipeline` selects the
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

## Operational resources

`Target(..., resources={...})` declares default requests. `plan(...,
resources={occurrence: {target: overrides}})` and CLI `--resources` apply
operational overrides after building, so overrides cannot alter commands.
The one-subpipeline shorthand uses occurrence `main`. Supported fields are
positive integer `memory_mb` and `walltime_seconds`, and nonempty,
whitespace-free string `partition` and `account`. Booleans are not integers here.
Unspecified fields retain defaults. Unknown fields, occurrences, or targets fail.
Equivalent occurrences sharing one computation must request identical resources;
conflicts fail rather than silently choosing an occurrence's request.

These fields must be computationally neutral. A result-affecting setting belongs
in the immutable definition even if it resembles a resource request. Resources
are not supplied to builders and never enter the computation descriptor.

```sh
conda run --prefix .venv python -m gwflow plan examples.resources:main --project /tmp/gwflow-demo --bindings '{"source":"a"}'
conda run --prefix .venv python -m gwflow plan examples.resources:main --project /tmp/gwflow-demo --bindings '{"source":"a"}' --resources '{"main":{"copy":{"memory_mb":2048,"walltime_seconds":120}}}'
conda run --prefix .venv python -m gwflow plan examples.resources:main --project /tmp/gwflow-demo --bindings '{"source":"a"}' --resources '{"main":{"copy":{"command":"other"}}}'
```

The first two have identical identities/result locations and different requests.
The third exits 2: command changes are not operational overrides.

## Complete internal graphs

Builders return all targets as a finite list. Targets have unique nonempty
names within their computation. File inputs infer edges from the target
producing the same normalized path. `depends_on=("target", ...)` adds explicit
computational predecessor references without inventing file inputs. Both kinds
participate in cycle validation; these are not scheduler-only completion edges.

Use `ctx.path(relative)` for generated paths. Retained names map to normalized
relative files in the result slot; other files go in work. Target paths may be
absolute or relative to work. Outputs must be contained in owned work/result
paths, with one producer per file and no file/parent collisions. Retained names
must identify distinct files with target producers. An unproduced input inside
owned paths is invalid; producerless external files remain unobserved.
Validation uses lexical paths and does not inspect generated files or symlinks.

Plans expose target `computation` membership, `dependencies`, file/explicit
`computational_edges`, `entry_targets`, `terminal_targets`, `internal_outputs`,
and per-target `output_kinds`. Outputless targets have `always_run: true`;
metadata does not make them cacheable. Parallel terminals need no synthetic join.

```sh
conda run --prefix .venv python -m gwflow plan examples.internal_graph:main --project /tmp/gwflow-demo --bindings '{"source":"x"}'
conda run --prefix .venv python -m gwflow plan examples.internal_graph:parallel_main --project /tmp/gwflow-demo --bindings '{"source":"x"}'
conda run --prefix .venv python -m gwflow plan examples.internal_graph:cycle --project /tmp/gwflow-demo --bindings '{"source":"x"}'
conda run --prefix .venv python -m gwflow plan examples.internal_graph:duplicate --project /tmp/gwflow-demo --bindings '{"source":"x"}'
conda run --prefix .venv python -m gwflow plan examples.internal_graph:always --project /tmp/gwflow-demo --bindings '{"source":"x"}'
```

The first exposes a fork/join; the second has fast/slow terminals. The next two
exit 2 naming a cycle or ambiguous producer. The last shows one outputless
always-run target. No target is executed and no runtime jobs are discovered.

## Retained-output connections

Bind a file input with `OutputRef("producer_occurrence", "public_output")` in a
Python `Use`. References are currently individual file-output references;
list-element addressing and a CLI reference-expression language are not exposed.
Composition bindings can still be supplied by ordinary imported Python fixtures.
The [connection identity contract](adr/0007-retained-output-identities.md)
records upstream identities, lexical boundary checks, and their scope.

Plans expose each resolved `connections` record (input, producer computation,
output name, path), `whole_producer_dependencies` independently of target file
inputs, and `composition_edges` for actual target file consumption. Unknown
producers/outputs and composition cycles fail before a valid plan is returned.

```sh
conda run --prefix .venv python -m gwflow plan examples.connections:main --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.connections:revised --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.connections:private --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.connections:exposed --project /tmp/gwflow-demo
```

Revising the producer changes producer, consumer and report identities; the
independent branch stays unchanged. `private` exits 2 because `a` is not a public
retained name. `exposed` declares `a` under producer version 3 and succeeds.
No output bytes or execution evidence are inspected.

## Whole-producer obligations

`completion_obligations` expands each required producer identity into its
`required_targets` and `terminal_targets`. Its condition is whole-subpipeline
completion and its evaluation is explicitly `not evaluated`. All internal work
is required, including independent branches whose files this consumer never
reads. Target inputs and computational edges retain only actual file
consumption. Scheduler enforcement remains a later execution-adapter concern.

```sh
conda run --prefix .venv python -m gwflow plan examples.whole_producer:main --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.whole_producer:multiple --project /tmp/gwflow-demo
```

The first plan has exactly three targets: producer fast/slow and consumer copy.
Copy reads one fast file, but its obligation lists both fast and slow terminals.
The second adds a fork/join producer; the consumer reads two files and has two
whole-producer obligations, including all four fork/join targets and terminal d.
No unrelated freshness inputs, synthetic targets, attempts, or jobs are added.

## Declared target environments

Set `Target(..., image=LocalImage("images/tool.sif"))` or
`image=RegistryImage("docker://registry.example/tool:1")`. Local paths must end
in `.sif`; relative paths anchor lexically to the selected project. Both original
declaration and absolute path are displayed. Registry syntax currently supports
nonempty `docker://` and `oras://` declarations using letters, digits, `. _ / :
@ + -`, without whitespace and ending in a letter/digit. This checks syntax,
not registry existence, image identity, immutability, or runtime usability.

With `image=None` (the default), the plan explicitly records `kind: host`, meaning
the prepared host environment. There is no subpipeline image field or inheritance.
Declared image changes require a new subpipeline version; image declarations
are not resource overrides. No image files, registry access, resolution,
acquisition, cache, mounts, Bash preflight, or container execution are involved.

```sh
conda run --prefix .venv python -m gwflow plan examples.target_images:main --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.target_images:revised --project /tmp/gwflow-demo
```

The first shows local SIF, registry and host targets without installed images.
The second changes one registry declaration under version 2 and has a new identity.

## Versioned manifests

See the [schema 1 contract](manifest-schema.md) for required fields, types,
interpretation revisions, validation, JSON round trips, and a mixed-feature
demo. `manifest(plan_result, identity)` exports one detached record;
`validate_manifest(record)` checks it without execution. The CLI's
`--format manifests` emits all computation manifests as a JSON array on stdout.
No project metadata is automatically persisted, and a valid manifest is not
completion evidence.

## Identity facts and prospective reuse

Every computation's `explanation` separates identity facts, constraints, and
prospective runtime conditions. The stable machine-readable `code` vocabulary is:

| Group | Codes and meaning |
| --- | --- |
| `identity_facts` | `definition-identity`, `named-binding-identity`, `upstream-identity`: the version, typed bindings and connected producer facts determining identity. |
| `identity_facts` | `provenance-only-versions`: main/software/package versions do not salt identity. `current-result-slot`: the planned address is not proof of completion. |
| `constraints` | `whole-producer-completion`: producer membership remains separate from file inputs. `outputless-always-run`: present when outputless targets prevent metadata-created cacheability. |
| `prospective_reuse.conditions` | `required-completion-evidence`, `retained-output-validity`, `target-level-freshness`, `available-scheduler-state`: each has `evaluation: not evaluated`. |

Prospective reuse always has `outcome: undetermined` in Phase 1. The recovery
explanation describes a conditional later evaluation, never established failed
work or a selection of jobs to submit. Descriptive wording may evolve; codes,
basis facts and evaluation limits are the public semantic contract. No baseline
plan comparison service or runtime evaluator is introduced. Schema-1 manifests
retain their unevaluated-runtime field; these derived display explanations are
not added to the required manifest schema.

```sh
conda run --prefix .venv python -m examples.explanations
conda run --prefix .venv python -m gwflow plan examples.explanations:main --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.explanations:main_changed --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.explanations:upstream_changed --project /tmp/gwflow-demo
conda run --prefix .venv python -m gwflow plan examples.explanations:outputless --project /tmp/gwflow-demo --bindings '{"source":"reads.txt"}'
```

Main-only changes preserve identities; upstream changes propagate through the
consumer/report chain and preserve the independent branch. All examples list
the four unevaluated conditions. The outputless example adds its always-run
constraint.

To deliberately prepare surviving fixture payloads and a saved planning record,
then demonstrate that planning still makes no completion claim:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from gwflow import manifest, plan
from examples.explanations import main
root = Path('/tmp/gwflow-explanation-demo')
result = plan(main, project=root)
for comp in result['computations']:
    for value in comp['retained_outputs'].values():
        path = Path(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('surviving fixture payload')
    (root / (comp['identity'] + '.json')).write_text(json.dumps(manifest(result, comp['identity'])))
assert plan(main, project=root) == result
print([c['explanation']['prospective_reuse']['outcome'] for c in result['computations']])
PY
```

The output is four `undetermined` values. File creation above is explicit fixture
setup by the example, not a planner side effect.

## Phase 1 behavioral coverage

The required command in [Contributing](../CONTRIBUTING.md) runs maintained public
planner/command tests alongside the Phase 0 probes. Parent #3 acceptance is
covered by these test modules:

| Acceptance | Public behavior tests |
| --- | --- |
| P1-01–03 | `test_planner`, `test_identity`, `test_composition` |
| P1-04–05 | `test_connections`, `test_small_data`, `test_explanations` |
| P1-06–07 | `test_file_lists`, `test_small_data`, `test_resources`, `test_identity` |
| P1-08 | `test_connections` |
| P1-09–10 | `test_internal_graph`, `test_whole_producer`, binding/composition diagnostic tests |
| P1-11 | `test_environments` |
| P1-12 | `test_manifests` |
| P1-13–14 | `test_explanations`, `test_manifests`, command smoke cases across the above modules |

These tests establish planning behavior only. They do not qualify a runnable
release or substitute for the later Slurm/Apptainer execution and reuse gates.
