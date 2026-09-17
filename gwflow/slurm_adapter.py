"""gwf 2.1.1-sensitive host submission and scheduler observation integration."""
import os
from pathlib import Path
import re
from shlex import join, quote
import sys

from gwf import Target
from gwf.backends.base import BackendStatus
from gwf.backends.slurm import SlurmOps, TARGET_DEFAULTS

from .runtime_errors import RuntimeFailure


def observe_tracking(tracking, scheduler):
    """Observe every retained association, including pruned computations."""
    associations = [item for item in tracking["associations"].values()
                    if item["kind"] == "job-association"] if tracking is not None else ()
    ids = [item["job_id"] for item in associations]
    observed = scheduler.observe(ids) if ids else {}
    allowed = {"submitted", "running", "completed", "failed", "cancelled", "unknown"}
    if (type(observed) is not dict or set(observed) != set(ids)
            or any(type(value) is not str or value not in allowed for value in observed.values())):
        raise RuntimeFailure("scheduler-query-failed", "scheduler did not return a valid observation for every tracked job")
    statuses = {(item["identity"], item["target"]): observed[item["job_id"]] for item in associations}
    jobs = {(item["identity"], item["target"]): item["job_id"] for item in associations}
    return statuses, jobs


def _options(resources):
    options = {key: value for key, value in TARGET_DEFAULTS.items() if value is not None}
    if "memory_mb" in resources:
        options["memory"] = f"{resources['memory_mb']}M"
    if "walltime_seconds" in resources:
        days, seconds = divmod(resources["walltime_seconds"], 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        options["walltime"] = (f"{days}-" if days else "") + f"{hours:02}:{minutes:02}:{seconds:02}"
    for source, destination in (("partition", "queue"), ("account", "account")):
        if source in resources:
            options[destination] = resources[source]
    return options


class GwfSlurmAdapter:
    """Use real gwf Slurm operations, with gwflow's independent durable tracking."""

    def __init__(self, project):
        self.project = str(project)
        self.ops = _QuotedLogSlurmOps(self.project, "full", True, TARGET_DEFAULTS)

    def observe(self, job_ids):
        try:
            states = self.ops.get_job_states(job_ids)
            if any(not isinstance(state, BackendStatus) or state is BackendStatus.UNKNOWN for state in states.values()):
                raise ValueError("scheduler returned an unrecognized state")
        except Exception as exc:
            raise RuntimeFailure("scheduler-query-failed", f"Slurm status query failed: {exc}") from exc
        return {job_id: states[job_id].name.lower() if job_id in states else "unknown" for job_id in job_ids}

    def submit(self, job):
        definition = job["definition"]
        # The shared source checkout (or installed package root) must be visible
        # to compute nodes, just like the interpreter and invocation records.
        source = str(Path(__file__).resolve().parents[1])
        pythonpath = source + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
        command = "exec env " + join([f"PYTHONPATH={pythonpath}", sys.executable,
                                       "-m", "gwflow.host_execution", job["invocation"]])
        target = Target(job["ownership"], definition["inputs"], definition["outputs"],
                        _options(definition["resources"]),
                        working_dir=job["computation"]["work_dir"], spec=command)
        (Path(self.project) / ".gwf" / "logs").mkdir(parents=True, exist_ok=True)
        response = self.ops.submit_target(target, job["dependencies"])
        match = re.fullmatch(r"([1-9][0-9]*)(?:;[A-Za-z0-9_.-]+)?", response)
        if match is None:
            raise RuntimeFailure("invalid-scheduler-job-id", f"Slurm acceptance did not return a valid job ID: {response!r}")
        return match.group(1)


class _QuotedLogSlurmOps(SlurmOps):
    """Keep gwf serialization/submission, quoting its path-valued directives."""

    def compile_script(self, target):
        lines = []
        for line in super().compile_script(target).splitlines(keepends=True):
            for flag in ("--output", "--error"):
                prefix = f"#SBATCH {flag}="
                if line.startswith(prefix):
                    line = prefix + quote(line[len(prefix):].rstrip("\n")) + "\n"
                    break
            lines.append(line)
        return "".join(lines)
