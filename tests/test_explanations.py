import json
from pathlib import Path
from gwflow import manifest, plan, validate_manifest
from examples.explanations import main, main_changed, upstream_changed, outputless
from test_connections import by_occurrence
from test_planner import cli


def facts(comp):
    return {f["code"]: f["basis"] for f in comp["explanation"]["identity_facts"]}


def test_paired_identity_facts(tmp_path):
    original = by_occurrence(plan(main, project=tmp_path))
    main_only = by_occurrence(plan(main_changed, project=tmp_path))
    upstream = by_occurrence(plan(upstream_changed, project=tmp_path))
    for name, comp in original.items():
        assert comp["identity"] == main_only[name]["identity"]
        assert facts(comp)["named-binding-identity"] == facts(main_only[name])["named-binding-identity"]
        assert facts(comp)["provenance-only-versions"]["main"]["version"] != facts(main_only[name])["provenance-only-versions"]["main"]["version"]
    assert facts(original["producer"])["definition-identity"] != facts(upstream["producer"])["definition-identity"]
    assert facts(original["consumer"])["upstream-identity"] != facts(upstream["consumer"])["upstream-identity"]
    assert original["independent"]["identity"] == upstream["independent"]["identity"]


def test_no_completion_claim_from_payloads_or_export(tmp_path):
    before = plan(main, project=tmp_path)
    for c in before["computations"]:
        for path in c["retained_outputs"].values():
            payload = Path(path)
            payload.parent.mkdir(parents=True, exist_ok=True)
            payload.write_text("surviving bytes")
        record = manifest(before, c["identity"])
        validate_manifest(record)
        (tmp_path / (c["identity"] + ".json")).write_text(json.dumps(record))
    assert plan(main, project=tmp_path) == before
    for c in before["computations"]:
        reuse = c["explanation"]["prospective_reuse"]
        assert reuse["outcome"] == "undetermined"
        assert {v["code"] for v in reuse["conditions"]} == {"required-completion-evidence", "retained-output-validity", "target-level-freshness", "available-scheduler-state"}
        assert all(v["evaluation"] == "not evaluated" for v in reuse["conditions"])


def test_outputless_and_whole_producer_constraints(tmp_path):
    c = plan(outputless, {"source": "reads.txt"}, project=tmp_path)["computations"][0]
    constraints = {v["code"]: v["basis"] for v in c["explanation"]["constraints"]}
    assert constraints["outputless-always-run"] == ["notify"]
    assert c["explanation"]["prospective_reuse"]["outcome"] == "undetermined"
    consumer = by_occurrence(plan(main, project=tmp_path))["consumer"]
    assert consumer["explanation"]["constraints"][0]["basis"] == consumer["completion_obligations"]


def test_command_explanation(tmp_path):
    result = cli(tmp_path, "examples.explanations:main")
    assert result.returncode == 0
    for c in json.loads(result.stdout)["computations"]:
        assert c["explanation"]["prospective_reuse"]["outcome"] == "undetermined"
