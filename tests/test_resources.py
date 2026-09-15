import json
import pytest
from gwflow import PlanError, plan
from examples.resources import main
from examples.composition import repeated
from test_planner import cli


def test_neutral_resources_preserve_identity(tmp_path):
    a = plan(main, {"source": "a"}, project=tmp_path)["computations"][0]
    changed = {"memory_mb": 2048, "walltime_seconds": 120, "partition": "normal", "account": "lab"}
    b = plan(main, {"source": "a"}, project=tmp_path, resources={"main": {"copy": changed}})["computations"][0]
    assert a["identity"] == b["identity"] and a["result_dir"] == b["result_dir"]
    assert a["targets"][0]["command"] == b["targets"][0]["command"]
    assert a["targets"][0]["resources"] == {"memory_mb": 1024, "walltime_seconds": 60}
    assert b["targets"][0]["resources"] == changed
    assert a["descriptor"] == b["descriptor"]


@pytest.mark.parametrize("override", [{"command": "other"}, {"parameters": {}}, {"image": "x"}, {"outputs": []}, {"memory_mb": True}, {"memory_mb": 0}, {"walltime_seconds": -1}, {"partition": ""}, {"account": "a b"}, []])
def test_invalid_operational_overrides(tmp_path, override):
    with pytest.raises(PlanError, match="resource"):
        plan(main, {"source": "a"}, project=tmp_path, resources={"main": {"copy": override}})


def test_invalid_scope_and_conflicting_shared_requests(tmp_path):
    for override in ({"unknown": {}}, {"main": {"unknown": {}}}):
        with pytest.raises(PlanError, match="existing"):
            plan(main, {"source": "a"}, project=tmp_path, resources=override)
    with pytest.raises(PlanError, match="conflicting resources"):
        plan(repeated, project=tmp_path, resources={"again": {"copy": {"memory_mb": 4}}})


def test_resources_command(tmp_path):
    good = cli(tmp_path, "examples.resources:main", "--bindings", '{"source":"a"}', "--resources", '{"main":{"copy":{"memory_mb":2048}}}')
    assert good.returncode == 0
    assert json.loads(good.stdout)["computations"][0]["targets"][0]["resources"]["memory_mb"] == 2048
    bad = cli(tmp_path, "examples.resources:main", "--bindings", '{"source":"a"}', "--resources", '{"main":{"copy":{"command":"x"}}}')
    assert bad.returncode == 2 and "unsupported resource" in bad.stderr
