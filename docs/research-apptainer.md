# Apptainer execution research

This note records the source evidence behind image-backed target execution. It
describes feasibility and unresolved choices; it does not select a public API.
Runtime feasibility results are recorded separately in
[Phase 0](phase0-results.md).

The selected design makes images **target-specific**, with separate cutadapt,
bwa, and samtools images permitted within one subpipeline. A subpipeline image
default or inheritance is not part of the model. Both existing local SIFs and
registry references with automatic fetching and caching are supported;
preparation placement, mounts, cache rules, and image identity are defined by
the [architecture](architecture-proposal.md).

## Existing gwf support

gwf **v2.1.1 already provides `Apptainer(image, flags=[], debug_mode=False)` and `Singularity(...)` executors**. Apptainer resolves the installed `apptainer` executable and returns the argument vector `apptainer [--debug] exec <flags> <image> <spec_path>`. It does not construct mounts, pull images separately, or manage a cache. The Apptainer docstring mistakenly mentions `singularity exec`; executable code correctly invokes Apptainer. [Pinned executor implementation](https://github.com/gwforg/gwf/blob/v2.1.1/src/gwf/executors.py)

The official versioned executor documentation supports a workflow default and per-target selection, but explicitly limits executors to the **Slurm backend**; settings have no effect with other backends. This is a material constraint for any promised local/backend-independent behavior. [Official executor documentation at v2.1.1](https://github.com/gwforg/gwf/blob/v2.1.1/docs/executors.rst)

The Slurm script starts the submission environment's Python with `-mgwf.exec`. That host-side wrapper deserializes the target, creates a temporary executable containing `#!/bin/bash`, `set -e`, and the **entire target spec**, then invokes the selected executor with `cwd=target.working_dir`. Therefore Python/gwf orchestration remains on the host; the script and its child commands run inside the container. The image needs `/bin/bash` and the computation's tools, while compute nodes need the host Python/gwf installation and Apptainer. [Slurm wrapper generation](https://github.com/gwforg/gwf/blob/v2.1.1/src/gwf/backends/slurm.py), [wrapper execution](https://github.com/gwforg/gwf/blob/v2.1.1/src/gwf/exec/__main__.py)

The wrapper forwards stdout/stderr, waits, and exits with the container subprocess's return code. Its Bash script enables `set -e`, **not `pipefail`**: preserving subprocess status does not make every failed command within a pipeline fail the script. Any stronger shell-failure policy remains a separate choice. [Wrapper source](https://github.com/gwforg/gwf/blob/v2.1.1/src/gwf/exec/__main__.py)

## What Nextflow's simplicity includes

Nextflow allows `apptainer.enabled = true` plus `process.container = '/path/image.sif'`; individual processes can declare their own image. It launches tasks through `apptainer exec` and automatically mounts required host paths. These mounts require administrator-enabled user bind control. [Apptainer integration](https://docs.seqera.io/nextflow/container/apptainer), [container directives](https://docs.seqera.io/nextflow/container)

Nextflow also distinguishes local images (`file://` forces local-only), remote image resolution, a writable image cache, and a library directory. On clusters, cached images must be accessible to compute nodes. Its `apptainer` configuration exposes mount, cache, environment-whitelist, extra-exec-option, and pull-timeout settings; `ociAutoPull` optionally delegates OCI acquisition/conversion to Apptainer instead of Nextflow's normal preparation. These are policies beyond simply adding an executor. [Image handling](https://docs.seqera.io/nextflow/container/apptainer), [configuration reference](https://docs.seqera.io/nextflow/reference/config/apptainer)

## Feasible authoring surface and runtime contract

**Inference about implementation:** gwflow can map each target's declarative image choice to that target's existing Apptainer executor. Target-specific selection supersedes the earlier subpipeline-default idea. Wrapping the whole Bash spec preserves pipelines, redirects, and multiple commands within the same container. It does not imply one persistent container across all internal steps. [gwf executor interface](https://github.com/gwforg/gwf/blob/v2.1.1/src/gwf/executors.py), [Apptainer exec](https://apptainer.org/docs/user/latest/cli/apptainer_exec.html)

For image-only authoring to work reliably, the execution layer must make the script, project helpers, work directory, declared inputs/references, and writable intermediate/output parent directories accessible. Binding the project alone cannot expose external inputs or symlink destinations. Resolve required symlink targets and preserve usable path mappings; arbitrary undeclared paths in shell text cannot be inferred reliably. These are gwflow design implications, not features already supplied by gwf's executor. Apptainer offers explicit `src:dest:ro/rw` binds and `--pwd`/`--cwd`; its `--workdir` flag instead controls containment storage. Defaults mount home, temporary directories, and usually the current directory, but site settings and symlinks affect these defaults. [Bind documentation](https://apptainer.org/docs/user/latest/bind_paths_and_mounts.html), [exec options](https://apptainer.org/docs/user/latest/cli/apptainer_exec.html), [Nextflow symlink caveat](https://docs.seqera.io/nextflow/container/apptainer)

## Image acquisition evidence and subsequent proposals

- **Existing local SIF:** uses a previously supplied artifact; image and data paths must exist on execution nodes. This can avoid image-fetch networking. The [architecture proposal](architecture-proposal.md#target-specific-apptainer-execution) proposes explicit local-path semantics: missing local files do not silently acquire registry meaning.
- **Registry URI:** Apptainer accepts `docker://` and `oras://` among other sources. OCI acquisition downloads layers and converts them into SIF; even `pull` performs a build internally for that conversion. This is distinct from creating a new software environment from a recipe. [Supported image sources](https://apptainer.org/docs/user/latest/cli/apptainer_exec.html), [OCI conversion](https://apptainer.org/docs/user/latest/docker_and_oci.html)
- **Placement/cache:** passing a remote URI straight through gwf causes acquisition on the execution node. Launch-side preparation would be extra behavior. Apptainer's own per-user cache defaults to `$HOME/.apptainer/cache`, is configurable with `APPTAINER_CACHEDIR`, and requires space; parallel remote pulls need suitable atomic-rename behavior. Local SIF preparation is the documented alternative. [Cache and temporary storage](https://apptainer.org/docs/user/latest/build_env.html)
- **Version policy:** Docker URI execution can contact the registry to check for changes even when cached. The architecture resolves and records identities, freezes cached references within the project, and requires image changes to be versioned deliberately; these policies require implementation validation. [Registry checks](https://apptainer.org/docs/user/latest/docker_and_oci.html)

No runtime installation, environment builds, network services, or persistent container orchestration is added by this design. Published images are downloaded and cached according to the separate architecture policy. Official current Apptainer documentation identifies itself as version 1.5. The gwf website was inaccessible during the source review, so its official pinned documentation and code were read directly from GitHub.
