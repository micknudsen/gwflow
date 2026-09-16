import os
from pathlib import Path

import pytest

from gwflow import execution_manifest, load, plan
from gwflow.evaluator import evaluate
from gwflow.runtime_records import current_attempt, current_attempt_path, receipt_path, success_receipt, write_execution_manifest, write_runtime_record
from test_planner import runtime_cli
from gwflow.runtime_records import job_association, job_tracking, write_tracking


def stamp(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("payload")
    os.utime(path, ns=(value, value))


def completed(tmp_path):
    stamp(tmp_path / "reads.txt", 10)
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    computation = result["computations"][0]
    target = computation["targets"][0]
    stamp(Path(target["outputs"][0]), 20)
    write_execution_manifest(tmp_path, execution_manifest(result, computation["identity"]))
    attempt = "attempt-1"
    write_tracking(tmp_path, job_tracking([job_association(computation["identity"], target["name"], attempt, "123")]))
    write_runtime_record(current_attempt_path(tmp_path, computation["identity"], target["name"]), current_attempt(computation["identity"], target["name"], attempt))
    write_runtime_record(receipt_path(tmp_path, computation["identity"], target["name"], attempt), success_receipt(computation["identity"], target["name"], attempt, [{"path": target["outputs"][0], "mtime_ns": 20}]))
    return result, computation, target


def test_completed_current_boundary_reuses_and_newer_input_recovers(tmp_path):
    result, computation, target = completed(tmp_path)
    assert evaluate(result)[0]["decision"] == "reuse"
    stamp(tmp_path / "reads.txt", 30)
    evaluated = evaluate(result)[0]
    assert evaluated["decision"] == "execute"
    assert evaluated["targets"][0]["reason"] == "newer-input"


def test_missing_required_evidence_or_retained_result_recovers(tmp_path):
    result, computation, target = completed(tmp_path)
    Path(target["outputs"][0]).unlink()
    assert evaluate(result)[0]["decision"] == "execute"
    completed(tmp_path)
    current_attempt_path(tmp_path, computation["identity"], target["name"]).unlink()
    assert evaluate(result)[0]["decision"] == "execute"


def test_active_status_precedes_missing_evidence(tmp_path):
    result, computation, target = completed(tmp_path)
    current_attempt_path(tmp_path, computation["identity"], target["name"]).unlink()
    assert evaluate(result, statuses={(computation["identity"], target["name"]): "running"})[0]["decision"] == "attach"


def test_missing_external_input_is_a_runtime_error(tmp_path):
    result, _, _ = completed(tmp_path)
    (tmp_path / "reads.txt").unlink()
    with pytest.raises(Exception, match="producerless external input"):
        evaluate(result)


def test_runtime_preview_reports_reuse_at_the_product_boundary(tmp_path):
    completed(tmp_path)
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr
    assert '"decision": "reuse"' in result.stdout
