import json
import pytest
from gwflow import PlanError, plan
from examples.file_list import main
from test_planner import cli


def comp(root, reads):
    return plan(main, {"reads": reads}, project=root)["computations"][0]


def test_order_duplicates_empty_and_paths(tmp_path):
    a = comp(tmp_path, ["a", "b"])
    assert comp(tmp_path, (tmp_path / "a", "x/../b")) == a
    assert a["bindings"]["reads"] == [str(tmp_path / "a"), str(tmp_path / "b")]
    variants = [[], ["a"], ["b", "a"], ["a", "b", "b"], ["a", "b", "c"], ["a", "c"]]
    assert len({a["identity"], *(comp(tmp_path, v)["identity"] for v in variants)}) == 7
    assert comp(tmp_path, ["/external/file"])["descriptor"]["bindings"]["reads"]["items"][0]["scope"] == "external"
    (tmp_path / "a").write_text("payload")
    assert comp(tmp_path, ["a", "b"]) == a


@pytest.mark.parametrize("value,match", [("a", "reads.*finite file list"), (["a", 7], "reads.*element 1.*file path"), ([[]], "reads.*element 0"), ([None], "reads.*element 0")])
def test_invalid_lists(tmp_path, value, match):
    with pytest.raises(PlanError, match=match):
        comp(tmp_path, value)
    with pytest.raises(PlanError, match="missing.*reads"):
        plan(main, {}, project=tmp_path)


def test_list_command(tmp_path):
    result = cli(tmp_path, "examples.file_list:main", "--bindings", '{"reads":["a","b"]}')
    assert result.returncode == 0
    assert len(json.loads(result.stdout)["computations"][0]["bindings"]["reads"]) == 2
    bad = cli(tmp_path, "examples.file_list:main", "--bindings", '{"reads":["a",3]}')
    assert bad.returncode == 2 and "element 1" in bad.stderr
