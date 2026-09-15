from dataclasses import replace
import json
import pytest
from gwflow import PlanError, Target, plan
from examples import internal_graph as fixtures
from test_planner import cli


def comp(root, definition=fixtures.main):
    return plan(definition, {"source": "missing"}, project=root)["computations"][0]


def test_fork_join_membership_and_parallel_endings(tmp_path):
    c = comp(tmp_path)
    targets = {t["name"]: t for t in c["targets"]}
    assert {n: t["dependencies"] for n, t in targets.items()} == {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
    assert all(t["computation"] == c["identity"] for t in targets.values())
    assert c["entry_targets"] == ["a"] and c["terminal_targets"] == ["d"]
    assert len(c["internal_outputs"]) == 3 and len(c["retained_outputs"]) == 1
    p = comp(tmp_path, fixtures.parallel_main)
    assert p["terminal_targets"] == ["fast", "slow"]
    assert p["computational_edges"] == []
    assert list(tmp_path.iterdir()) == []


def test_explicit_edges_and_outputless(tmp_path):
    def build(ctx):
        return [Target("a", "a"), Target("b", "b", depends_on=("a",)), Target("c", "c", depends_on=("b",))]
    definition = replace(fixtures.always, subpipeline=replace(fixtures.always.subpipeline, build=build))
    c = comp(tmp_path, definition)
    assert c["terminal_targets"] == ["c"]
    assert all(t["always_run"] and t["inputs"] == [] and t["outputs"] == [] for t in c["targets"])
    assert [e["kind"] for e in c["computational_edges"]] == ["explicit", "explicit"]


@pytest.mark.parametrize("definition,match", [(fixtures.cycle, "cycle.*a.*b"), (fixtures.duplicate, "ambiguous producer.*a, b")])
def test_graph_diagnostics(tmp_path, definition, match):
    with pytest.raises(PlanError, match=match):
        comp(tmp_path, definition)


@pytest.mark.parametrize("build,outputs,match", [
    (lambda c: [Target("a", "a", depends_on=("a",))], {}, "cycle.*a"),
    (lambda c: [Target("a", "a", depends_on=("missing",))], {}, "unknown target.*missing"),
    (lambda c: [Target("a", "a", inputs=(c.path("missing"),))], {}, "unresolved internal input"),
    (lambda c: [Target("a", "a"), Target("a", "b")], {}, "duplicate target"),
    (lambda c: [Target("a", "a", outputs=("/external/file",))], {}, "outside owned"),
    (lambda c: [Target("a", "a", outputs=(c.path("a"), c.path("a/b")))], {}, "path collision"),
    (lambda c: [Target("a", "a")], {"missing": "file"}, "retained output.*no target producer"),
    (lambda c: [Target("a", "a")], {"bad": "../escape"}, "relative and contained"),
])
def test_invalid_references_paths_and_ownership(tmp_path, build, outputs, match):
    definition = replace(fixtures.main, subpipeline=replace(fixtures.main.subpipeline, build=build, outputs=outputs))
    with pytest.raises(PlanError, match=match):
        comp(tmp_path, definition)


def test_graph_command(tmp_path):
    good = cli(tmp_path, "examples.internal_graph:parallel_main", "--bindings", '{"source":"x"}')
    assert good.returncode == 0
    assert json.loads(good.stdout)["computations"][0]["terminal_targets"] == ["fast", "slow"]
    for entry in ("cycle", "duplicate"):
        bad = cli(tmp_path, f"examples.internal_graph:{entry}", "--bindings", '{"source":"x"}')
        assert bad.returncode == 2


@pytest.mark.parametrize("change", [{"inputs": []}, {"outputs": {1: "a"}}, {"parameters": []}, {"version": None}])
def test_invalid_definition_interfaces(tmp_path, change):
    definition = replace(fixtures.main, subpipeline=replace(fixtures.main.subpipeline, **change))
    with pytest.raises(PlanError, match="interface|parameters|version"):
        comp(tmp_path, definition)
