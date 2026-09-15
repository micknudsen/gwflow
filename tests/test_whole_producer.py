import json
from gwflow import plan
from examples.whole_producer import main, multiple
from test_connections import by_occurrence
from test_planner import cli


def test_parallel_terminal_obligation_is_separate_from_files(tmp_path):
    result = plan(main, project=tmp_path)
    nodes = by_occurrence(result)
    producer, consumer = nodes["producer"], nodes["consumer"]
    assert sum(len(c["targets"]) for c in result["computations"]) == 3
    assert consumer["targets"][0]["inputs"] == [producer["retained_outputs"]["fast"]]
    assert consumer["completion_obligations"] == [{
        "producer": producer["identity"], "condition": "whole-subpipeline completion",
        "required_targets": ["fast", "slow"], "terminal_targets": ["fast", "slow"], "evaluation": "not evaluated",
    }]
    assert len(result["composition_edges"]) == 1
    assert result["composition_edges"][0]["producer_target"] == "fast"
    assert producer["completion_obligations"] == []
    assert list(tmp_path.iterdir()) == []


def test_multiple_producers_and_fork_join(tmp_path):
    result = plan(multiple, project=tmp_path)
    nodes = by_occurrence(result)
    obligations = {o["producer"]: o for o in nodes["consumer"]["completion_obligations"]}
    assert len(obligations) == 2
    fork = obligations[nodes["fork"]["identity"]]
    assert fork["required_targets"] == ["a", "b", "c", "d"]
    assert fork["terminal_targets"] == ["d"]
    assert len(nodes["consumer"]["targets"][0]["inputs"]) == 2
    assert len(result["composition_edges"]) == 2


def test_obligations_command(tmp_path):
    result = cli(tmp_path, "examples.whole_producer:main")
    assert result.returncode == 0
    consumer = by_occurrence(json.loads(result.stdout))["consumer"]
    assert consumer["completion_obligations"][0]["terminal_targets"] == ["fast", "slow"]
    assert len(consumer["targets"][0]["inputs"]) == 1
