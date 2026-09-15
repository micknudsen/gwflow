"""The planning command; imports trusted definition code, never runs targets."""
import argparse
import json
import sys
from . import PlanError, load, plan


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m gwflow")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("plan", help="describe intended work as JSON")
    command.add_argument("definition", help="importable module:attribute")
    command.add_argument("--project", required=True)
    command.add_argument("--bindings", default="{}", help="JSON object of named input bindings")
    command.add_argument("--resources", default="{}", help="JSON occurrence/target operational overrides")
    args = parser.parse_args(argv)
    try:
        result = plan(load(args.definition), json.loads(args.bindings), project=args.project, resources=json.loads(args.resources))
    except (PlanError, json.JSONDecodeError) as exc:
        print(f"gwflow: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
