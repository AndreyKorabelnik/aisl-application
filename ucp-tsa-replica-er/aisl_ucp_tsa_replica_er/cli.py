from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .builder import build_replica_model, mermaid_flowchart
from .contracts import RevisionBinding
from .gateway import KnowledgeApiGateway
from .output import write_relationships_csv, write_tables_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ucp-tsa-replica-er")
    build = parser.add_subparsers(dest="command", required=True).add_parser("build")
    build.add_argument("--aisl-base-url", default=os.getenv("AISL_BASE_URL", "http://127.0.0.1:8080"))
    build.add_argument("--ucp-system", required=True)
    build.add_argument("--ucp-revision", required=True)
    build.add_argument("--tsa-system", required=True)
    build.add_argument("--tsa-revision", required=True)
    build.add_argument("--root-object", action="append", default=[])
    build.add_argument("--output-json", required=True)
    build.add_argument("--tables-csv", required=True)
    build.add_argument("--relationships-csv", required=True)
    build.add_argument("--output-mermaid", required=True)
    args = parser.parse_args(argv)

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
        Path(args.output_json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_tables_csv(payload["tables"], args.tables_csv)
        write_relationships_csv(payload["relationships"], args.relationships_csv)
        Path(args.output_mermaid).write_text(mermaid_flowchart(payload), encoding="utf-8")
        return 0 if payload["tables"] else 2
    except Exception as exc:
        print(f"ucp-tsa-replica-er build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
