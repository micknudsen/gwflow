"""Test-only Slurm command substitute; never invokes a real scheduler."""
import io
import json
import os
from pathlib import Path
import subprocess
from shlex import split
import sys

from gwf.executors import deserialize


class PortableSlurm:
    """Substitute external Slurm executables, retaining real gwf integration."""

    def __init__(self, root):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True)
        (self.root / "bin").mkdir()
        (self.root / "jobs").mkdir()
        self.state_path = self.root / "scheduler.json"
        self.state_path.write_text(json.dumps({"jobs": {}, "next_id": 1001}))
        source = str(Path(__file__).resolve().parents[1])
        for name in ("sbatch", "sacct", "squeue"):
            path = self.root / "bin" / name
            path.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {source!r})\nfrom examples.portable_slurm import command\nraise SystemExit(command({name!r}))\n")
            path.chmod(0o700)

    @property
    def environment(self):
        return {**os.environ, "PATH": str(self.root / "bin") + os.pathsep + os.environ.get("PATH", ""),
                "GWFLOW_PORTABLE_SLURM_STATE": str(self.state_path)}

    def command(self, *arguments):
        return subprocess.run([sys.executable, "-m", "gwflow", *arguments], env=self.environment,
                              capture_output=True, text=True, timeout=30)

    def jobs(self):
        return json.loads(self.state_path.read_text())["jobs"]

    def configure(self, **settings):
        state = json.loads(self.state_path.read_text())
        state.update(settings)
        self.state_path.write_text(json.dumps(state))

    def execute(self, job_id):
        state = json.loads(self.state_path.read_text())
        job = state["jobs"][job_id]
        if job["state"] != "submitted" or any(state["jobs"][parent]["state"] != "completed" for parent in job["dependencies"]):
            return False
        job["state"] = "running"
        self.state_path.write_text(json.dumps(state))
        result = subprocess.run([sys.executable, "-m", "gwf.exec", job["script"]],
                                env={**self.environment, "GWF_EXEC_WORKFLOW_ROOT": job["workflow_root"]},
                                cwd=job["working_dir"], capture_output=True, text=True, timeout=30)
        job.update(state="completed" if result.returncode == 0 else "failed",
                   returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        self.state_path.write_text(json.dumps(state))
        return True

    def advance(self):
        while True:
            progressed = False
            for job_id in self.jobs():
                progressed = self.execute(job_id) or progressed
            if not progressed:
                return


def command(executable):
    """Entry point used only by generated fixture executables on a private PATH."""
    state_path = Path(os.environ["GWFLOW_PORTABLE_SLURM_STATE"])
    state = json.loads(state_path.read_text())
    if executable == "sbatch":
        script = sys.stdin.read()
        directives = {}
        for line in script.splitlines():
            if line.startswith("#SBATCH "):
                words = split(line[len("#SBATCH "):])
                if len(words) == 1 and "=" in words[0]:
                    flag, value = words[0].split("=", 1)
                elif len(words) == 2 and "=" not in words[0]:
                    flag, value = words
                else:
                    print(f"error: invalid fixture Slurm directive: {line}", file=sys.stderr)
                    return 1
                directives[flag] = value
        target = deserialize(io.StringIO(script))
        job_id = str(state["next_id"])
        state["next_id"] += 1
        dependencies = next((arg.split("afterok:", 1)[1].split(":") for arg in sys.argv[1:] if arg.startswith("--dependency=afterok:")), [])
        script_path = state_path.parent / "jobs" / f"{job_id}.gwf"
        script_path.write_text(script)
        state["jobs"][job_id] = {"name": target.name, "dependencies": dependencies,
            "inputs": list(target.inputs), "outputs": list(target.outputs), "options": target.options,
            "working_dir": target.working_dir, "script": str(script_path),
            "directives": directives,
            "workflow_root": os.environ["GWF_EXEC_WORKFLOW_ROOT"], "state": "submitted"}
        temporary = state_path.with_suffix(".pending")
        temporary.write_text(json.dumps(state))
        os.replace(temporary, state_path)
        print(state.get("sbatch_reply", job_id + state.get("sbatch_reply_suffix", "")))
    elif executable == "squeue":
        for job_id, job in state["jobs"].items():
            if job["state"] in {"submitted", "running"}:
                print(f"{job_id};{'PD' if job['state'] == 'submitted' else 'R'}")
    elif executable == "sacct":
        requested = sys.argv[sys.argv.index("--jobs") + 1].split(",")
        states = {"submitted": "PENDING", "running": "RUNNING", "completed": "COMPLETED", "failed": "FAILED", "cancelled": "CANCELLED"}
        for job_id in requested:
            job = state["jobs"].get(job_id)
            if job and job["state"] in states:
                print(f"{job_id}|{states[job['state']]}")
    return 0
