"""Run one maintained host target without a scheduler submission."""
import sys
from pathlib import Path

from gwflow import load, plan
from gwflow.host_execution import execute


def main(project="/tmp/gwflow-host-execution-demo"):
    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    (project / "reads.txt").write_text("demo input\n")
    result = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=project)
    computation = result["computations"][0]
    target = computation["targets"][0]
    execution = execute(project, computation, target, "demo-attempt-1")
    print(f"exit={execution.returncode} retained={target['outputs'][0]}")
    return execution.returncode


if __name__ == "__main__":
    raise SystemExit(main(*(sys.argv[1:] or [])))
