import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest
from gwflow import PlanError, load, plan
from examples.portable_slurm import PortableSlurm


def test_import_plan_without_files_or_execution(tmp_path):
    result = plan(load("examples.one_file:main"), {"source": "missing.txt"}, project=tmp_path)
    comp = result["computations"][0]
    assert result["main"]["version"] == "1"
    assert result["software"]["gwflow"]
    assert comp["definition"]["name"] == "examples.copy"
    assert comp["definition"]["package"]["version"] == "0.1.dev0"
    assert comp["bindings"]["source"] == str(tmp_path / "missing.txt")
    assert comp["targets"][0]["command"].startswith("cp ")
    assert comp["retained_outputs"]["copy"] in comp["targets"][0]["outputs"]
    assert result["runtime_evaluation"] == "not evaluated"
    assert result["external_input_existence"] == "not evaluated"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bindings,match", [({}, "missing.*source"), ({"source": "x", "extra": "y"}, "unknown.*extra"), ({"source": 1}, "source.*file path")])
def test_invalid_bindings(tmp_path, bindings, match):
    with pytest.raises(PlanError, match=match):
        plan(load("examples.one_file:main"), bindings, project=tmp_path)


@pytest.mark.parametrize("selector", ["bad", "missing_module_123:main", "examples.one_file:missing", "examples.one_file:copy"])
def test_load_errors(selector):
    with pytest.raises(PlanError, match="definition"):
        load(selector)


def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "gwflow", "plan", *args, "--project", str(tmp_path)], text=True, capture_output=True)


def runtime_cli(tmp_path, *args):
    # Seeded evidence tests explicitly model successfully expired accounting.
    # Never query a real cluster for their synthetic job IDs.
    with tempfile.TemporaryDirectory(prefix="gwflow-test-scheduler-") as root:
        scheduler = PortableSlurm(Path(root) / "scheduler")
        return scheduler.command("run", *args, "--project", str(tmp_path))


def test_command(tmp_path):
    result = cli(tmp_path, "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["computations"][0]["retained_outputs"]["copy"].endswith("copy.txt")
    for args in [("examples.one_file:main",), ("bad",), ("examples.one_file:main", "--bindings", "[]")]:
        result = cli(tmp_path, *args)
        assert result.returncode == 2
        assert "gwflow:" in result.stderr


def test_runtime_preview_is_read_only_and_structured(tmp_path):
    source = tmp_path / "reads.txt"
    source.write_text("input\n")
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert preview["kind"] == "runtime-preview"
    assert preview["runtime_preview_revision"] == 1
    computation = preview["computations"][0]
    assert computation["decision"] == "execute"
    assert computation["reason"]["code"] == "no-runtime-state"
    assert computation["job_ids"] == []
    assert any(item["kind"] == "input-file" and item["path"] == str(source) for item in computation["evidence"])
    assert computation["targets"][0]["decision"] == "execute"
    assert list(tmp_path.iterdir()) == [source]
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_runtime_preview_rejects_images_without_side_effects(tmp_path):
    result = runtime_cli(tmp_path, "--dry-run", "examples.target_images:main")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "host-only" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_missing_external_input_fails_submission_before_any_job_is_accepted(tmp_path):
    result = runtime_cli(tmp_path, "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["outcome"] == "error"
    assert report["reason"]["code"] == "missing-external-input"
    assert report["accepted_job_ids"] == []
    assert "missing producerless external input" in result.stderr
    assert not (tmp_path / ".gwflow" / "command-guard").exists()
    assert not (tmp_path / ".gwflow" / "runtime").exists()
