from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .aisl import KnowledgeApiGateway
from .batch_cache import BatchCachingGateway
from .builder import build_interaction_lineage
from .checker import check_interaction_lineage
from .contracts import BindingIndex, load_bindings, BINDINGS_SCHEMA_VERSION
from .human_csv import write_human_csv
from .prepare import KnowledgeControlPlaneGateway, prepare_interaction_lineage
from .topology import validate_topology


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
        selector = command.add_mutually_exclusive_group(required=True)
        selector.add_argument("--edge-id")
        selector.add_argument("--all-edges", action="store_true", help="Evaluate every candidate edge; no implicit prepare")
        command.add_argument("--bindings", required=True)
        command.add_argument("--aisl-base-url", required=True)
        command.add_argument("--transport-role", choices=("request", "response", "all"), default="all")
        command.add_argument("--output", required=True)
        if name == "check":
            command.add_argument(
                "--deep", action="store_true",
                help="Resolve field anchors and external-origin gaps; default check only verifies pinned revisions, capabilities and observed field coverage",
            )

    csv_command = sub.add_parser("csv", help="Render human-readable CSV from interaction lineage JSON")
    csv_command.add_argument("--input", required=True)
    csv_command.add_argument("--output", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--topology", required=True)
    prepare_selector = prepare.add_mutually_exclusive_group(required=True)
    prepare_selector.add_argument("--edge-id")
    prepare_selector.add_argument("--all-edges", action="store_true", help="Explicit bounded preparation of all candidate edges")
    prepare.add_argument("--bindings", help="Optional existing exact bindings; prepare fills generic preparable knowledge gaps")
    prepare.add_argument("--aisl-base-url", required=True)
    prepare.add_argument("--kcp-base-url", required=True)
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

    gateway = None
    try:
        topology = _load_object(args.topology)
        bindings = _bindings(args.bindings)
        roles = ("request", "response") if args.transport_role == "all" else (args.transport_role,)
        validate_topology(topology)
        if args.all_edges:
            edge_ids = sorted(str(item.get("edge_id") or "") for item in topology["edges"])
            if not edge_ids or not all(edge_ids) or len(set(edge_ids)) != len(edge_ids):
                raise ValueError("all candidate edges must have unique nonempty IDs")
        else:
            edge_ids = [args.edge_id]
        gateway = KnowledgeApiGateway(args.aisl_base_url)
        query_gateway = (BatchCachingGateway(gateway)
                         if args.all_edges and args.command in ("check", "build")
                         else gateway)
        kcp = KnowledgeControlPlaneGateway(args.kcp_base_url) if args.command == "prepare" else None
        results: list[dict[str, Any]] = []
        for edge_id in edge_ids:
            try:
                if args.command == "check":
                    item = check_interaction_lineage(
                        topology, edge_id=edge_id, bindings=bindings,
                        gateway=query_gateway, transport_roles=roles,
                        prerequisites_only=not args.deep,
                    )
                elif args.command == "prepare":
                    item = prepare_interaction_lineage(
                        topology, edge_id=edge_id, bindings=bindings,
                        readiness_gateway=query_gateway, preparation_gateway=kcp,
                        transport_roles=roles,
                    )
                    updated = item.get("bindings")
                    if isinstance(updated, Mapping):
                        rows = updated.get("repositories")
                        if isinstance(rows, list):
                            bindings = bindings.merged([x for x in rows if isinstance(x, Mapping)])
                else:
                    item = build_interaction_lineage(
                        topology, edge_id=edge_id, bindings=bindings,
                        gateway=query_gateway, transport_roles=roles,
                    )
                results.append(dict(item))
            except Exception as exc:
                if not args.all_edges:
                    raise
                results.append({
                    "format": "interaction-lineage-command-result/v1",
                    "edge_id": edge_id, "status": "failed",
                    "diagnostics": [{"code": "edge_failed", "exception_type": type(exc).__name__, "message": str(exc)}],
                })
        if args.all_edges:
            # A complete ledger even when individual candidates are unresolved.
            states = [str(item.get("status") or "candidate") for item in results]
            bad = {"not_ready", "failed", "blocked", "no_progress", "step_limit"}
            output_status = "partial" if any(state in bad for state in states) else "complete"
            result = {
                "format": "interaction-lineage-candidate-batch/v1",
                "status": output_status,
                "topology_id": str(topology.get("topology_id") or ""),
                "command": args.command,
                "edges": [{"edge_id": edge_id, "result": item} for edge_id, item in zip(edge_ids, results)],
                "summary": {
                    "candidate_edge_count": len(edge_ids),
                    "processed_edge_count": len(results),
                    "failed_or_blocked_count": sum(state in bad for state in states),
                    "framework_invocation_count": sum(int(item.get("summary", {}).get("framework_invocation_count") or 0) for item in results),
                },
            }
            if isinstance(query_gateway, BatchCachingGateway):
                result["summary"]["aisl_api_cache"] = query_gateway.statistics()
            if args.command == "prepare":
                result["bindings"] = {
                    "schema_version": BINDINGS_SCHEMA_VERSION,
                    "repositories": [binding.to_dict() for binding in bindings.all()],
                }
        else:
            result = results[0]
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
    return 0 if result.get("status") not in {"not_ready", "failed", "blocked", "no_progress", "step_limit", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
