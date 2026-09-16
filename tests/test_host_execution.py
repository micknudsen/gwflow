from pathlib import Path

from gwflow import load, plan
from gwflow.host_execution import OUTPUT_CHECK_FAILURE, RECEIPT_PUBLICATION_FAILURE, execute
from gwflow.runtime_records import current_attempt_path, read_runtime_record, receipt_path


def target(tmp_path, command):
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    computation = result["computations"][0]
    item = dict(computation["targets"][0], command=command)
    (tmp_path / "reads.txt").write_text("input")
    return computation, item


def test_host_execution_fences_then_receipts_success(tmp_path):
    computation, item = target(tmp_path, f"cp {tmp_path}/reads.txt {tmp_path}/results/{'x'}")
    # Use the actual declared output, not an ad-hoc product path.
    item["command"] = f"cp {tmp_path}/reads.txt {item['outputs'][0]}"
    result = execute(tmp_path, computation, item, "attempt-1")
    assert result.returncode == 0
    assert read_runtime_record(current_attempt_path(tmp_path, computation["identity"], item["name"]))["attempt"] == "attempt-1"
    receipt = read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "attempt-1"))
    assert receipt["outputs"][0]["path"] == item["outputs"][0]
    assert result.stdout.exists() and result.stderr.exists()


def test_failed_payload_and_missing_output_do_not_publish_receipts(tmp_path):
    computation, item = target(tmp_path, "true; exit 29")
    failed = execute(tmp_path, computation, item, "attempt-1")
    assert failed.returncode == 29
    assert read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "attempt-1")) is None
    computation, item = target(tmp_path, "true")
    missing = execute(tmp_path, computation, item, "attempt-2")
    assert missing.returncode == OUTPUT_CHECK_FAILURE
    assert read_runtime_record(receipt_path(tmp_path, computation["identity"], item["name"], "attempt-2")) is None


def test_receipt_publication_failure_fails_the_job(tmp_path):
    computation, item = target(tmp_path, "true")
    item["command"] = f"cp {tmp_path}/reads.txt {item['outputs'][0]}"
    path = receipt_path(tmp_path, computation["identity"], item["name"], "attempt-3")
    path.parent.mkdir(parents=True)
    path.mkdir()
    result = execute(tmp_path, computation, item, "attempt-3")
    assert result.returncode == RECEIPT_PUBLICATION_FAILURE
    assert path.is_dir()


def test_new_attempt_is_selected_before_a_late_old_receipt(tmp_path):
    computation, item = target(tmp_path, "true; exit 3")
    execute(tmp_path, computation, item, "attempt-1")
    execute(tmp_path, computation, item, "attempt-2")
    assert read_runtime_record(current_attempt_path(tmp_path, computation["identity"], item["name"]))["attempt"] == "attempt-2"
