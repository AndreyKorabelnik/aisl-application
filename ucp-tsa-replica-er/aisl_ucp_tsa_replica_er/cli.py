from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .builder import build_replica_model, mermaid_flowchart
from .contracts import RevisionBinding
from .gateway import KnowledgeApiGateway
from .output import write_keys_csv, write_links_csv, write_relationships_csv, write_tables_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ucp-tsa-replica-er")
    build = parser.add_subparsers(dest="command", required=True).add_parser("build")
    build.add_argument("--aisl-base-url", default=os.getenv("AISL_BASE_URL", "http://127.0.0.1:8080"))
    build.add_argument("--ucp-system", required=True)
    build.add_argument("--ucp-revision", required=True)
    build.add_argument("--tsa-system", required=True)
    build.add_argument("--tsa-revision", required=True)
    build.add_argument("--root-object", action="append", default=[])
    build.add_argument("--output-json")
    build.add_argument("--tables-csv")
    build.add_argument("--relationships-csv")
    build.add_argument("--keys-csv")
    build.add_argument("--links-csv")
    build.add_argument("--output-mermaid")
    args = parser.parse_args(argv)

    outputs = (
        args.output_json,
        args.tables_csv,
        args.relationships_csv,
        args.keys_csv,
        args.links_csv,
        args.output_mermaid,
    )
    if not any(outputs):
        build.error(
            "at least one output must be requested: --output-json, --tables-csv, "
            "--relationships-csv, --keys-csv, --links-csv, or --output-mermaid"
        )

    gateway = None
    try:
        ucp = RevisionBinding(args.ucp_system, args.ucp_revision)
        tsa = RevisionBinding(args.tsa_system, args.tsa_revision)
        gateway = KnowledgeApiGateway(args.aisl_base_url)
        payload = build_replica_model(
            ucp=ucp,
            tsa=tsa,
            ucp_dataset=gateway.load_ucp_dataset(ucp),
            tsa_mappings=gateway.load_tsa_mappings(tsa),
            root_objects=tuple(args.root_object),
        )
        if args.output_json:
            path = Path(args.output_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if args.tables_csv:
            write_tables_csv(payload["tables"], args.tables_csv)
        if args.relationships_csv:
            write_relationships_csv(payload["relationships"], args.relationships_csv)
        if args.keys_csv:
            write_keys_csv(payload["tables"], args.keys_csv)
        if args.links_csv:
            write_links_csv(payload["relationships"], args.links_csv)
        if args.output_mermaid:
            path = Path(args.output_mermaid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(mermaid_flowchart(payload), encoding="utf-8")
        return 0 if payload["tables"] else 2
    except Exception as exc:
        print(f"ucp-tsa-replica-er build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
