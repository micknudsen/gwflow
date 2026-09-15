"""Phase 0 E5: real gwf runtime, fake Apptainer, and a disposable host envelope.

The fake records argv and executes Bash on the host. It does not implement images,
mounts, namespaces, pulling, cache coordination, or Slurm submission.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from gwf.core import Target
from gwf.executors import Apptainer, Bash, serialize

from experiments.phase0.live_target_envelope import EvidenceApptainer


FAKE_APPTAINER = r"""
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
image, script = args[-2:]
record = {
    "argv": args,
    "cwd": os.getcwd(),
    "target": os.environ.get("GWF_TARGET_NAME"),
    "forwarded_env": os.environ.get("PHASE0_FORWARD"),
    "script": Path(script).read_text(),
}
with open(os.environ["PHASE0_APPTAINER_LOG"], "a") as log:
    log.write(json.dumps(record) + "\n")
if "PHASE0_RUNTIME_FAILURE" in os.environ:
    sys.exit(int(os.environ["PHASE0_RUNTIME_FAILURE"]))
child_env = dict(os.environ, PHASE0_SELECTED_IMAGE=image)
# Deliberately no image validation, binding, cleanenv, or --pwd implementation.
sys.exit(subprocess.run([script], env=child_env).returncode)
"""


# Disposable outer-job probe, not the selected production executor.
HOST_ENVELOPE = r"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

config = json.loads(Path(sys.argv[1]).read_text())
result = subprocess.run([sys.executable, "-m", "gwf.exec", config["target_file"]])
if result.returncode:
    sys.exit(result.returncode)
missing = [path for path in config["outputs"] if not Path(path).exists()]
if missing:
    print("required outputs missing: " + repr(missing), file=sys.stderr)
    sys.exit(72)
receipt = Path(config["receipt"])
temporary = None
try:
    fd, temporary = tempfile.mkstemp(dir=receipt.parent, prefix=".receipt-")
    with os.fdopen(fd, "w") as stream:
        json.dump({"target": config["target"], "command_exit": result.returncode,
                   "host_image_marker": os.environ.get("PHASE0_SELECTED_IMAGE")}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, receipt)
    temporary = None
    directory = os.open(receipt.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except OSError as error:
    print("receipt publication failed: " + str(error), file=sys.stderr)
    sys.exit(73)
finally:
    if temporary is not None:
        os.unlink(temporary)
"""


@pytest.fixture
def execution_lab(tmp_path):
    """A host scratch directory and a deliberately fake executable on PATH."""
    work = tmp_path / "work with spaces"
    work.mkdir()
    scripts = tmp_path / "temporary scripts"
    scripts.mkdir()
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake = fake_bin / "apptainer"
    fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent(FAKE_APPTAINER))
    fake.chmod(0o700)
    log = tmp_path / "invocations.jsonl"
    environment = os.environ.copy()
    environment.update(
        PATH=str(fake_bin) + os.pathsep + environment.get("PATH", ""),
        TMPDIR=str(scripts),
        GWF_EXEC_WORKFLOW_ROOT=str(tmp_path),
        PHASE0_APPTAINER_LOG=str(log),
        PHASE0_FORWARD="declared-value",
    )
    environment.pop("GWF_EXEC_DEBUG_MODE", None)
    environment.pop("PHASE0_SELECTED_IMAGE", None)
    return {"root": tmp_path, "work": work, "env": environment, "log": log}


def make_target(lab, name, spec, executor, outputs=()):
    return Target(
        name=name,
        inputs=[],
        outputs=list(outputs),
        options={},
        group="alignment",
        working_dir=str(lab["work"]),
        executor=executor,
        spec=spec,
    )


def target_file(lab, target):
    path = lab["root"] / (target.name + ".target")
    with path.open("w") as stream:
        serialize(target, stream)
    return path


