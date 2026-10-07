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

from .bridge import bind_kpk_consumers, compose_many
from .contracts import CrossingUcpEvidence
from .csv_output import write_csv


def _load_crossing_evidence(path: str | Path) -> list[CrossingUcpEvidence]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result: list[CrossingUcpEvidence] = []
    for row in rows:
        if not str(row.get("endpoint_key") or "").strip():
            continue
        if str(row.get("left_status") or "exact_field").strip() not in {"exact_field", "confirmed"}:
            continue
        result.append(CrossingUcpEvidence.from_mapping(row))
    return result


def _load_interaction_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh, delimiter=";")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kpk-profile-fl-lineage")
    build = parser.add_subparsers(dest="command", required=True).add_parser("build")
    build.add_argument("--aisl-base-url", default=os.getenv("AISL_BASE_URL", "http://127.0.0.1:8080"))
    build.add_argument("--crossing-ucp-evidence", required=True)
    build.add_argument("--interaction-lineage-csv", required=True)
    build.add_argument("--consumer-repository", required=True)
    build.add_argument("--consumer-output-root", required=True)
    build.add_argument("--interaction", default="")
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
        crossing_evidence = _load_crossing_evidence(args.crossing_ucp_evidence)
        if not crossing_evidence:
            raise RuntimeError("crossing→UCP evidence contains no exact endpoint rows")
        interaction_rows = _load_interaction_rows(args.interaction_lineage_csv)
        evidence = bind_kpk_consumers(
            crossing_evidence,
            interaction_rows,
            consumer_repository=args.consumer_repository,
            output_root=args.consumer_output_root,
            interaction=args.interaction,
        )
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
            "schema_version": "kpk-profile-fl-lineage/v2",
            "join_rule": "exact_task43_crossing_to_consumer_plus_exact_full_ucp_semantic_path",
            "consumer_selection": {
                "consumer_repository": args.consumer_repository,
                "consumer_output_root": args.consumer_output_root,
                "interaction": args.interaction,
            },
            "source_binding": {"system_id": source.system_id, "revision_id": source.revision_id},
            "tsa_binding": {"system_id": tsa.system_id, "revision_id": tsa.revision_id},
            "profile_binding": {"system_id": profile.system_id, "revision_id": profile.revision_id},
            "rows": rows,
        }
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_csv(rows, args.output_csv)
        return 0 if any(
            row.get("join_status") == "confirmed_exact_ucp_semantic_path_and_kpk_egress"
            for row in rows
        ) else 2
    except Exception as exc:
        print(f"kpk-profile-fl-lineage build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
