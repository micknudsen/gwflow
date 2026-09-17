"""Conservative ownership inspection for explicit operator recovery only."""
import re
import subprocess

from .runtime_errors import RuntimeFailure


TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
            "OUT_OF_MEMORY", "BOOT_FAIL", "DEADLINE", "PREEMPTED", "REVOKED"}


def inspect_ownership(ownerships, since):
    """Return accounting and live-queue observations, never infer nonacceptance."""
    if not ownerships:
        return []
    names = ",".join(ownerships)
    commands = [
        ["sacct", "--noheader", "--parsable2", "--allocations", "--duplicates",
         "--starttime", since, "--name", names, "--format=JobIDRaw,JobName%128,State%64"],
        ["squeue", "--noheader", "--states=all", "--name", names, "--format=%i|%j|%T"],
    ]
    observations = []
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            for line in result.stdout.splitlines():
                fields = [field.strip() for field in line.split("|")]
                if len(fields) != 3 or not re.fullmatch(r"[1-9][0-9]*", fields[0]):
                    raise ValueError(f"invalid recovery scheduler row: {line!r}")
                job_id, ownership, state = fields
                # Slurm may append ' by <uid>' to CANCELLED.
                if state.startswith("CANCELLED by "):
                    state = "CANCELLED"
                if ownership not in ownerships or not state:
                    raise ValueError(f"unknown recovery ownership/state: {line!r}")
                observations.append({"job_id": job_id, "ownership": ownership,
                                     "state": state, "source": command[0]})
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise RuntimeFailure("scheduler-query-failed", f"recovery inspection failed: {exc}") from exc
    return observations
