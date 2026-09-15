"""Disposable host envelope used by the live Phase 0 Apptainer probe."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile


@dataclass
class EvidenceApptainer:
    """A test-only gwf executor that keeps evidence duties outside the image."""

    image: str
    flags: tuple[str, ...]
    outputs: tuple[str, ...]
    receipt: str
    attempt: str
    fail_after_receipt: int | None = None

    def get_command(self, spec_path: str, workflow_root: str) -> list[str]:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "run",
            "--image", self.image,
            "--receipt", self.receipt,
            "--attempt", self.attempt,
            "--spec", spec_path,
        ]
        for flag in self.flags:
            command.append(f"--flag={flag}")
        for output in self.outputs:
            command.extend(["--output", output])
        if self.fail_after_receipt is not None:
            command.extend(["--fail-after-receipt", str(self.fail_after_receipt)])
        return command


def publish_receipt(path: Path, value: object) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".receipt-")
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary_path.unlink(missing_ok=True)


def run(args) -> int:
    executable = shutil.which("apptainer")
    if executable is None:
        print("apptainer executable is unavailable", file=sys.stderr)
        return 71
    result = subprocess.run(
        [executable, "exec", *args.flag, args.image, args.spec],
        env=os.environ,
    )
    if result.returncode:
        return result.returncode
    try:
        outputs = {path: Path(path).stat().st_mtime for path in args.output}
    except OSError as error:
        print(f"required output check failed: {error}", file=sys.stderr)
        return 72
    try:
        publish_receipt(Path(args.receipt), {
            "attempt": args.attempt,
            "image": args.image,
            "node": socket.gethostname(),
            "outputs": outputs,
            "target": os.environ.get("GWF_TARGET_NAME"),
        })
    except OSError as error:
        print(f"required receipt publication failed: {error}", file=sys.stderr)
        return 73
    return args.fail_after_receipt or 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run",))
    parser.add_argument("--image", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--flag", action="append", default=[])
    parser.add_argument("--output", action="append", default=[])
    parser.add_argument("--fail-after-receipt", type=int)
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
