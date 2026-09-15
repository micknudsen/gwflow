from dataclasses import replace
import json
import pytest
from examples.small_data import main, revised
from gwflow import PlanError, plan
from test_planner import cli


def comp(root, value, definition=main):
    return plan(definition, {"sample": value}, project=root)["computations"][0]


def test_small_data_identity_and_parameters(tmp_path):
    a = comp(tmp_path, {"id": "A", "lanes": [1, 2]})
    assert comp(tmp_path, {"lanes": [1, 2], "id": "A"}) == a
    assert a["computational_parameters"] == {"threshold": 5}
    assert a["bindings"]["sample"]["id"] == "A"
    values = [None, False, 0, 0.0, -0.0, True, 1, 1.0, "1", [], {}, [1], [1, 1], 2**53 - 1]
    assert len({comp(tmp_path, v)["identity"] for v in values}) == len(values)
    assert comp(tmp_path, "A", revised)["identity"] != comp(tmp_path, "A")["identity"]
    with pytest.raises(PlanError, match="unknown.*threshold"):
        plan(main, {"sample": "A", "threshold": 100}, project=tmp_path)
    bad = replace(main, subpipeline=replace(main.subpipeline, inputs={"threshold": "data"}))
    with pytest.raises(PlanError, match="parameters.*separate"):
        plan(bad, {"threshold": 2}, project=tmp_path)


@pytest.mark.parametrize("value", [2**53, float("nan"), float("inf"), (1,), {1: "x"}, {1}, b"bytes", "x" * 16383, json.loads("[" * 17 + "0" + "]" * 17)])
def test_invalid_data(tmp_path, value):
    with pytest.raises(PlanError, match="sample.*small data"):
        comp(tmp_path, value)


def test_size_boundary_and_input_copy(tmp_path):
    value = {"a": [1]}
    result = comp(tmp_path, value)
    value["a"].append(2)
    assert result["bindings"]["sample"] == {"a": [1]}
    assert comp(tmp_path, "x" * 16382)["bindings"]["sample"] == "x" * 16382


def test_data_command(tmp_path):
    good = cli(tmp_path, "examples.small_data:main", "--bindings", '{"sample":"A"}')
    assert good.returncode == 0
    assert json.loads(good.stdout)["computations"][0]["computational_parameters"] == {"threshold": 5}
    bad = cli(tmp_path, "examples.small_data:main", "--bindings", '{"sample":"A","threshold":2}')
    assert bad.returncode == 2 and "unknown" in bad.stderr
