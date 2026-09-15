# Source findings

This document records external source evidence and explicitly labelled design
implications. [Phase 0 results](phase0-results.md) contain the corresponding
runtime observations and mechanism refinements. Online documentation and
default branches can change; a source snapshot does not establish gwflow's
supported dependency range.

## Nextflow: directory hashes and reuse after cleanup

Primary source: [official caching and resuming documentation](https://docs.seqera.io/nextflow/cache-and-resume), sections “Task hash” and “Work directory”. This is the live documentation, not a pinned release.

Verified documentation behavior:

- Task hashes incorporate execution context and task metadata, including inputs, script, and software-environment information; they are not simply checksums of output bytes.
- Resuming requires matching cache metadata, required outputs in the corresponding work directory, and a valid exit code.
- The documentation therefore instructs users to preserve both the task cache and work directories for resume.

Design implication, not a decision: hash-based directory naming by itself does not deliver gwflow's required reuse after internal-intermediate cleanup. The subpipeline completion boundary and retained-result validity need their own explicit design.

## gwf: initial evidence and released-version check

Focused follow-ups cover [exact scheduler-status precedence](research-gwf-status.md) and [Apptainer execution support](research-apptainer.md). They take precedence over any payload-only completion recommendation below.

Initial sources: [tutorial](https://gwf.app/tutorial/), [backends](https://gwf.app/backends/), [reference](https://gwf.app/reference/), and retrieved snapshots of [scheduling.py](https://raw.githubusercontent.com/gwforg/gwf/master/src/gwf/scheduling.py) and [core.py](https://raw.githubusercontent.com/gwforg/gwf/master/src/gwf/core.py).

The tutorial documents submission of dependent targets before their prerequisites finish. It also describes incomplete output files being mistaken for successful results when existence and timestamps appear current. The retrieved scheduling source checks missing outputs and timestamps, visits dependencies recursively, and can submit dependents after a producer is submitted. These observations show why existing target freshness is not sufficient proof of subpipeline completion after intermediates are deleted.

Version caution: the website banner says 2.1.1, but several page sections describe 3.0.0 features. Live remote refs gave HEAD `b49f21a9f813cb42ff03c05210761c1a9f62d779` and version tag `v2.1.1` at `f25685a781befe75ef23556110334039b274c066`; no v3.0.0 tag was observed. The first raw-source responses were cached default-branch snapshots and were not verified against HEAD. Do not infer released support for selective output checking, target isolation, or newer local-scheduler behavior from the website banner.

The released v2.1.1 files at commit `f25685a781befe75ef23556110334039b274c066` were retrieved directly through public raw URLs. The findings below supersede any uncertainty about these particular release behaviors. Runtime evidence is recorded in Phase 0; this source verification does not by itself select gwflow's supported version range.

### Verified in released gwf v2.1.1

| Behavior | Evidence and implication | Pinned source |
| --- | --- | --- |
| Reruns after deletion | Any missing declared target output causes scheduling; otherwise freshness uses input/output modification times. Dependency scheduling/status propagates to dependent targets, which explains why cleanup-tolerant subpipeline reuse needs a separate boundary check. | [scheduling.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/scheduling.py) |
| Spec hashes | Disabled by default. When enabled, SHA-1 covers only `target.spec`, keyed by target name, and is saved after submission, not successful execution. It is not completion evidence or a complete execution identity. | [conf.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/conf.py), [core.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/core.py), [scheduling.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/scheduling.py) |
| Slurm lifecycle | Uses `sbatch --parsable` with `--dependency=afterok:<job IDs>`. Recursive submission returns without waiting for job completion; backend close is empty. | [slurm.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/slurm.py), [run.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/plugins/run.py) |
| Graph construction | Documented graph/submission API; released signature `Graph.from_targets(targets, fs)`. An input without a producer must exist on disk or graph construction raises `UnresolvedInputError`. No dedicated subpipeline completion/pruning hook found. | [reference.rst](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/docs/reference.rst), [core.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/core.py) |
| File and environment access | Runtime uses `target.working_dir`; the ordinary Slurm path does not transfer declared inputs/outputs. The temporary file is an execution script, not isolated data storage. The submitting Python executable and required environment must also be accessible or handled explicitly by execution configuration. | [slurm.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/slurm.py), [runtime](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/exec/__main__.py), [executors.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/executors.py) |
| Output validation | Runtime enables `set -e`, but not `set -u` or `pipefail`, and returns the command's exit status without validating declared outputs. Validation inside existing compute jobs is possible; whole-subpipeline completion remains a design problem. | [runtime](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/exec/__main__.py) |
| Package metadata | Python >=3.8; flit_core >=3.2,<4; no project runtime-dependency list in pyproject. Conda recipe is noarch Python and declares attrs, click, click-plugins, prettyprinter, and Python >=3.8. | [pyproject.toml](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/pyproject.toml), [conda/meta.yaml](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/conda/meta.yaml) |
| Log preservation | Stock `gwf run` defaults to cleaning logs for target names absent from the current graph. Omitting reusable subpipelines therefore requires an explicit provenance/log policy. | [run.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/plugins/run.py), [conf.py](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/conf.py) |

The inspected release lacks the `require_all_outputs` argument and target-isolation API described in the website's 3.0.0 sections. The new local-scheduler details in the initial website findings must not be attributed to v2.1.1 without separate release verification.

### Published gwf conda artifact

The [official Anaconda release API](https://api.anaconda.org/release/gwforg/gwf/2.1.1) reports gwf 2.1.1 on **gwforg**, label `main`, as `noarch/gwf-2.1.1-py_0.conda` (`noarch: python`, build 0). The artifact declares attrs, click, click-plugins, prettyprinter, and Python >=3.8, with no Python upper bound. Its SHA-256 is `5b78e4685273706c9cec1cc5657d829e4cbd68fb84b6b2aea94403ecc0bada7a`.

The official package API endpoints for `bioconda/gwf` and `conda-forge/gwf`
returned 404 during the same check. Packaging implication: include `gwforg` in
the build and installation channel configuration and select
`gwforg::gwf=2.1.1`; the usual conda-forge and bioconda channels do not supply
this verified artifact. Artifact metadata was checked, but no solver,
installation, or runtime test was run. The recorded artifact checksum is
provenance for this packaging investigation, not an input-data checksum
requirement for gwflow.

### Exact freshness semantics

gwflow's requirements exclude pre-submission input-file checksum matching and any input check stricter than standard gwf. The pinned v2.1.1 source establishes:

- The freshness inequality is strictly `max(input mtimes) > min(output mtimes)`. Equal timestamps do not trigger it. Any missing declared output requires execution. With no inputs, the comparison uses negative infinity; with no outputs, the target needs execution. Submitted/running status may still prevent another submission. [Scheduling source](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/scheduling.py)
- The checks read existence and current `st_mtime`; they do not compare size, contents, or a previously saved input timestamp. Producerless inputs must exist at graph construction. [Core source](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/core.py)

Inference for gwflow: one aggregate timestamp comparison over a whole subpipeline can be stricter than gwf's target-level rule. For independent branches `x → a` and `y → b`, mtimes `x=9, a=10, y=11, b=12` leave both targets current, while a pooled comparison incorrectly tests `11 > 10`. A future reuse check must account for the actual dependencies. This reasoning is recorded as an acceptance constraint in `design.md`; no completion/freshness algorithm has been selected or tested.

Separate proposal, not an accepted decision: a work-directory name could digest a small declared computation description rather than file contents. That would address computations, not establish that input files are unchanged. Do not put input size/mtime snapshots into such a key as a silent replacement for the rejected stronger checking.

### Repeated submissions while jobs remain active

Verified at the same pinned gwf v2.1.1 commit: with the same working directory and target names, the tracking backend persists target-name/job-ID mappings in `.gwf/slurm-backend-tracked.json`. A later command can recognize queued/running targets without submitting them again and submit new dependent targets using their existing job IDs in Slurm `afterok` dependencies. [Tracking backend](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/base.py), [scheduling](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/scheduling.py), [Slurm submission](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/slurm.py)

The inspected path has no submission lock: tracking is loaded at initialization and rewritten with a normal JSON file write on backend close. Source-based inference, not an experiment: truly simultaneous commands can read the same previous state, duplicate submissions, and overwrite tracking updates. This is distinct from a later command run after the first submission command exits while its jobs remain active. [Tracking persistence](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/base.py), [run command](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/plugins/run.py), [CLI](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/cli.py)

Implication, not an accepted mechanism: gwflow can aim to preserve reuse of active jobs while coordinating the short submission commands. Rejecting a submission merely because equivalent jobs are active would be a new restriction, not an unavoidable gwf limitation. Stable target identity, tracking persistence, partial submission, and races need adapter-level validation.

### Completion and ordering with parallel terminal targets

Source-informed design reasoning identified a candidate that requires no extra orchestration job: existing compute targets record their own success, and a later submission, status, or cleanup command evaluates the relevant records, retained outputs, and freshness conditions together. A single persistent subpipeline completion marker is not inherently necessary. Phase 0 tests this candidate; it is not yet product behavior.

For same-run ordering, gwf scheduling consumes graph dependency sets and Slurm translates them into job dependencies. Two candidate representations need different tests:

- Using every upstream terminal's retained output or success record as a downstream input follows file-based graph discovery, but also adds those files to downstream timestamp checks even if computation does not read them.
- Explicit graph dependency edges could provide an ordering barrier without adding computational inputs. The released graph is mutable and scheduling reads its dependency map, but graph consistency, reverse edges, pruning, and resubmission need deliberate validation; mutation is not automatically revalidated.

Sources for those integration surfaces: [graph implementation](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/core.py), [scheduling](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/scheduling.py), [Slurm backend](https://github.com/gwforg/gwf/blob/f25685a781befe75ef23556110334039b274c066/src/gwf/backends/slurm.py).

Limits: per-target records do not establish atomic publication of the whole output set, identify later mutations, or prove that the scheduler eventually recorded success after the record was written. Old records must not certify a failed retry. Input freshness after cleanup needs a dependency-aware mechanism. Observable completion, ordering, and publication guarantees are defined in the [requirements](design.md); record formats and protocols remain implementation work.

### Computational success versus final scheduler outcome

For an `sbatch` job, Slurm records the batch script's exit code and also records termination signals; a nonzero script exit means job failure. [Job exit codes](https://slurm.schedmd.com/job_exit_code.html) The documented states distinguish successful completion from failure, cancellation, timeout, and node failure; `COMPLETING` can include cleanup after execution has ended. [Job state codes](https://slurm.schedmd.com/job_state_codes.html)

Design inference: an in-job success record can be written only before the job finishes. There is therefore a window after commands/output checks succeed and their record becomes durable, but before the job exits and Slurm establishes the final outcome. A failure during that window can leave a record of successful computation alongside a failed scheduler outcome. The record alone cannot distinguish eventual Slurm success from that later failure once accounting history is unavailable.

This does not make durable computational-success evidence infeasible: a record written only after the entire command payload succeeds can distinguish it from commands that create outputs and then return nonzero. The record does not suffice despite a later known job failure; gwflow matches gwf, including Slurm status. The [focused released-source investigation](research-gwf-status.md) establishes the actual precedence and unknown-status fallback. No controller, extra orchestration job, or cluster hook is introduced.

Phase 0 injects failure after durable command evidence, observes the scheduler outcome, and evaluates retry behavior with attempt fencing. It also checks downstream jobs blocked on the failed job and their recovery on a later submission.

Design implications, not selected implementations:

- Omitting verified completed subpipelines when constructing a gwf graph is a candidate integration. Selecting only endpoint targets would not by itself prevent recursive traversal of their producers.
- A subpipeline with several parallel terminal steps needs an explicit completion/publication protocol that establishes success of all required work. An atomic marker alone does not identify which actor can safely create it. No extra finalizer or orchestration job is authorized.
- If generated upstream file contents do not exist at submission, content-only identity for downstream work is unavailable then. Changed producer identity therefore invalidates consumers conservatively; later byte-equivalence reuse is not required.

## skua: verified packaging reference

[`MOMA-AUH/skua`](https://github.com/MOMA-AUH/skua) is a separate public project
used only as a reference for Python packaging, Conda recipes, and release
automation. gwflow does not depend on skua and does not use skua's release
channel. The conventions below come from skua's `master` branch at
[`4b2162c4d2df11830ba030420899af7cb6165d04`](https://github.com/MOMA-AUH/skua/commit/4b2162c4d2df11830ba030420899af7cb6165d04),
version 0.7.1.

| Area | Verified convention | Pinned source |
| --- | --- | --- |
| Python package | setuptools >=69 and wheel; `src` layout; dynamic version from `skua._version.__version__`; Python >=3.11; runtime dependency `pysam>=0.22`; CLI entry point `skua = skua.cli:main` | [pyproject.toml](https://github.com/MOMA-AUH/skua/blob/4b2162c4d2df11830ba030420899af7cb6165d04/pyproject.toml) |
| Version updates | Helper coordinates the Python version file and conda recipe; this does not itself prove a semantic-versioning compatibility policy | [tools/set_version.py](https://github.com/MOMA-AUH/skua/blob/4b2162c4d2df11830ba030420899af7cb6165d04/tools/set_version.py) |
| Conda recipe | Version 0.7.1, build 0, `noarch: python`, local source `path: ..`; runtime requirements match Python metadata; tests import skua and run CLI help | [meta.yaml](https://github.com/MOMA-AUH/skua/blob/4b2162c4d2df11830ba030420899af7cb6165d04/conda-recipe/meta.yaml) |
| Conda build | Uses the build environment's Python to run `pip install . -vv` | [build.sh](https://github.com/MOMA-AUH/skua/blob/4b2162c4d2df11830ba030420899af7cb6165d04/conda-recipe/build.sh) |
| Release automation | `v*` tag pushes and manual dispatch trigger Ubuntu build/test. Publication requires a tag and successful build/test; uploads to MOMA-AUH with `--skip-existing`, using the `conda` GitHub environment and `ANACONDA_API_TOKEN`. Build channels are conda-forge, bioconda, defaults with strict priority. | [publish.yml](https://github.com/MOMA-AUH/skua/blob/4b2162c4d2df11830ba030420899af7cb6165d04/.github/workflows/publish.yml) |
| Installation and development | README recommends `conda install MOMA-AUH::skua`; development environment uses conda-forge, Python >=3.11, pip, conda-build, pytest, and editable installation | [README](https://github.com/MOMA-AUH/skua), [environment.yml](https://github.com/MOMA-AUH/skua/blob/4b2162c4d2df11830ba030420899af7cb6165d04/environment.yml) |

Limits: workflow configuration was inspected, but successful release runs and current Anaconda inventory were not checked. Other workflow files were listed but not inspected. gwflow's dependency versions, conda channel, and pipeline-definition distribution remain project decisions; skua's values are a reference, not gwflow settings.