def run_target(lab, target, environment=None):
    return subprocess.run(
        [sys.executable, "-m", "gwf.exec", str(target_file(lab, target))],
        env=environment or lab["env"],
        cwd=lab["root"],
        text=True,
        capture_output=True,
        timeout=20,
    )


def run_envelope(lab, target, receipt):
    path = target_file(lab, target)
    envelope = lab["root"] / "host-envelope.py"
    envelope.write_text(textwrap.dedent(HOST_ENVELOPE))
    config = lab["root"] / "envelope.json"
    config.write_text(json.dumps({
        "target_file": str(path),
        "target": target.name,
        "outputs": [str(lab["work"] / output) for output in target.outputs],
        "receipt": str(receipt),
    }))
    return subprocess.run(
        [sys.executable, str(envelope), str(config)],
        env=lab["env"],
        cwd=lab["root"],
        text=True,
        capture_output=True,
        timeout=20,
    )


def invocations(lab):
    return [json.loads(line) for line in lab["log"].read_text().splitlines()]


def test_independent_images_and_same_image_targets(execution_lab):
    lab = execution_lab
    images = lab["root"] / "image placeholders"
    images.mkdir()
    selections = [("trim", "cutadapt"), ("align", "bwa"),
                  ("bam", "samtools"), ("align_again", "bwa")]
    for name, image_name in selections:
        image = images / (image_name + ".sif")
        image.touch()  # Empty placeholders, not runnable SIF images.
        spec = f'printf "%s\\n" "$PHASE0_SELECTED_IMAGE" > {name}.txt\n'
        target = make_target(lab, name, spec, Apptainer(str(image)), [name + ".txt"])
        result = run_target(lab, target)
        assert result.returncode == 0, result.stderr
        assert (lab["work"] / (name + ".txt")).read_text().strip() == str(image)
    records = invocations(lab)
    assert [(r["target"], Path(r["argv"][-2]).stem) for r in records] == selections


def test_full_bash_spec_flags_cwd_environment_and_script_lifetime(execution_lab):
    lab = execution_lab
    flags = ["--bind", "/external reference:/external reference:ro",
             "--bind", f"{lab['work']}:{lab['work']}:rw", "--pwd", str(lab["work"])]
    spec = textwrap.dedent("""\
        printf 'b\\na\\n' | sort > sorted.txt
        printf 'tail\\n' >> sorted.txt
        pwd > cwd.txt
        printf '%s:%s\\n' "$GWF_TARGET_NAME" "$PHASE0_FORWARD"
        printf 'diagnostic\\n' >&2
    """)
    target = make_target(lab, "whole_spec", spec,
                         Apptainer("selected image.sif", flags, debug_mode=True))
    result = run_target(lab, target)
    assert result.returncode == 0, result.stderr
    record, = invocations(lab)
    assert record["argv"][:-2] == ["--debug", "exec", *flags]
    assert record["argv"][-2] == "selected image.sif"
    assert record["script"] == "#!/bin/bash\n\nset -e\n\n" + spec
    assert Path(record["cwd"]).resolve() == lab["work"].resolve()
    assert record["forwarded_env"] == "declared-value"
    assert Path((lab["work"] / "cwd.txt").read_text().strip()).resolve() == lab["work"].resolve()
    assert (lab["work"] / "sorted.txt").read_text() == "a\nb\ntail\n"
    assert result.stdout == "whole_spec:declared-value\n"
    assert result.stderr == "diagnostic\n"
    assert not Path(record["argv"][-1]).exists()


def test_target_without_image_uses_host_bash(execution_lab):
    lab = execution_lab
    target = make_target(lab, "host", 'printf host > host.txt\n', Bash())
    result = run_target(lab, target)
    assert result.returncode == 0, result.stderr
    assert (lab["work"] / "host.txt").read_text() == "host"
    assert not lab["log"].exists()


