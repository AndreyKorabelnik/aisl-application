from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .contracts import CrossingUcpEvidence, KpkUcpEvidence


def _text(value: Any) -> str:
    return str(value or "").strip()


def _confirmed(row: Mapping[str, Any]) -> bool:
    return _text(row.get("status")).startswith("confirmed")


def _normalise_output_path(value: str) -> str:
    return _text(value).replace("[]", "")


def _is_selected_output_attribute(value: str, output_root: str) -> bool:
    attr = _normalise_output_path(value)
    root = _normalise_output_path(output_root)
    return bool(attr and root and (attr == root or attr.startswith(root + ".")))


def bind_kpk_consumers(
    evidence_rows: Iterable[CrossingUcpEvidence],
    interaction_rows: Iterable[Mapping[str, Any]],
    *,
    consumer_repository: str,
    output_root: str,
    interaction: str = "",
) -> list[KpkUcpEvidence]:
    """Bind CPC crossing attributes to the final KPK service egress published by Task 43.

    The join is exact on ``crossing_attribute`` after selecting one consumer
    repository and, optionally, one interaction.  No field-name or semantic
    similarity is used.  A missing/ambiguous final ``consumer_attribute`` is an
    explicit KPK-egress gap and can never be promoted to confirmed KPK↔Profile
    lineage merely because the UCP→Profile side is known.
    """
    selected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    wanted_repo = _text(consumer_repository)
    wanted_interaction = _text(interaction)
    wanted_output_root = _text(output_root)
    if not wanted_repo:
        raise ValueError("consumer_repository must not be empty")
    if not wanted_output_root:
        raise ValueError("output_root must not be empty")

    for raw in interaction_rows:
        row = dict(raw)
        if _text(row.get("role")) != "response":
            continue
        if _text(row.get("consumer_repository")) != wanted_repo:
            continue
        if wanted_interaction and _text(row.get("interaction")) != wanted_interaction:
            continue
        crossing = _text(row.get("crossing_attribute"))
        if crossing:
            selected[crossing].append(row)

    result: list[KpkUcpEvidence] = []
    for evidence in evidence_rows:
        matches = selected.get(evidence.crossing_attribute, [])
        interaction_names = sorted({_text(row.get("interaction")) for row in matches if _text(row.get("interaction"))})
        consumer_values = sorted({_text(row.get("consumer_attribute")) for row in matches})
        nonempty_consumers = [value for value in consumer_values if value]

        kpk_attribute = ""
        interaction_consumer_attribute = consumer_values[0] if len(consumer_values) == 1 else ""
        kpk_gap = ""
        chosen_interaction = wanted_interaction or (interaction_names[0] if len(interaction_names) == 1 else "")

        if not matches:
            kpk_gap = "kpk_interaction_crossing_not_found"
        elif not wanted_interaction and len(interaction_names) > 1:
            kpk_gap = "kpk_interaction_ambiguous:" + json.dumps(
                interaction_names, ensure_ascii=False, separators=(",", ":")
            )
        elif len(consumer_values) == 1 and nonempty_consumers:
            if _is_selected_output_attribute(nonempty_consumers[0], wanted_output_root):
                kpk_attribute = nonempty_consumers[0]
            else:
                kpk_gap = "kpk_consumer_attribute_outside_selected_output_root"
        elif len(consumer_values) == 1:
            kpk_gap = "kpk_consumer_attribute_not_observed"
        else:
            kpk_gap = "kpk_consumer_attribute_ambiguous:" + json.dumps(
                consumer_values, ensure_ascii=False, separators=(",", ":")
            )

        interaction_gaps = sorted({_text(row.get("gap")) for row in matches if _text(row.get("gap"))})
        interaction_paths = sorted({_text(row.get("full_attribute_path")) for row in matches if _text(row.get("full_attribute_path"))})
        result.append(KpkUcpEvidence(
            kpk_service=wanted_repo,
            kpk_interaction=chosen_interaction,
            kpk_attribute=kpk_attribute,
            kpk_output_root=wanted_output_root,
            crossing_attribute=evidence.crossing_attribute,
            interaction_consumer_attribute=interaction_consumer_attribute,
            classification=evidence.classification,
            ucp_semantic_path=evidence.ucp_semantic_path,
            endpoint_key=evidence.endpoint_key,
            kpk_gap=kpk_gap,
            interaction_gap="; ".join(interaction_gaps),
            interaction_full_attribute_path=" | OR | ".join(interaction_paths),
            provenance_json=evidence.provenance_json,
            interaction_provenance_json=json.dumps(matches, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ))
    return result


def _base_row(evidence: KpkUcpEvidence, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kpk_service": evidence.kpk_service,
        "kpk_interaction": evidence.kpk_interaction,
        "kpk_attribute": evidence.kpk_attribute,
        "kpk_output_root": evidence.kpk_output_root,
        "cpc_crossing_attribute": evidence.crossing_attribute,
        "interaction_consumer_attribute": evidence.interaction_consumer_attribute,
        "kpk_evidence_classification": evidence.classification,
        "ucp_semantic_path": evidence.ucp_semantic_path,
        "ucp_endpoint_key": evidence.endpoint_key,
        "ucp_revision_id": _text(row.get("source_revision_id")),
        "tsa_replica_relation": _text(row.get("replica_relation")),
        "tsa_replica_column": _text(row.get("replica_column")),
        "profile_fl_relation": _text(row.get("target_relation")),
        "profile_fl_column": _text(row.get("target_column")),
        "kpk_interaction_gap": evidence.interaction_gap,
        "left_provenance_json": evidence.provenance_json,
        "kpk_interaction_provenance_json": evidence.interaction_provenance_json,
        "right_provenance_json": _text(row.get("provenance_json")),
    }


def _path(evidence: KpkUcpEvidence, replica: str, target: str) -> str:
    upstream = " ← ".join(
        value for value in (evidence.kpk_attribute, evidence.crossing_attribute, evidence.ucp_semantic_path) if value
    )
    if not evidence.kpk_attribute:
        upstream = f"[KPK egress unresolved for {evidence.kpk_service}] ← {evidence.crossing_attribute} ← {evidence.ucp_semantic_path}"
    downstream = " → ".join(value for value in (replica, target) if value)
    return upstream + ((" → " + downstream) if downstream else "")


def compose_one(
    evidence: KpkUcpEvidence,
    right_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compose a proven KPK egress→CPC crossing→UCP fact with Task46 UCP→Profile rows."""
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
        out = _base_row(evidence, row)
        if evidence.kpk_attribute:
            out.update({
                "join_status": "confirmed_exact_ucp_semantic_path_and_kpk_egress",
                "gap": _text(row.get("gap")),
            })
        else:
            out.update({
                "join_status": "unresolved_kpk_egress",
                "gap": evidence.kpk_gap or "kpk_consumer_attribute_not_observed",
            })
        out["full_attribute_path"] = _path(evidence, replica, target)
        result.append(out)
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
            out = _base_row(evidence, row)
            right_gap = "right_context_not_exact:" + json.dumps(observed_paths, ensure_ascii=False, separators=(",", ":"))
            if evidence.kpk_attribute:
                out.update({"join_status": "context_ambiguous", "gap": right_gap})
            else:
                out.update({
                    "join_status": "unresolved_kpk_egress",
                    "gap": ";".join(value for value in (evidence.kpk_gap, right_gap) if value),
                })
            out["full_attribute_path"] = _path(evidence, "", target)
            rendered.append(out)
        return rendered

    first_gap = next((dict(row) for row in right_rows if not _confirmed(row)), {})
    out = _base_row(evidence, first_gap)
    gaps = [
        value for value in (
            evidence.kpk_gap,
            _text(first_gap.get("gap")) or "profile_lineage_not_confirmed",
        ) if value
    ]
    out.update({
        "join_status": "unresolved_kpk_egress" if not evidence.kpk_attribute else "unresolved_profile_lineage",
        "gap": ";".join(gaps),
        "full_attribute_path": _path(evidence, "", ""),
    })
    return [out]


def compose_many(
    evidence_rows: Iterable[KpkUcpEvidence],
    right_rows_by_endpoint: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str, str]] = set()
    for evidence in evidence_rows:
        for row in compose_one(evidence, right_rows_by_endpoint.get(evidence.endpoint_key, ())):
            key = (
                _text(row.get("kpk_service")),
                _text(row.get("kpk_attribute")),
                _text(row.get("cpc_crossing_attribute")),
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
        _text(row.get("kpk_service")),
        _text(row.get("kpk_attribute")),
        _text(row.get("cpc_crossing_attribute")),
        _text(row.get("ucp_semantic_path")),
        _text(row.get("profile_fl_relation")),
        _text(row.get("profile_fl_column")),
        _text(row.get("join_status")),
    ))
