"""Command-line interface for EndfieldModController."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .api import EndfieldModControllerApi


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EndfieldModController CLI")
    parser.add_argument("--config", default=None, help="config.json path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("state")
    sub.add_parser("scan")
    prep = sub.add_parser("prepare")
    prep.add_argument("--select", action="append", default=[])
    sub.add_parser("deps-check")
    sub.add_parser("deps-update")
    sub.add_parser("launch-preview")
    sub.add_parser("launch")
    sub.add_parser("rollback")
    args = parser.parse_args(argv)

    api = EndfieldModControllerApi(Path(args.config) if args.config else None)
    if args.command == "state":
        _print(api.get_state())
    elif args.command == "scan":
        _print(api.scan())
    elif args.command == "prepare":
        _print(api.prepare(args.select))
    elif args.command == "deps-check":
        _print(api.update_dependencies(dry_run=True))
    elif args.command == "deps-update":
        _print(api.update_dependencies(dry_run=False))
    elif args.command == "launch-preview":
        _print(api.launch_preview())
    elif args.command == "launch":
        _print(api.launch())
    elif args.command == "rollback":
        _print(api.rollback())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