@pytest.mark.parametrize("spec, expected", [
    ("printf partial > partial.txt\nexit 23\n", 23),
    ("false\nprintf unreachable > tail.txt\n", 1),
    ("false | cat\nprintf reachable > tail.txt\n", 0),
    ("set -o pipefail\nfalse | cat\nprintf unreachable > tail.txt\n", 1),
])
def test_gwf_shell_and_exit_semantics(execution_lab, spec, expected):
    lab = execution_lab
    target = make_target(lab, "shell_status", spec, Apptainer("placeholder.sif"))
    result = run_target(lab, target)
    assert result.returncode == expected, result.stderr
    assert (lab["work"] / "tail.txt").exists() == (expected == 0)


def test_runtime_start_failure_is_propagated(execution_lab):
    lab = execution_lab
    target = make_target(lab, "runtime_failure", "touch should_not_exist\n",
                         Apptainer("placeholder.sif"))
    environment = dict(lab["env"], PHASE0_RUNTIME_FAILURE="61")
    result = run_target(lab, target, environment)
    assert result.returncode == 61
    assert not (lab["work"] / "should_not_exist").exists()


def test_missing_apptainer_is_an_execution_error(execution_lab):
    lab = execution_lab
    target = make_target(lab, "missing_runtime", "true\n", Apptainer("placeholder.sif"))
    environment = dict(lab["env"], PATH="")
    result = run_target(lab, target, environment)
    assert result.returncode != 0
    assert "Could not find apptainer installation" in result.stderr


def test_stock_runtime_does_not_check_declared_outputs(execution_lab):
    lab = execution_lab
    target = make_target(lab, "missing_output", "true\n", Bash(), ["missing.txt"])
    result = run_target(lab, target)
    assert result.returncode == 0, result.stderr
    assert not (lab["work"] / "missing.txt").exists()


@pytest.mark.parametrize("image", ["absent-local.sif", "docker://example.invalid/tool:tag"])
def test_native_executor_forwards_unprepared_image_reference(execution_lab, image):
    """The fake intercepts the URI; this cannot access the registry or pull."""
    lab = execution_lab
    target = make_target(lab, "unprepared", "true\n", Apptainer(image))
    result = run_target(lab, target)
    assert result.returncode == 0, result.stderr
    record, = invocations(lab)
    assert record["argv"][-2] == image
    # Stock get_command does not supply the proposed preparer/preflight policy.


@pytest.mark.parametrize("case, expected", [
    ("success", 0), ("payload_failure", 29),
    ("missing_output", 72), ("receipt_failure", 73),
])
def test_host_envelope_checks_outputs_and_propagates_receipt_failure(execution_lab, case, expected):
    lab = execution_lab
    receipt = lab["root"] / "success-receipt.json"
    spec = 'printf "%s\\n" "$PHASE0_SELECTED_IMAGE" > result.txt\n'
    if case == "payload_failure":
        spec += "exit 29\n"
    if case == "missing_output":
        spec = "true\n"
    if case == "receipt_failure":
        receipt.mkdir()  # Real atomic replacement error, not a mocked exception.
    target = make_target(lab, "enveloped", spec, Apptainer("tool.sif"), ["result.txt"])
    result = run_envelope(lab, target, receipt)
    assert result.returncode == expected, result.stderr
    if case == "success":
        evidence = json.loads(receipt.read_text())
        assert evidence == {"target": "enveloped", "command_exit": 0, "host_image_marker": None}
        assert (lab["work"] / "result.txt").read_text() == "tool.sif\n"
    else:
        assert not receipt.is_file()
    if case == "missing_output":
        assert "required outputs missing" in result.stderr
    if case == "receipt_failure":
        assert "receipt publication failed" in result.stderr


def test_live_evidence_executor_encodes_option_looking_flag_values():
    executor = EvidenceApptainer(
        image="tool.sif",
        flags=("--bind", "/input:/input:ro", "--pwd", "/work"),
        outputs=("/work/result.txt",),
        receipt="/work/receipt.json",
        attempt="attempt-1",
    )

    command = executor.get_command("/tmp/target.sh", "/workflow")

    assert "--flag=--bind" in command
    assert "--flag=--pwd" in command
