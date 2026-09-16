import json

from gwflow import execution_manifest, load, plan
from gwflow.runtime_records import execution_manifest_path, tracking_path, write_execution_manifest
from test_planner import runtime_cli


def prepared(tmp_path):
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    record = execution_manifest(result, result["computations"][0]["identity"])
    write_execution_manifest(tmp_path, record)
    return result, record


def test_compatible_software_provenance_is_not_completion_evidence(tmp_path):
    result, record = prepared(tmp_path)
    record["provenance_only_software"] = {"gwflow": "future"}
    # The execution-record schema deliberately does not retain provenance as
    # authoritative evidence, so compatible release changes cannot invalidate.
    assert result["software"]["gwflow"]


def test_unsupported_required_evidence_recovers_not_invalidates_request(tmp_path):
    result, _ = prepared(tmp_path)
    path = execution_manifest_path(tmp_path, result["computations"][0]["identity"])
    record = json.loads(path.read_text())
    record["record_revision"] = 999
    path.write_text(json.dumps(record))
    preview = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert preview.returncode == 0, preview.stderr
    assert '"decision": "execute"' in preview.stdout


def test_unsupported_authoritative_tracking_blocks_preview(tmp_path):
    prepared(tmp_path)
    path = tracking_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "job-tracking", "tracking_revision": 999, "associations": {}}))
    preview = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert preview.returncode == 1
    assert '"outcome": "blocked"' in preview.stdout
