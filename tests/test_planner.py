import json
from pathlib import Path
import subprocess
import sys

import pytest
from gwflow import PlanError, load, plan


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


def test_command(tmp_path):
    result = cli(tmp_path, "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["computations"][0]["retained_outputs"]["copy"].endswith("copy.txt")
    for args in [("examples.one_file:main",), ("bad",), ("examples.one_file:main", "--bindings", "[]")]:
        result = cli(tmp_path, *args)
        assert result.returncode == 2
        assert "gwflow:" in result.stderr
