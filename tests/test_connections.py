from dataclasses import replace
import json
import pytest
from gwflow import MainPipeline, OutputRef, PlanError, Use, plan
from examples import connections as fixture
from examples.one_file import copy_file
from test_planner import cli


def by_occurrence(result):
    return {name: next(c for c in result["computations"] if c["identity"] == item["identity"]) for name, item in result["main"]["occurrences"].items()}


def test_transitive_identity_and_unrelated_branch(tmp_path):
    a = plan(fixture.main, project=tmp_path)
    old = by_occurrence(a)
    new = by_occurrence(plan(fixture.revised, project=tmp_path))
    assert all(old[n]["identity"] != new[n]["identity"] for n in ("producer", "consumer", "report"))
    assert old["independent"]["identity"] == new["independent"]["identity"]
    assert [c["identity"] for c in plan(replace(fixture.main, version="main2"), project=tmp_path)["computations"]] == [c["identity"] for c in a["computations"]]
    consumer = old["consumer"]
    assert consumer["bindings"]["source"] == old["producer"]["retained_outputs"]["result"]
    assert consumer["descriptor"]["bindings"]["source"] == {"kind": "output", "computation": old["producer"]["identity"], "output": "result"}
    assert consumer["whole_producer_dependencies"] == [old["producer"]["identity"]]
    assert len(a["composition_edges"]) == 2
    assert list(tmp_path.iterdir()) == []


def test_expose_previously_private_output(tmp_path):
    with pytest.raises(PlanError, match="producer.*no retained output.*a.*private"):
        plan(fixture.private, project=tmp_path)
    exposed = by_occurrence(plan(fixture.exposed, project=tmp_path))
    assert exposed["consumer"]["bindings"]["source"] == exposed["producer"]["retained_outputs"]["a"]


@pytest.mark.parametrize("kind", ["retained", "internal", "unlisted", "list", "builder"])
def test_raw_path_bypasses_are_rejected(tmp_path, kind):
    p = by_occurrence(plan(fixture.main, project=tmp_path))["producer"]
    path = p["retained_outputs"]["result"] if kind == "retained" else p["work_dir"] + "/a"
    if kind == "unlisted":
        path = p["work_dir"] + "/not-declared"
    consumer = copy_file
    binding = {"source": path}
    if kind == "list":
        from examples.file_list import main
        consumer, binding = main.subpipeline, {"reads": [path]}
    if kind == "builder":
        from gwflow import Target
        def build(ctx):
            return [Target("copy", "copy", (path,), (ctx.path("copy.txt"),))]
        consumer, binding = replace(copy_file, build=build), {"source": "unrelated"}
    definition = MainPipeline("test.raw", "1", uses={"producer": fixture.main.uses["producer"], "consumer": Use(consumer, binding)})
    with pytest.raises(PlanError, match="raw path.*producer.*retained-output interface"):
        plan(definition, project=tmp_path)


@pytest.mark.parametrize("refs,match", [({"a": OutputRef("a", "copy")}, "cycle.*a"), ({"a": OutputRef("b", "copy"), "b": OutputRef("a", "copy")}, "cycle"), ({"a": OutputRef("missing", "copy")}, "unknown producer"), ({"a": OutputRef("b", "missing"), "b": "file"}, "no retained output")])
def test_composition_reference_errors(tmp_path, refs, match):
    main = MainPipeline("test.refs", "1", uses={n: Use(copy_file, {"source": ref}) for n, ref in refs.items()})
    with pytest.raises(PlanError, match=match):
        plan(main, project=tmp_path)


def test_command_connections_and_boundary_error(tmp_path):
    good = cli(tmp_path, "examples.connections:main")
    assert good.returncode == 0
    assert len(json.loads(good.stdout)["composition_edges"]) == 2
    bad = cli(tmp_path, "examples.connections:private")
    assert bad.returncode == 2 and "private" in bad.stderr


def test_equivalent_producer_aliases_share_consumer_identity(tmp_path):
    main = replace(fixture.main, uses={**fixture.main.uses,
        "producer_alias": fixture.main.uses["producer"],
        "consumer_alias": Use(copy_file, {"source": OutputRef("producer_alias", "result")})})
    result = plan(main, project=tmp_path)
    members = by_occurrence(result)
    assert members["consumer"]["identity"] == members["consumer_alias"]["identity"]
    assert members["producer"]["identity"] == members["producer_alias"]["identity"]
    reordered = replace(main, uses=dict(reversed(list(main.uses.items()))))
    assert plan(reordered, project=tmp_path) == result
