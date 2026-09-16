"""Native command submission through real gwf and an external Slurm substitute."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

from examples.portable_slurm import PortableSlurm
from gwflow.runtime_records import read_runtime_record, read_tracking, receipt_path


def submitted(tmp_path, definition="examples.static_submission:main", *arguments):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("host payload\n")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    result = scheduler.command("run", definition, "--project", str(project), *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    return project, scheduler, json.loads(result.stdout)


def test_complete_static_graph_uses_only_compute_jobs_and_whole_producer_dependencies(tmp_path):
    project, scheduler, report = submitted(tmp_path)
    assert report["outcome"] == "submitted"
    assert len(report["accepted_job_ids"]) == 5
    jobs = scheduler.jobs()
    associations = list(read_tracking(project)["associations"].values())
    ids = {record["target"]: record["job_id"] for record in associations}
    reported = {target["name"]: target["job_ids"] for computation in report["computations"] for target in computation["targets"]}
    assert reported == {name: [job_id] for name, job_id in ids.items()}
    assert set(ids) == {"seed", "early", "branch", "late", "copy"}
    assert jobs[ids["seed"]]["dependencies"] == []
    assert jobs[ids["early"]]["dependencies"] == [ids["seed"]]
    assert jobs[ids["branch"]]["dependencies"] == [ids["seed"]]
    assert jobs[ids["late"]]["dependencies"] == [ids["branch"]]
    assert set(jobs[ids["copy"]]["dependencies"]) == {ids["early"], ids["late"]}
    assert jobs[ids["copy"]]["inputs"] == jobs[ids["early"]]["outputs"]
    assert all(job["state"] == "submitted" for job in jobs.values())
    assert not any(project.rglob("copy.txt"))  # Command returned before payload execution.


def test_real_host_jobs_continue_after_command_exit_and_early_output_does_not_release_consumer(tmp_path):
    project, scheduler, report = submitted(tmp_path)
    associations = list(read_tracking(project)["associations"].values())
    ids = {record["target"]: record["job_id"] for record in associations}
    assert scheduler.execute(ids["seed"])
    assert scheduler.execute(ids["early"])
    early = Path(scheduler.jobs()[ids["early"]]["outputs"][0])
    consumer = Path(scheduler.jobs()[ids["copy"]]["outputs"][0])
    assert early.read_text() == "host payload\n"
    assert not scheduler.execute(ids["copy"])
    assert not consumer.exists()
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())
    assert consumer.read_text() == "host payload\n"
    for association in associations:
        receipt = read_runtime_record(receipt_path(project, association["identity"], association["target"], association["attempt"]))
        assert receipt is not None
    repeated = scheduler.command("run", "examples.static_submission:main", "--project", str(project))
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert json.loads(repeated.stdout)["accepted_job_ids"] == []
    assert len(scheduler.jobs()) == 5


def test_project_paths_with_spaces_reach_slurm_and_the_actual_host_worker(tmp_path):
    location = tmp_path / "project location with spaces"
    location.mkdir()
    project, scheduler, _ = submitted(location)
    for job in scheduler.jobs().values():
        assert job["directives"]["--output"] == str(project / ".gwf" / "logs" / (job["name"] + ".stdout"))
        assert job["directives"]["--error"] == str(project / ".gwf" / "logs" / (job["name"] + ".stderr"))
    scheduler.advance()
    assert all(job["state"] == "completed" for job in scheduler.jobs().values())


@pytest.mark.parametrize("seconds,formatted", [(61, "00:01:01"), (90061, "1-01:01:01")])
def test_operational_resources_reach_native_slurm_directives(tmp_path, seconds, formatted):
    override = {"producer": {"early": {"memory_mb": 128, "walltime_seconds": seconds,
                                         "partition": "portable", "account": "fixture"}}}
    project, scheduler, _ = submitted(tmp_path, "examples.static_submission:main", "--resources", json.dumps(override))
    early = next(record for record in read_tracking(project)["associations"].values() if record["target"] == "early")
    directives = scheduler.jobs()[early["job_id"]]["directives"]
    assert {key: directives[key] for key in ("-c", "--mem", "-t", "-p", "-A")} == {
        "-c": "1", "--mem": "128M", "-t": formatted, "-p": "portable", "-A": "fixture",
    }


def test_late_terminal_failure_blocks_consumer_despite_early_retained_file(tmp_path):
    project, scheduler, _ = submitted(tmp_path, "examples.static_submission:failure")
    scheduler.advance()
    associations = list(read_tracking(project)["associations"].values())
    by_name = {record["target"]: record for record in associations}
    jobs = scheduler.jobs()
    assert jobs[by_name["early"]["job_id"]]["state"] == "completed"
    assert jobs[by_name["late"]["job_id"]]["state"] == "failed"
    assert jobs[by_name["late"]["job_id"]]["returncode"] == 31
    assert jobs[by_name["copy"]["job_id"]]["state"] == "submitted"
    assert not Path(jobs[by_name["copy"]["job_id"]]["outputs"][0]).exists()
    late = by_name["late"]
    assert read_runtime_record(receipt_path(project, late["identity"], late["target"], late["attempt"])) is None
    assert len(jobs) == 5  # No join, controller, finalizer, or retry job appeared.


def test_unparseable_acceptance_response_keeps_uncertainty_and_complete_intent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("source")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    scheduler.configure(sbatch_reply="accepted without a usable ID")
    result = scheduler.command("run", "examples.static_submission:main", "--project", str(project))
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["reason"]["code"] == "invalid-scheduler-job-id"
    assert report["accepted_job_ids"] == []
    assert len(scheduler.jobs()) == 1
    assert len(read_runtime_record(report["intent"])["targets"]) == 5
    assert (project / ".gwflow" / "submission.json").exists()
    blocked = scheduler.command("run", "--dry-run", "examples.static_submission:main", "--project", str(project))
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["computations"] == []


def test_parsable_optional_cluster_suffix_preserves_numeric_ids(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reads.txt").write_text("source")
    scheduler = PortableSlurm(tmp_path / "scheduler")
    scheduler.configure(sbatch_reply_suffix=";portable")
    result = scheduler.command("run", "examples.static_submission:main", "--project", str(project))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["accepted_job_ids"] == ["1001", "1002", "1003", "1004", "1005"]


def test_native_submission_rejects_images_before_project_mutation_or_acceptance(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    scheduler = PortableSlurm(tmp_path / "scheduler")
    result = scheduler.command("run", "examples.target_images:main", "--project", str(project))
    assert result.returncode == 2
    assert "host-only" in result.stderr
    assert scheduler.jobs() == {}
    assert not list(project.iterdir())


def test_static_submission_demo_grades_success_reuse_and_late_failure(tmp_path):
    result = subprocess.run([sys.executable, "-m", "examples.static_submission_demo", "--project", str(tmp_path / "demo")], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["real_slurm_jobs_submitted"] == 0
    success, failure = report["cases"]
    assert success["dependencies"]["copy"] == ["early", "late"]
    assert len(success["accepted_job_ids"]) == len(failure["accepted_job_ids"]) == 5
    assert success["repeat_accepted_job_ids"] == []
    assert success["states_after_fixture_execution"]["copy"] == "completed"
    assert failure["states_after_fixture_execution"]["late"] == "failed"
    assert failure["states_after_fixture_execution"]["copy"] == "submitted"
