"""The planning command; imports trusted definition code, never runs targets."""
import argparse
import json
import sys
from . import PlanError, load, manifest, plan
from .runtime import preview
from .runtime_records import execution_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m gwflow")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("plan", help="describe intended work as JSON")
    runtime = commands.add_parser("run", help="preview or submit runtime work")
    for subcommand in (command, runtime):
        subcommand.add_argument("definition", help="importable module:attribute")
        subcommand.add_argument("--project", required=True)
        subcommand.add_argument("--bindings", default="{}", help="JSON object of named input bindings")
        subcommand.add_argument("--resources", default="{}", help="JSON occurrence/target operational overrides")
    command.add_argument("--format", choices=("plan", "manifests", "execution-manifests"), default="plan")
    runtime.add_argument("--dry-run", action="store_true", help="emit a strictly read-only runtime preview")
    args = parser.parse_args(argv)
    try:
        result = plan(load(args.definition), json.loads(args.bindings), project=args.project, resources=json.loads(args.resources))
        if args.command == "plan" and args.format == "manifests":
            result = [manifest(result, c["identity"]) for c in result["computations"]]
        if args.command == "plan" and args.format == "execution-manifests":
            result = [execution_manifest(result, c["identity"]) for c in result["computations"]]
        if args.command == "run" and args.dry_run:
            result = preview(result)
    except (PlanError, json.JSONDecodeError) as exc:
        print(f"gwflow: {exc}", file=sys.stderr)
        return 2
    if args.command == "run":
        if not args.dry_run:
            print("gwflow: runtime submission is not available until the static scheduler adapter is installed", file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "run" and result.get("outcome") in {"blocked", "error"}:
        print(f"gwflow: {result['diagnostic']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
