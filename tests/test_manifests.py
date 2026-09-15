from copy import deepcopy
import json
import pytest
from gwflow import PlanError, load, manifest, plan, validate_manifest
from examples.manifests import main
from test_connections import by_occurrence
from test_planner import cli


@pytest.mark.parametrize("selector,bindings", [
    ("examples.one_file:main", {"source": "a"}),
    ("examples.file_list:main", {"reads": ["a", "b", "b"]}),
    ("examples.small_data:main", {"sample": {"id": 1.0}}),
    ("examples.resources:main", {"source": "a"}),
    ("examples.internal_graph:main", {"source": "a"}),
    ("examples.internal_graph:always", {"source": "a"}),
    ("examples.connections:main", {}), ("examples.whole_producer:multiple", {}),
    ("examples.target_images:main", {}), ("examples.manifests:main", {}),
])
def test_all_supported_forms_export_and_round_trip(tmp_path, selector, bindings):
    result = plan(load(selector), bindings, project=tmp_path)
    for c in result["computations"]:
        record = manifest(result, c["identity"])
        assert record["computation"]["descriptor"] == c["descriptor"]
        assert record["provenance"] == {"main": result["main"], "software": result["software"]}
        assert record["interpretation"] == {"definition_api": 1, "identity": 1}
        assert record["runtime_evaluation"] == "not evaluated"
        assert validate_manifest(json.loads(json.dumps(record))) is None
        record["computation"]["definition"]["version"] = "changed-copy"
        assert c["definition"]["version"] != "changed-copy"
    assert list(tmp_path.iterdir()) == []


def test_mixed_manifest_facts(tmp_path):
    result = plan(main, project=tmp_path)
    nodes = by_occurrence(result)
    producer = manifest(result, nodes["producer"]["identity"])["computation"]
    assert producer["input_interface"] == {"reads": "files", "sample": "data"}
    assert producer["computational_parameters"] == {"threshold": 5}
    assert len(producer["bindings"]["reads"]) == 2
    assert producer["bindings"]["sample"] == {"id": "sample-a"}
    assert producer["terminal_targets"] == ["fast", "host", "slow"]
    assert len(producer["internal_outputs"]) == 2
    assert {t["environment"]["kind"] for t in producer["targets"]} == {"local-sif", "registry", "host"}
    assert producer["targets"][0]["resources"] == {"memory_mb": 1024}
    consumer = manifest(result, nodes["consumer"]["identity"])["computation"]
    assert len(consumer["connections"]) == len(consumer["completion_obligations"]) == 1


@pytest.fixture
def record(tmp_path):
    result = plan(main, project=tmp_path)
    return manifest(result, by_occurrence(result)["producer"]["identity"])


def test_every_required_field_is_checked(record):
    for scope in ((), ("computation",), ("interpretation",), ("provenance",)):
        original = record
        for key in scope:
            original = original[key]
        for missing in original:
            bad = deepcopy(record)
            node = bad
            for key in scope:
                node = node[key]
            del node[missing]
            with pytest.raises(PlanError, match="manifest"):
                validate_manifest(bad)


@pytest.mark.parametrize("path,value", [
    (("schema_version",), 999), (("schema_version",), True), (("interpretation", "identity"), 2),
    (("runtime_evaluation",), "complete"), (("computation", "identity"), "0" * 64),
    (("computation", "descriptor", "identity_version"), 2),
    (("computation", "bindings", "sample"), {"different": "data"}),
    (("computation", "targets", 0, "always_run"), True),
    (("computation", "targets", 0, "name"), []),
    (("computation", "targets", 0, "environment", "path"), "/wrong/image.sif"),
    (("computation", "targets", 0, "resources"), {"image": "override"}),
    (("computation", "targets", 0, "dependencies"), ["missing"]),
    (("computation", "terminal_targets"), []),
    (("computation", "output_interface"), {"fast": "missing"}),
    (("computation", "work_dir"), "/wrong"),
    (("provenance", "software", "gwflow"), 3),
])
def test_invalid_records_are_rejected(record, path, value):
    node = record
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(PlanError):
        validate_manifest(record)


def test_command_manifest_export(tmp_path):
    result = cli(tmp_path, "examples.manifests:main", "--format", "manifests")
    assert result.returncode == 0, result.stderr
    records = json.loads(result.stdout)
    assert len(records) == 2
    for record in records:
        validate_manifest(record)


def test_explicit_edges_and_outputless_constraints_round_trip(tmp_path):
    from gwflow import MainPipeline, Subpipeline, Target
    def build(ctx):
        return [Target("a", "effect a"), Target("b", "effect b", depends_on=("a",))]
    result = plan(MainPipeline("test.main", "1", Subpipeline("test.explicit", "1", {}, {}, build)), project=tmp_path)
    record = manifest(result, result["computations"][0]["identity"])
    validate_manifest(json.loads(json.dumps(record)))
    assert record["computation"]["computational_edges"] == [{"producer": "a", "consumer": "b", "kind": "explicit"}]
    assert all(t["always_run"] for t in record["computation"]["targets"])
    record["computation"]["attempt"] = "fabricated"
    with pytest.raises(PlanError, match="expected fields"):
        validate_manifest(record)


def test_upstream_obligation_and_connection_validation(tmp_path):
    result = plan(main, project=tmp_path)
    record = manifest(result, by_occurrence(result)["consumer"]["identity"])
    bad = deepcopy(record)
    bad["computation"]["completion_obligations"][0]["terminal_targets"] = ["unknown"]
    with pytest.raises(PlanError, match="required members"):
        validate_manifest(bad)
    bad = deepcopy(record)
    bad["computation"]["connections"][0]["path"] = "/unrelated"
    with pytest.raises(PlanError, match="connection"):
        validate_manifest(bad)
