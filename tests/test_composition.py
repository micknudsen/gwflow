from dataclasses import replace
import json
import pytest
from examples import composition
from examples.one_file import copy_file
from gwflow import DefinitionRef, MainPipeline, PlanError, Use, plan
from test_planner import cli


def ids(root, main):
    return {n: c["identity"] for n, c in plan(main, project=root)["main"]["occurrences"].items()}


def test_composition_and_repeated_computations(tmp_path):
    a = ids(tmp_path, composition.main)
    assert len(set(a.values())) == 3
    assert a == ids(tmp_path, composition.main_only)
    assert a == ids(tmp_path, replace(composition.main, uses=dict(reversed(list(composition.main.uses.items())))))
    changed = ids(tmp_path, composition.report_changed)
    assert changed["sample_a"] == a["sample_a"] and changed["sample_b"] == a["sample_b"]
    assert changed["report"] != a["report"]
    repeated = plan(composition.repeated, project=tmp_path)
    assert len(repeated["computations"]) == 3
    assert ids(tmp_path, composition.repeated)["again"] == a["sample_a"]
    shared = next(c for c in repeated["computations"] if "again" in c["occurrences"])
    assert shared["occurrences"] == ["again", "sample_a"]
    assert len({c["result_dir"] for c in repeated["computations"]}) == 3


@pytest.mark.parametrize("definition,match", [(composition.unavailable, "requested.*99"), (MainPipeline("x", "1", uses={"x": Use(None)}), "unresolved"), (MainPipeline("x", "1", uses={"x": Use(DefinitionRef("missing:sub", "x.y", "1"))}), "cannot load")])
def test_definition_errors(tmp_path, definition, match):
    with pytest.raises(PlanError, match=match):
        plan(definition, project=tmp_path)


def test_visible_conflicts_and_binding_overrides(tmp_path):
    conflict = replace(copy_file, outputs={"other": "other.txt"})
    main = MainPipeline("test.main", "1", uses={"a": Use(copy_file, {"source": "a"}), "b": Use(conflict, {"source": "b"})})
    with pytest.raises(PlanError, match="conflicting immutable.*examples.copy@1"):
        plan(main, project=tmp_path)
    result = plan(composition.main, {"sample_a": {"source": "different"}}, project=tmp_path)
    assert result["main"]["occurrences"]["sample_a"]["identity"] != ids(tmp_path, composition.main)["sample_a"]
    with pytest.raises(PlanError, match="unknown occurrences"):
        plan(composition.main, {"typo": {}}, project=tmp_path)


def test_composition_command(tmp_path):
    good = cli(tmp_path, "examples.composition:repeated")
    assert good.returncode == 0
    assert len(json.loads(good.stdout)["main"]["occurrences"]) == 4
    bad = cli(tmp_path, "examples.composition:unavailable")
    assert bad.returncode == 2 and "requested" in bad.stderr
