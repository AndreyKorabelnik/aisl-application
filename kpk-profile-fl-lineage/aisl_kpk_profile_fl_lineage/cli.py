from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from aisl_data_model_datamart_lineage.builder import build_lineage
from aisl_data_model_datamart_lineage.contracts import RevisionBinding
from aisl_data_model_datamart_lineage.gateway import KnowledgeApiGateway

from .bridge import compose_many
from .contracts import KpkUcpEvidence
from .csv_output import write_csv


def _load_evidence(path: str | Path) -> list[KpkUcpEvidence]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result: list[KpkUcpEvidence] = []
    for row in rows:
        if not str(row.get("endpoint_key") or "").strip():
            continue
        if str(row.get("left_status") or "exact_field").strip() not in {"exact_field", "confirmed"}:
            continue
        result.append(KpkUcpEvidence.from_mapping(row))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kpk-profile-fl-lineage")
    build = parser.add_subparsers(dest="command", required=True).add_parser("build")
    build.add_argument("--aisl-base-url", default=os.getenv("AISL_BASE_URL", "http://127.0.0.1:8080"))
    build.add_argument("--kpk-ucp-evidence", required=True)
    build.add_argument("--source-system", required=True)
    build.add_argument("--source-revision", required=True)
    build.add_argument("--bridge-system", required=True)
    build.add_argument("--bridge-revision", required=True)
    build.add_argument("--target-system", required=True)
    build.add_argument("--target-revision", required=True)
    build.add_argument("--output-json", required=True)
    build.add_argument("--output-csv", required=True)
    args = parser.parse_args(argv)

    gateway = None
    try:
        evidence = _load_evidence(args.kpk_ucp_evidence)
        if not evidence:
            raise RuntimeError("KPK→UCP evidence contains no exact endpoint rows")
        source = RevisionBinding(args.source_system, args.source_revision)
        tsa = RevisionBinding(args.bridge_system, args.bridge_revision)
        profile = RevisionBinding(args.target_system, args.target_revision)
        gateway = KnowledgeApiGateway(args.aisl_base_url)
        right_by_endpoint: dict[str, list[dict]] = {}
        for item in evidence:
            if item.endpoint_key in right_by_endpoint:
                continue
            right_by_endpoint[item.endpoint_key] = build_lineage(
                gateway=gateway,
                source=source,
                tsa=tsa,
                profile=profile,
                source_object=item.source_type_fqcn,
                source_field=item.source_field,
            )
        rows = compose_many(evidence, right_by_endpoint)
        payload = {
            "schema_version": "kpk-profile-fl-lineage/v1",
            "join_rule": "exact_full_ucp_semantic_path",
            "source_binding": {"system_id": source.system_id, "revision_id": source.revision_id},
            "tsa_binding": {"system_id": tsa.system_id, "revision_id": tsa.revision_id},
            "profile_binding": {"system_id": profile.system_id, "revision_id": profile.revision_id},
            "rows": rows,
        }
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_csv(rows, args.output_csv)
        return 0 if any(row.get("join_status") == "confirmed_exact_ucp_semantic_path" for row in rows) else 2
    except Exception as exc:
        print(f"kpk-profile-fl-lineage build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
