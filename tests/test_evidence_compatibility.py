import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from gwflow import execution_manifest, load, manifest, plan
from gwflow.runtime_records import current_attempt, current_attempt_path, execution_manifest_path, job_association, job_tracking, receipt_path, tracking_path, write_execution_manifest, write_runtime_record, write_tracking
from test_planner import runtime_cli
from examples.runtime_evaluation import prepare_fixture
from gwflow.runtime import preview


def prepared(tmp_path):
    (tmp_path / "reads.txt").write_text("input\n")
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    record = execution_manifest(result, result["computations"][0]["identity"])
    write_execution_manifest(tmp_path, record)
    return result, record


def test_absent_tracking_with_retained_runtime_history_blocks_without_decisions(tmp_path):
    prepared(tmp_path)
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["outcome"] == "blocked"
    assert report["reason"]["code"] == "untrustworthy-job-tracking"
    assert report["computations"] == []
    assert "tracking" in result.stderr
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize("damage", ["boolean-revision", "arbitrary-association", "wrong-key", "wrong-kind", "duplicate-job", "duplicate-json-key", "invalid-utf8"])
def test_corrupt_authoritative_associations_block_instead_of_falling_back_to_files(tmp_path, damage):
    planned, _ = prepared(tmp_path)
    identity = planned["computations"][0]["identity"]
    association = job_association(identity, "copy", "one", "123")
    record = {"kind": "job-tracking", "tracking_revision": 1, "associations": {f"{identity}:copy": association}}
    if damage == "boolean-revision":
        record["tracking_revision"] = True
    elif damage == "arbitrary-association":
        record["associations"][f"{identity}:copy"] = {"job_id": "123"}
    elif damage == "wrong-key":
        record["associations"] = {"other": association}
    elif damage == "wrong-kind":
        association["kind"] = "current-attempt"
        del association["job_id"]
    elif damage == "duplicate-job":
        record["associations"][f"{identity}:other"] = job_association(identity, "other", "two", "123")
    path = tracking_path(tmp_path)
    path.write_text(json.dumps(record))
    if damage == "duplicate-json-key":
        path.write_text('{"kind":"ignored",' + json.dumps(record)[1:])
    elif damage == "invalid-utf8":
        path.write_bytes(b"\xff")
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["outcome"] == "blocked"
    assert json.loads(result.stdout)["computations"] == []


@pytest.mark.parametrize("damage", ["lost-association", "untracked-selection"])
def test_partial_tracking_loss_blocks_even_with_successful_receipts(tmp_path, damage):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    if damage == "lost-association":
        path = tracking_path(tmp_path)
        record = json.loads(path.read_text())
        del record["associations"][f"{identity}:b"]
        path.write_text(json.dumps(record))
    else:
        write_runtime_record(current_attempt_path(tmp_path, identity, "b"), current_attempt(identity, "b", "untracked-replacement"))
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["outcome"] == "blocked"
    assert json.loads(result.stdout)["computations"] == []


def test_compatible_software_provenance_is_not_completion_evidence(tmp_path):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    installed_software = dict(planned["software"])
    planned["software"] = {"gwflow": "prior-compatible-release", "gwf": "prior-compatible-release"}
    assert planned["software"] != installed_software
    # Persist actual old provenance separately from required runtime evidence.
    (tmp_path / "prior-plan.json").write_text(json.dumps(manifest(planned, identity)))
    write_execution_manifest(tmp_path, execution_manifest(planned, identity))
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["computations"][0]["decision"] == "reuse"


def test_unsupported_required_evidence_recovers_not_invalidates_request(tmp_path):
    result, _ = prepared(tmp_path)
    write_tracking(tmp_path, job_tracking())  # Declaration-only fixture, no accepted jobs.
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


@pytest.mark.parametrize("kind", ["manifest", "selection", "receipt"])
@pytest.mark.parametrize("damage", ["missing", "malformed", "unsupported", "boolean-revision"])
def test_indispensable_evidence_recovers_with_intact_independent_tracking(tmp_path, kind, damage):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    path = {"manifest": execution_manifest_path(tmp_path, identity),
            "selection": current_attempt_path(tmp_path, identity, "b"),
            "receipt": receipt_path(tmp_path, identity, "b", "fixture-success")}[kind]
    if damage == "missing":
        path.unlink()
    elif damage == "malformed":
        path.write_text("not-json")
    else:
        record = json.loads(path.read_text())
        record["record_revision"] = 999 if damage == "unsupported" else True
        path.write_text(json.dumps(record))
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 0, result.stderr
    targets = json.loads(result.stdout)["computations"][0]["targets"]
    assert sorted(t["name"] for t in targets if t["decision"] == "execute") == (["a", "b", "c", "d", "e"] if kind == "manifest" else ["b", "e"])


def test_loss_of_optional_history_does_not_require_recomputation(tmp_path):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    target = current_attempt_path(tmp_path, identity, "b").parent
    history = target / "attempts" / "superseded"
    history.mkdir()
    for name in ("stdout.log", "stderr.log", "receipt.json", "diagnostic.json"):
        path = history / name
        path.write_text("optional superseded history")
        path.unlink()
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["computations"][0]["decision"] == "reuse"


