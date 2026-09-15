"""Local execution-to-reuse integration: real gwf/Bash, no Slurm or containers.

Reuse decisions use E1's unchanged gwf scheduler with its experimental evidence
hook/filesystem view. All accepted receipts here come from executed payloads.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from gwf.executors import serialize

from test_freshness_recovery import Fixture, SHAPES


ENVELOPE = r"""
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
try:
    outputs = {path: Path(path).stat().st_mtime for path in config["outputs"]}
except OSError as error:
    print("required output check failed: " + str(error), file=sys.stderr)
    sys.exit(72)
temporary = None
try:
    fd, temporary = tempfile.mkstemp(dir=config["staging_directory"], prefix=".receipt-")
    with os.fdopen(fd, "w") as stream:
        json.dump({"attempt": config["attempt"], "outputs": outputs}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, config["receipt"])
    temporary = None
    directory = os.open(Path(config["receipt"]).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except OSError as error:
    print("required receipt publication failed: " + str(error), file=sys.stderr)
    sys.exit(73)
finally:
    if temporary is not None:
        os.unlink(temporary)
"""


@pytest.fixture
def unexecuted_chain(tmp_path):
    fixture = Fixture(tmp_path, *SHAPES["chain"])
    # Fixture supplies the expected manifest/graph. Remove every synthetic
    # output and assumed receipt before exercising any execution or reuse.
    for target in fixture.targets:
        fixture.receipt(target.name).unlink()
        for path in target.flattened_outputs():
            Path(path).unlink()
    for target, source, output in zip(fixture.targets, ["x", "a.out", "b.out"],
                                      ["a.out", "b.out", "c.out"]):
        target.spec = (f"cat {source} > {output}\n"
                       f"printf '{target.name}\\n' >> {output}\n"
                       f"printf '{target.name}\\n' >> executed.log\n")
    assert fixture.valid_evidence() == {}
    assert not fixture.reusable()
    return fixture


def run_selected(fixture, names, *, receipt_failure=None):
    """Execute the scheduler-selected sequence locally, stopping on failure."""
    envelope = fixture.root / "execution-envelope.py"
    envelope.write_text(ENVELOPE)
    environment = dict(os.environ, GWF_EXEC_WORKFLOW_ROOT=str(fixture.root))
    environment.pop("GWF_EXEC_DEBUG_MODE", None)
    results = {}
    for name in names:
        target = next(target for target in fixture.targets if target.name == name)
        # Invalidate the previous proof before this attempt executes.
        fixture.expected_attempts[name] += "-next"
        fixture.receipt(name).unlink(missing_ok=True)
        target_file = fixture.root / f"{name}.target"
        with target_file.open("w") as stream:
            serialize(target, stream)
        staging = fixture.meta if name != receipt_failure else fixture.meta / "absent-directory"
        config = fixture.root / f"{name}.execution.json"
        config.write_text(json.dumps({
            "target_file": str(target_file), "outputs": list(target.flattened_outputs()),
            "attempt": fixture.expected_attempts[name], "receipt": str(fixture.receipt(name)),
            "staging_directory": str(staging),
        }))
        result = subprocess.run(
            [sys.executable, str(envelope), str(config)], env=environment,
            cwd=fixture.root, capture_output=True, text=True, timeout=20,
        )
        results[name] = result
        if result.returncode:
            break
        # A reported success must already have published compatible evidence.
        assert name in fixture.valid_evidence()
    return results


def planned_names(fixture):
    return [name for name, _ in fixture.decisions(evidence=True)[1]]


def execute_initial_chain(fixture):
    assert planned_names(fixture) == ["a", "b", "c"]
    results = run_selected(fixture, planned_names(fixture))
    assert {name: result.returncode for name, result in results.items()} == {
        "a": 0, "b": 0, "c": 0,
    }, {name: result.stderr for name, result in results.items()}
    assert (fixture.root / "c.out").read_text() == "fixturea\nb\nc\n"
    assert set(fixture.valid_evidence()) == {"a", "b", "c"}


def test_executed_chain_receipts_allow_reuse_after_cleanup(unexecuted_chain):
    fixture = unexecuted_chain
    execute_initial_chain(fixture)
    for target in fixture.targets:
        recorded = fixture.valid_evidence()[target.name]
        assert recorded == {path: Path(path).stat().st_mtime
                            for path in target.flattened_outputs()}
    fixture.cleanup()
    assert fixture.reusable()
    assert fixture.decisions(boundary=True, evidence=True)[1] == []
    assert not (fixture.root / "a.out").exists()
    assert not (fixture.root / "b.out").exists()
    assert (fixture.root / "executed.log").read_text() == "a\nb\nc\n"


@pytest.mark.parametrize("damage", ["retained_output", "required_receipt"])
def test_loss_after_cleanup_physically_reexecutes_prerequisites(unexecuted_chain, damage):
    fixture = unexecuted_chain
    execute_initial_chain(fixture)
    fixture.cleanup()
    if damage == "retained_output":
        (fixture.root / "c.out").unlink()
    else:
        fixture.receipt("b").unlink()
    assert not fixture.reusable()
    assert planned_names(fixture) == ["a", "b", "c"]
    previous_attempts = fixture.expected_attempts.copy()
    results = run_selected(fixture, planned_names(fixture))
    assert all(result.returncode == 0 for result in results.values())
    assert all(fixture.expected_attempts[name] != previous_attempts[name] for name in results)
    assert all(Path(path).exists() for target in fixture.targets for path in target.outputs)
    assert (fixture.root / "c.out").read_text() == "fixturea\nb\nc\n"
    assert (fixture.root / "executed.log").read_text() == "a\nb\nc\na\nb\nc\n"
    fixture.cleanup()
    assert fixture.reusable()


@pytest.mark.parametrize("failure,code", [("payload", 31), ("output", 72), ("receipt", 73)])
def test_failed_terminal_cannot_certify_boundary_from_files(unexecuted_chain, failure, code):
    fixture = unexecuted_chain
    terminal = fixture.targets[-1]
    if failure == "payload":
        terminal.spec += "exit 31\n"
    elif failure == "output":
        terminal.spec = "true\n"
    results = run_selected(fixture, planned_names(fixture),
                           receipt_failure="c" if failure == "receipt" else None)
    assert {name: result.returncode for name, result in results.items()} == {
        "a": 0, "b": 0, "c": code,
    }
    assert set(fixture.valid_evidence()) == {"a", "b"}
    assert not fixture.receipt("c").exists()
    assert not fixture.reusable()
    assert planned_names(fixture) == ["c"]  # Successful physical prerequisites survive.
    if failure != "output":
        assert (fixture.root / "c.out").exists()
        assert fixture.decisions()[1] == []  # Ordinary file checks alone would skip it.
    # Simulate external deletion; approved cleanup would reject this incomplete boundary.
    fixture.cleanup()
    assert not fixture.reusable()
    assert planned_names(fixture) == ["a", "b", "c"]
