"""Crash controlled submission commands against a test-only scheduler substitute."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from gwflow.__main__ import main as product_command
from gwflow.runtime_records import read_runtime_record, tracking_path


class FixtureScheduler:
    """External scheduler simulation: accepted jobs never execute payloads."""

    def __init__(self, project, interruption):
        self.project = project
        self.interruption = interruption
        self.accepted = []

    def observe(self, job_ids):
        return {job_id: "running" for job_id in job_ids}

    def submit(self, job):
        if self.interruption == "before-acceptance":
            os._exit(91)
        if self.interruption == "hold" and not self.accepted:
            (self.project / "fixture-submit-entered").write_text("ready")
            deadline = time.monotonic() + 15
            while not (self.project / "fixture-release").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("test-only scheduler hold timed out")
                time.sleep(0.02)
        job_id = str(101 + len(self.accepted))
        self.accepted.append({"job_id": job_id, "ownership": job["ownership"]})
        (self.project / "fixture-scheduler.json").write_text(json.dumps(self.accepted))
        if self.interruption == "accepted-before-id" or (self.interruption == "partial-graph" and len(self.accepted) == 2):
            os._exit(91)
        return job_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="new directory; defaults to a unique temporary directory")
    parser.add_argument("--worker", choices=("before-acceptance", "accepted-before-id", "partial-graph", "hold", "success"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if args.project is None:
            parser.error("fixture worker needs --project")
        return product_command([
            "run", "examples.runtime_evaluation:main", "--project", str(args.project),
            "--bindings", '{"source":"reads.txt","other":"other.txt"}',
        ], scheduler=FixtureScheduler(args.project, args.worker))
    root = args.project.absolute() if args.project else Path(tempfile.mkdtemp(prefix="gwflow-guard-demo-"))
    if args.project:
        root.mkdir(parents=True)
    cases = []
    for case, accepted_count, tracked_count in (("before-acceptance", 0, 0), ("accepted-before-id", 1, 0), ("partial-graph", 2, 1)):
        project = root / case
        project.mkdir()
        (project / "reads.txt").write_text("source")
        (project / "other.txt").write_text("other")
        crashed = subprocess.run([sys.executable, "-m", "examples.submission_guard_demo",
                                  "--project", str(project), "--worker", case], capture_output=True, text=True, timeout=30)
        if crashed.returncode != 91:
            raise RuntimeError(f"{case}: expected controlled crash: {crashed.stdout} {crashed.stderr}")
        marker = json.loads((project / ".gwflow" / "submission.json").read_text())
        intent = read_runtime_record(marker["intent"])
        tracked = json.loads(tracking_path(project).read_text())["associations"]
        ledger = project / "fixture-scheduler.json"
        accepted = json.loads(ledger.read_text()) if ledger.exists() else []
        preview = subprocess.run([sys.executable, "-m", "gwflow", "run", "--dry-run",
                                  "examples.runtime_evaluation:main", "--project", str(project),
                                  "--bindings", '{"source":"reads.txt","other":"other.txt"}'],
                                 capture_output=True, text=True, timeout=30)
        report = json.loads(preview.stdout)
        if len(accepted) != accepted_count or len(tracked) != tracked_count or len(intent["targets"]) != 5 or preview.returncode != 1 or report["computations"]:
            raise RuntimeError(f"{case}: incorrect retained state or blocked preview")
        cases.append({"case": case, "command_exit": crashed.returncode,
                      "fixture_accepted": len(accepted), "durably_tracked": len(tracked),
                      "intended": len(intent["targets"]), "intent": marker["intent"],
                      "preview_exit": preview.returncode, "reason": report["reason"]["code"]})
    print(json.dumps({"project": str(root), "fixture_only": True, "scheduler_jobs_submitted": 0, "cases": cases}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
