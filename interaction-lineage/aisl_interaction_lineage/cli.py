from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping

from .aisl import KnowledgeApiGateway
from .builder import build_interaction_lineage
from .checker import check_interaction_lineage
from .contracts import BindingIndex, load_bindings
from .human_csv import write_human_csv
from .prepare import KnowledgeApiCliImporter, KnowledgeControlPlaneGateway, prepare_interaction_lineage


def _load_object(path: str) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def _bindings(path: str | None) -> BindingIndex:
    return load_bindings(path) if path else BindingIndex([])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="interaction-lineage")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("check", "build"):
        command = sub.add_parser(name)
        command.add_argument("--topology", required=True)
        command.add_argument("--edge-id", required=True)
        command.add_argument("--bindings", required=True)
        command.add_argument("--aisl-base-url", required=True)
        command.add_argument("--transport-role", choices=("request", "response", "all"), default="all")
        command.add_argument("--output", required=True)

    csv_command = sub.add_parser("csv", help="Render human-readable CSV from interaction lineage JSON")
    csv_command.add_argument("--input", required=True)
    csv_command.add_argument("--output", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--topology", required=True)
    prepare.add_argument("--edge-id", required=True)
    prepare.add_argument("--bindings", help="Optional existing exact bindings; prepare fills missing/not-ready repositories")
    prepare.add_argument("--aisl-base-url", required=True)
    prepare.add_argument("--kcp-base-url", required=True)
    prepare.add_argument("--knowledge-api-command", default="knowledge-api")
    prepare.add_argument("--transport-role", choices=("request", "response", "all"), default="all")
    prepare.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "csv":
        try:
            write_human_csv(_load_object(args.input), args.output)
            return 0
        except Exception as exc:
            print(f"interaction-lineage csv failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    topology = _load_object(args.topology)
    bindings = _bindings(args.bindings)
    roles = ("request", "response") if args.transport_role == "all" else (args.transport_role,)
    gateway = None
    try:
        try:
            gateway = KnowledgeApiGateway(args.aisl_base_url)
            if args.command == "check":
                result = check_interaction_lineage(
                    topology,
                    edge_id=args.edge_id,
                    bindings=bindings,
                    gateway=gateway,
                    transport_roles=roles,
                )
            elif args.command == "prepare":
                kcp = KnowledgeControlPlaneGateway(args.kcp_base_url)
                importer = KnowledgeApiCliImporter(shlex.split(args.knowledge_api_command))
                result = prepare_interaction_lineage(
                    topology,
                    edge_id=args.edge_id,
                    bindings=bindings,
                    readiness_gateway=gateway,
                    preparation_gateway=kcp,
                    importer=importer,
                    transport_roles=roles,
                )
            else:
                result = build_interaction_lineage(
                    topology,
                    edge_id=args.edge_id,
                    bindings=bindings,
                    gateway=gateway,
                    transport_roles=roles,
                )
        except Exception as exc:
            result = {
                "format": "interaction-lineage-command-result/v1",
                "status": "failed",
                "command": args.command,
                "diagnostics": [{
                    "code": "command_failed",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }],
            }
    finally:
        if gateway is not None:
            gateway.close()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("status") not in {"not_ready", "failed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