def test_fresh_project_needs_no_tracking_and_preview_stays_read_only(tmp_path):
    (tmp_path / "reads.txt").write_text("input")
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["computations"][0]["decision"] == "execute"
    assert not (tmp_path / ".gwflow").exists()


def test_pure_plan_ignores_corrupt_runtime_tracking(tmp_path):
    path = tracking_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("corrupt tracking")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = subprocess.run([sys.executable, "-m", "gwflow", "plan", "examples.one_file:main", "--project", str(tmp_path), "--bindings", '{"source":"missing.txt"}'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["computations"]
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_compatibility_demo_grades_reuse_recovery_and_uncertainty(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.evidence_compatibility_demo", "--project", str(tmp_path / "demo")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["scheduler_jobs_submitted"] == 0
    assert report["installed_software"] != report["prior_software"]
    assert [(case["case"], case["exit"], case["execute"]) for case in report["cases"]] == [
        ("compatible-provenance-reuse", 0, []), ("unsupported-receipt-recovery", 0, ["b", "e"]),
        ("corrupt-manifest-recovery", 0, ["a", "b", "c", "d", "e"]),
        ("missing-tracking-block", 1, []), ("corrupt-tracking-block", 1, []),
        ("unsupported-tracking-block", 1, []),
    ]


def test_unrecognized_retained_runtime_namespace_cannot_be_ignored(tmp_path):
    prepare_fixture(tmp_path)
    unknown = tmp_path / ".gwflow" / "runtime" / "v999"
    unknown.mkdir()
    (unknown / "tracking.json").write_text("future authority")
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 1
    assert json.loads(result.stdout)["computations"] == []


@pytest.mark.parametrize("kind", ["manifest", "selection", "receipt"])
def test_incompatible_completion_evidence_preserves_known_active_work(tmp_path, kind):
    planned = prepare_fixture(tmp_path)
    identity = planned["computations"][0]["identity"]
    path = {"manifest": execution_manifest_path(tmp_path, identity),
            "selection": current_attempt_path(tmp_path, identity, "b"),
            "receipt": receipt_path(tmp_path, identity, "b", "fixture-success")}[kind]
    record = json.loads(path.read_text())
    record["record_revision"] = 999
    path.write_text(json.dumps(record))
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in tmp_path.rglob("*") if path.is_file()}
    report = preview(planned, statuses={(identity, "b"): "running"}, job_ids={(identity, "b"): "101"})
    assert before == {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in tmp_path.rglob("*") if path.is_file()}
    if kind == "manifest":
        # Losing the whole declaration also requires recovering b's upstream
        # target a. Protect b's active consumption before allowing that retry.
        assert report["outcome"] == "blocked"
        assert report["reason"]["code"] == "active-consumer-conflict"
        assert report["computations"] == []
        assert f"{identity}/a" in report["diagnostic"]
        assert f"{identity}/b (job 101, running)" in report["diagnostic"]
        return
    target = next(t for t in report["computations"][0]["targets"] if t["name"] == "b")
    assert target["decision"] == "attach"
    assert target["job_ids"] == ["101"]


def test_unreadable_retained_history_cannot_be_mistaken_for_no_history(tmp_path, monkeypatch):
    planned = prepare_fixture(tmp_path)
    real_scandir = os.scandir
    root = tracking_path(tmp_path).parent / "computations"

    def denied(path):
        if Path(path) == root:
            raise PermissionError("injected unreadable retained history")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", denied)
    report = preview(planned)
    assert report["outcome"] == "blocked"
    assert report["computations"] == []
    assert "unreadable retained history" in report["diagnostic"]


@pytest.mark.parametrize("surviving", ["work", "results"])
def test_losing_entire_runtime_metadata_still_blocks_with_owned_locations(tmp_path, surviving):
    prepare_fixture(tmp_path)
    (tmp_path / ".gwflow").rename(tmp_path / "metadata-removed-for-fixture")
    other = "results" if surviving == "work" else "work"
    (tmp_path / other).rename(tmp_path / f"{other}-removed-for-fixture")
    result = runtime_cli(tmp_path, "--dry-run", "examples.runtime_evaluation:main", "--bindings", '{"source":"reads.txt","other":"other.txt"}')
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["outcome"] == "blocked"
    assert report["computations"] == []
    assert "tracking" in result.stderr


def test_unrelated_user_directories_do_not_make_a_fresh_project_uncertain(tmp_path):
    (tmp_path / "work" / "notes").mkdir(parents=True)
    (tmp_path / "results" / "reports").mkdir(parents=True)
    (tmp_path / "work" / "ab").write_text("unrelated input file")
    (tmp_path / "results" / "ab").mkdir()
    (tmp_path / "results" / "ab" / ("ab" + "0" * 62)).write_text("unrelated regular file, not a slot directory")
    (tmp_path / "reads.txt").write_text("source")
    result = runtime_cli(tmp_path, "--dry-run", "examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".gwflow").exists()
