from __future__ import annotations

import argparse
import os
import sys

from .builder import build_lineage, list_source_fields
from .contracts import RevisionBinding
from .csv_output import write_csv
from .gateway import KnowledgeApiGateway


def _binding(system_id: str, revision_id: str) -> RevisionBinding:
    return RevisionBinding(system_id=system_id, revision_id=revision_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="data-model-datamart-lineage")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--aisl-base-url", default=os.getenv("AISL_BASE_URL", "http://127.0.0.1:8080"))
    build.add_argument("--source-system", required=True)
    build.add_argument("--source-revision", required=True)
    build.add_argument("--bridge-system", required=True)
    build.add_argument("--bridge-revision", required=True)
    build.add_argument("--target-system", required=True)
    build.add_argument("--target-revision", required=True)
    build.add_argument("--source-object", required=True)
    build.add_argument("--source-field")
    build.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    gateway = None
    try:
        gateway = KnowledgeApiGateway(args.aisl_base_url)
        source = _binding(args.source_system, args.source_revision)
        tsa = _binding(args.bridge_system, args.bridge_revision)
        profile = _binding(args.target_system, args.target_revision)
        fields = [args.source_field] if args.source_field else list_source_fields(
            gateway=gateway, source=source, source_object=args.source_object
        )
        if not fields:
            raise RuntimeError(f"source object has no resolvable declared fields: {args.source_object}")
        rows = []
        for source_field in fields:
            rows.extend(build_lineage(
                gateway=gateway,
                source=source,
                tsa=tsa,
                profile=profile,
                source_object=args.source_object,
                source_field=source_field,
            ))
        write_csv(rows, args.output)
        # Explicit gap/ambiguity rows are valid deterministic build output.
        # Exit non-zero only when no mechanically supported branch exists at all.
        return 0 if any(row.get("status", "").startswith("confirmed") for row in rows) else 2
    except Exception as exc:
        print(f"data-model-datamart-lineage build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
