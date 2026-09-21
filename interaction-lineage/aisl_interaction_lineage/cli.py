from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from .aisl import KnowledgeApiGateway
from .builder import build_interaction_lineage
from .contracts import load_bindings


def _load_object(path: str) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="interaction-lineage")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--topology", required=True)
    build.add_argument("--edge-id", required=True)
    build.add_argument("--bindings", required=True)
    build.add_argument("--aisl-base-url", required=True)
    build.add_argument("--transport-role", choices=("request", "response", "all"), default="all")
    build.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    topology = _load_object(args.topology)
    bindings = load_bindings(args.bindings)
    roles = ("request", "response") if args.transport_role == "all" else (args.transport_role,)
    gateway = KnowledgeApiGateway(args.aisl_base_url)
    try:
        result = build_interaction_lineage(
            topology,
            edge_id=args.edge_id,
            bindings=bindings,
            gateway=gateway,
            transport_roles=roles,
        )
    finally:
        gateway.close()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
