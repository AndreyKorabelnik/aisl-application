from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

from .contracts import KpkUcpEvidence


def _text(value: Any) -> str:
    return str(value or "").strip()


def _confirmed(row: Mapping[str, Any]) -> bool:
    return _text(row.get("status")).startswith("confirmed")


def compose_one(
    evidence: KpkUcpEvidence,
    right_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compose one KPK→UCP fact with Task46 UCP→Profile rows.

    The join is intentionally stricter than endpoint leaf identity: the right
    application must publish the exact same full UCP semantic path.  A common
    dictionary leaf such as ``QualityCode.code`` therefore never becomes a
    cross-system claim unless the target-specific UCP context is retained.
    """
    exact = [
        dict(row)
        for row in right_rows
        if _confirmed(row)
        and _text(row.get("source_type_fqcn")) == evidence.source_type_fqcn
        and _text(row.get("source_field")) == evidence.source_field
        and _text(row.get("source_attribute_path")) == evidence.ucp_semantic_path
    ]
    result: list[dict[str, Any]] = []
    for row in exact:
        replica = ".".join(v for v in (_text(row.get("replica_relation")), _text(row.get("replica_column"))) if v)
        target = ".".join(v for v in (_text(row.get("target_relation")), _text(row.get("target_column"))) if v)
        full = " → ".join(v for v in (evidence.kpk_attribute, evidence.ucp_semantic_path, replica, target) if v)
        result.append({
            "kpk_attribute": evidence.kpk_attribute,
            "kpk_evidence_classification": evidence.classification,
            "ucp_semantic_path": evidence.ucp_semantic_path,
            "ucp_endpoint_key": evidence.endpoint_key,
            "ucp_revision_id": _text(row.get("source_revision_id")),
            "tsa_replica_relation": _text(row.get("replica_relation")),
            "tsa_replica_column": _text(row.get("replica_column")),
            "profile_fl_relation": _text(row.get("target_relation")),
            "profile_fl_column": _text(row.get("target_column")),
            "join_status": "confirmed_exact_ucp_semantic_path",
            "gap": _text(row.get("gap")),
            "full_attribute_path": full,
            "left_provenance_json": evidence.provenance_json,
            "right_provenance_json": _text(row.get("provenance_json")),
        })
    if result:
        return result

    confirmed_same_leaf = [
        row for row in right_rows
        if _confirmed(row)
        and _text(row.get("source_type_fqcn")) == evidence.source_type_fqcn
        and _text(row.get("source_field")) == evidence.source_field
    ]
    if confirmed_same_leaf:
        observed_paths = sorted({_text(row.get("source_attribute_path")) for row in confirmed_same_leaf if _text(row.get("source_attribute_path"))})
        rendered: list[dict[str, Any]] = []
        for row in confirmed_same_leaf:
            target = ".".join(v for v in (_text(row.get("target_relation")), _text(row.get("target_column"))) if v)
            rendered.append({
                "kpk_attribute": evidence.kpk_attribute,
                "kpk_evidence_classification": evidence.classification,
                "ucp_semantic_path": evidence.ucp_semantic_path,
                "ucp_endpoint_key": evidence.endpoint_key,
                "ucp_revision_id": _text(row.get("source_revision_id")),
                "tsa_replica_relation": _text(row.get("replica_relation")),
                "tsa_replica_column": _text(row.get("replica_column")),
                "profile_fl_relation": _text(row.get("target_relation")),
                "profile_fl_column": _text(row.get("target_column")),
                "join_status": "context_ambiguous",
                "gap": "right_context_not_exact:" + json.dumps(observed_paths, ensure_ascii=False, separators=(",", ":")),
                "full_attribute_path": " → ".join(v for v in (evidence.kpk_attribute, evidence.ucp_semantic_path, target) if v),
                "left_provenance_json": evidence.provenance_json,
                "right_provenance_json": _text(row.get("provenance_json")),
            })
        return rendered

    first_gap = next((dict(row) for row in right_rows if not _confirmed(row)), {})
    return [{
        "kpk_attribute": evidence.kpk_attribute,
        "kpk_evidence_classification": evidence.classification,
        "ucp_semantic_path": evidence.ucp_semantic_path,
        "ucp_endpoint_key": evidence.endpoint_key,
        "ucp_revision_id": _text(first_gap.get("source_revision_id")),
        "tsa_replica_relation": "",
        "tsa_replica_column": "",
        "profile_fl_relation": "",
        "profile_fl_column": "",
        "join_status": "unresolved",
        "gap": _text(first_gap.get("gap")) or "profile_lineage_not_confirmed",
        "full_attribute_path": evidence.kpk_attribute + " → " + evidence.ucp_semantic_path,
        "left_provenance_json": evidence.provenance_json,
        "right_provenance_json": _text(first_gap.get("provenance_json")),
    }]


def compose_many(
    evidence_rows: Iterable[KpkUcpEvidence],
    right_rows_by_endpoint: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for evidence in evidence_rows:
        for row in compose_one(evidence, right_rows_by_endpoint.get(evidence.endpoint_key, ())):
            key = (
                _text(row.get("kpk_attribute")),
                _text(row.get("ucp_semantic_path")),
                _text(row.get("profile_fl_relation")),
                _text(row.get("profile_fl_column")),
                _text(row.get("join_status")),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return sorted(rows, key=lambda row: (
        _text(row.get("kpk_attribute")),
        _text(row.get("ucp_semantic_path")),
        _text(row.get("profile_fl_relation")),
        _text(row.get("profile_fl_column")),
        _text(row.get("join_status")),
    ))
