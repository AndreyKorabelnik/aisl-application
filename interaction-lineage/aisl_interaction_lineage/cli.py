from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .aisl import KnowledgeApiGateway
from .bundle_plan import plan_missing_bundles, write_bundle_plan
from .batch_cache import BatchCachingGateway
from .builder import build_interaction_lineage
from .checker import check_interaction_lineage
from .contracts import BindingIndex, load_bindings, BINDINGS_SCHEMA_VERSION
from .human_csv import write_human_csv
from .prepare import KnowledgeControlPlaneGateway, PreparationBudget, prepare_interaction_lineage
from .repository_sources import load_inventory_remote_sources, KcpRepositoryRegistrar
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
    prepare.add_argument("--output", help="Detailed preparation JSON (default: <output-dir>/preparation.json)")
    prepare.add_argument("--output-dir", help="Directory for missing-revisions.json, resolved-bindings.json and prepare-missing-bundles.sh; defaults to --output parent")
    prepare.add_argument("--max-preparations", type=int, default=1,
                         help="Hard limit on total KCP calls across all selected edges (default: 1; 0 = no KCP calls)")
    prepare.add_argument("--max-kcp-steps", type=int, default=1,
                         help="KCP-enforced max_steps per call, 1..32 (default: 1)")
    prepare.add_argument("--inventory-manifest", action="append", default=[],
                         help="Inventory remote_batch_manifest.json or parent directory; repeat for UCP and KPK. Required to auto-register sources; omit for existing KCP registration")
    prepare.add_argument("--progress-jsonl",
                         help="Append sanitized progress events as JSON lines and also emit them to stderr")

    args = parser.parse_args(argv)
    if args.command == "csv":
        try:
            write_human_csv(_load_object(args.input), args.output)
            return 0
        except Exception as exc:
            print(f"interaction-lineage csv failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    if args.command == "prepare" and not (args.output or args.output_dir):
        parser.error("prepare requires --output or --output-dir")
    output_file = (Path(args.output) if args.output else Path(args.output_dir) / "preparation.json")
    plan_dir = (Path(args.output_dir) if args.command == "prepare" and args.output_dir
                else output_file.parent)
    if args.command == "prepare":
        plan_dir.mkdir(parents=True, exist_ok=True)
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
        # Reuse compatible exact source revisions BEFORE expensive KCP preparation.
        # The catalog is the only discovery owner; it does not infer bindings from names.
        has_exact_sources = args.command == "prepare" and any(
            isinstance(row, Mapping) and row.get("repository_url") and row.get("resolved_commit")
            for row in topology.get("repositories") or ()
        )
        if has_exact_sources:
            preplan = plan_missing_bundles(topology, client=gateway._client, bindings=bindings)
            bindings = bindings.merged(preplan["resolved_bindings"]["repositories"])
        query_gateway = (BatchCachingGateway(gateway)
                         if args.all_edges and args.command in ("check", "build")
                         else gateway)
        kcp = KnowledgeControlPlaneGateway(args.kcp_base_url) if args.command == "prepare" else None
        budget = (PreparationBudget(args.max_preparations, args.max_kcp_steps)
                  if args.command == "prepare" else None)
        selected_source_ids = {
            str(edge.get(key) or "").strip()
            for edge in topology.get("edges") or () if isinstance(edge, Mapping)
            and (args.all_edges or str(edge.get("edge_id") or "") in edge_ids)
            for key in ("source_repository_id", "target_repository_id")
        }
        registrar = (KcpRepositoryRegistrar(args.kcp_base_url, load_inventory_remote_sources(
            args.inventory_manifest, selected_ids=selected_source_ids))
                     if args.command == "prepare" and args.inventory_manifest else None)

        def progress(event: Mapping[str, Any]) -> None:
            item = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), **dict(event)}
            line = json.dumps(item, ensure_ascii=False, sort_keys=True)
            print(line, file=sys.stderr, flush=True)
            if args.progress_jsonl:
                with Path(args.progress_jsonl).open("a", encoding="utf-8") as log:
                    log.write(line + "\n")

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
                        transport_roles=roles, budget=budget, progress=progress,
                        ensure_repository=registrar.ensure if registrar is not None else None,
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
            bad = {"not_ready", "failed", "blocked", "no_progress", "step_limit", "budget_exhausted"}
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
                    "deferred_group_count": sum(int(item.get("summary", {}).get("deferred_group_count") or 0) for item in results),
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
        if args.command == "prepare":
            # One user action: do all bounded automatic work, then generate
            # exact-source manual bundle tasks for the residual published gaps.
            final_plan = plan_missing_bundles(
                topology, client=getattr(gateway, "_client", None), bindings=bindings,
            )
            write_bundle_plan(final_plan, plan_dir)
            progress({
                "event": "preparation.manual_bundles_planned",
                "ready_count": final_plan["summary"]["ready_count"],
                "requires_bundle_count": final_plan["summary"]["requires_bundle_count"],
                "unresolved_count": final_plan["summary"]["unresolved_count"],
            })
            result["manual_bundles"] = {
                "status": final_plan["status"],
                "summary": final_plan["summary"],
                "missing_revisions": str(plan_dir / "missing-revisions.json"),
                "resolved_bindings": str(plan_dir / "resolved-bindings.json"),
                "preparation_script": str(plan_dir / "prepare-missing-bundles.sh"),
            }
            if final_plan["summary"]["requires_bundle_count"] or final_plan["summary"]["unresolved_count"]:
                if result.get("status") not in {"failed", "blocked", "no_progress", "step_limit", "budget_exhausted"}:
                    result["status"] = "partial"
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
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.command == "prepare" and isinstance(result.get("manual_bundles"), Mapping):
        message = result["manual_bundles"]
        print(json.dumps({
            "status": result.get("status"),
            "preparation_result": str(output_file),
            "remaining_manual_bundles": message["summary"]["requires_bundle_count"],
            "unresolved_source_identities": message["summary"]["unresolved_count"],
            "prepare_missing_bundles_script": message["preparation_script"],
            "missing_revisions": message["missing_revisions"],
        }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") not in {"not_ready", "failed", "blocked", "no_progress", "step_limit", "partial", "budget_exhausted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
