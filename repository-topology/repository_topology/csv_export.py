from __future__ import annotations

import csv
import io
import json
from typing import Any

from .contracts import TOPOLOGY_CSV_FORMAT, TOPOLOGY_FORMAT


CSV_COLUMNS = (
    "csv_format",
    "record_type",
    "topology_format",
    "topology_id",
    "repository_count",
    "edge_count",
    "exact_edge_count",
    "probable_edge_count",
    "island_count",
    "attribute_name_comparison",
    "rename_inference",
    "island_id",
    "island_repository_ids_json",
    "island_edge_ids_json",
    "repository_id",
    "input_ref",
    "input_artifact_format",
    "input_artifact_id",
    "input_semantic_fingerprint",
    "input_source_inventory_id",
    "input_source_snapshot_fingerprint",
    "input_sha256",
    "edge_id",
    "source_repository_id",
    "target_repository_id",
    "protocol",
    "method",
    "matched_identity",
    "match_classification",
    "claim_classification",
    "confidence",
    "transport_role",
    "attribute_name",
    "attribute_flow_source_repository_id",
    "attribute_flow_target_repository_id",
    "attribute_flow_basis_json",
    "source_half_wires_json",
    "target_half_wires_json",
    "edge_basis_json",
    "half_wire_count",
    "matched_half_wire_count",
    "unmatched_half_wire_count",
    "repository_with_half_wire_count",
    "repository_without_half_wire_count",
    "matchability_protocol",
    "matchability_direction",
    "matchability_reason",
    "matchability_count",
    "matchability_identity_status",
    "matchability_transport_identity_kind",
    "repository_half_wire_count",
    "repository_http_inbound_count",
    "repository_http_outbound_count",
    "repository_kafka_publish_count",
    "repository_kafka_consume_count",
    "repository_matched_half_wire_count",
    "repository_unmatched_half_wire_count",
    "diagnostic_kind",
    "diagnostic_repository_id",
    "diagnostic_observed_identity_id",
    "diagnostic_protocol",
    "diagnostic_direction",
    "diagnostic_method",
    "diagnostic_path_status",
    "diagnostic_reason",
    "diagnostic_candidate_count",
    "diagnostic_max_request_field_overlap",
    "diagnostic_required_request_field_overlap",
    "diagnostic_transport_identity_kind",
    "diagnostic_identities_json",
    "record_json",
)

_DELIMITERS = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
}


def render_topology_csv(topology: dict[str, Any], *, delimiter: str = "comma") -> str:
    """Render repository-topology/v3 as one Excel-friendly long-form CSV.

    The CSV is a deterministic representation only. It does not perform matching,
    graph construction or attribute inference. Complex source records are retained
    in canonical JSON columns so the export does not silently discard provenance.
    """
    if topology.get("format") != TOPOLOGY_FORMAT:
        raise ValueError(f"CSV renderer requires {TOPOLOGY_FORMAT}")
    if delimiter not in _DELIMITERS:
        raise ValueError(f"unsupported CSV delimiter: {delimiter!r}")

    rows = topology_csv_rows(topology)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(CSV_COLUMNS),
        delimiter=_DELIMITERS[delimiter],
        lineterminator="\r\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _excel_safe_cell(row.get(column, "")) for column in CSV_COLUMNS})
    # UTF-8 BOM makes non-ASCII repository/API/attribute names open reliably in Excel.
    return "\ufeff" + stream.getvalue()


def topology_csv_rows(topology: dict[str, Any]) -> list[dict[str, Any]]:
    if topology.get("format") != TOPOLOGY_FORMAT:
        raise ValueError(f"CSV renderer requires {TOPOLOGY_FORMAT}")

    summary = topology.get("summary") or {}
    policy = topology.get("attribute_identity_policy") or {}
    common = {
        "csv_format": TOPOLOGY_CSV_FORMAT,
        "topology_format": topology.get("format", ""),
        "topology_id": topology.get("topology_id", ""),
        "repository_count": summary.get("repository_count", ""),
        "edge_count": summary.get("edge_count", ""),
        "exact_edge_count": summary.get("exact_edge_count", ""),
        "probable_edge_count": summary.get("probable_edge_count", ""),
        "island_count": summary.get("island_count", ""),
        "half_wire_count": summary.get("half_wire_count", ""),
        "matched_half_wire_count": summary.get("matched_half_wire_count", ""),
        "unmatched_half_wire_count": summary.get("unmatched_half_wire_count", ""),
        "repository_with_half_wire_count": summary.get("repository_with_half_wire_count", ""),
        "repository_without_half_wire_count": summary.get("repository_without_half_wire_count", ""),
        "attribute_name_comparison": policy.get("name_comparison", ""),
        "rename_inference": policy.get("rename_inference", ""),
    }

    inputs_by_repository = {
        str(row.get("repository_id")): row
        for row in topology.get("inputs") or []
        if isinstance(row, dict) and row.get("repository_id") is not None
    }
    islands = [row for row in topology.get("islands") or [] if isinstance(row, dict)]
    island_by_repository: dict[str, dict[str, Any]] = {}
    island_by_edge: dict[str, dict[str, Any]] = {}
    for island in islands:
        for repository_id in island.get("repository_ids") or []:
            island_by_repository[str(repository_id)] = island
        for edge_id in island.get("edge_ids") or []:
            island_by_edge[str(edge_id)] = island

    rows: list[dict[str, Any]] = []
    rows.append({**common, "record_type": "topology", "record_json": _canonical_json(summary)})

    for island in sorted(islands, key=lambda row: str(row.get("island_id", ""))):
        rows.append(
            {
                **common,
                "record_type": "island",
                **_island_columns(island),
                "record_json": _canonical_json(island),
            }
        )

    repositories = [row for row in topology.get("repositories") or [] if isinstance(row, dict)]
    for repository in sorted(repositories, key=lambda row: str(row.get("repository_id", ""))):
        repository_id = str(repository.get("repository_id", ""))
        input_row = inputs_by_repository.get(repository_id, {})
        island = island_by_repository.get(repository_id, {})
        rows.append(
            {
                **common,
                "record_type": "repository",
                **_island_columns(island),
                "repository_id": repository_id,
                "input_ref": repository.get("input_ref", ""),
                **_input_columns(input_row),
                "record_json": _canonical_json({"repository": repository, "input": input_row}),
            }
        )

    edges = [row for row in topology.get("edges") or [] if isinstance(row, dict)]
    for edge in sorted(edges, key=lambda row: str(row.get("edge_id", ""))):
        island = island_by_edge.get(str(edge.get("edge_id", "")), {})
        edge_columns = _edge_columns(edge)
        rows.append(
            {
                **common,
                "record_type": "edge",
                **_island_columns(island),
                **edge_columns,
                "record_json": _canonical_json(edge),
            }
        )
        flows = [flow for flow in edge.get("attribute_flows") or [] if isinstance(flow, dict)]
        for flow in sorted(
            flows,
            key=lambda item: (
                str(item.get("transport_role", "")),
                str(item.get("source_repository_id", "")),
                str(item.get("target_repository_id", "")),
            ),
        ):
            basis = [row for row in flow.get("basis") or [] if isinstance(row, dict)]
            for attribute_name in sorted(str(name) for name in flow.get("attribute_names") or []):
                attribute_basis = [
                    row for row in basis if str(row.get("attribute_name", "")) == attribute_name
                ]
                rows.append(
                    {
                        **common,
                        "record_type": "attribute",
                        **_island_columns(island),
                        **edge_columns,
                        "transport_role": flow.get("transport_role", ""),
                        "attribute_name": attribute_name,
                        "attribute_flow_source_repository_id": flow.get("source_repository_id", ""),
                        "attribute_flow_target_repository_id": flow.get("target_repository_id", ""),
                        "attribute_flow_basis_json": _canonical_json(attribute_basis),
                        "record_json": _canonical_json(
                            {
                                "edge_id": edge.get("edge_id"),
                                "transport_role": flow.get("transport_role"),
                                "source_repository_id": flow.get("source_repository_id"),
                                "target_repository_id": flow.get("target_repository_id"),
                                "attribute_name": attribute_name,
                                "basis": attribute_basis,
                            }
                        ),
                    }
                )

    analysis = topology.get("matchability_analysis") or {}
    analysis_summary = analysis.get("summary") or {}
    rows.append(
        {
            **common,
            "record_type": "matchability_summary",
            "record_json": _canonical_json({
                "matching_owner": analysis.get("matching_owner"),
                "matching_policy": analysis.get("matching_policy") or {},
                "summary": analysis_summary,
            }),
        }
    )

    for item in analysis.get("unmatched_reason_counts") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                **common,
                "record_type": "matchability_reason",
                "matchability_protocol": item.get("protocol", ""),
                "matchability_direction": item.get("direction", ""),
                "matchability_reason": item.get("reason", ""),
                "matchability_count": item.get("count", ""),
                "record_json": _canonical_json(item),
            }
        )

    for item in analysis.get("identity_status_counts") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                **common,
                "record_type": "identity_status",
                "matchability_protocol": item.get("protocol", ""),
                "matchability_direction": item.get("direction", ""),
                "matchability_identity_status": item.get("identity_status", ""),
                "matchability_count": item.get("count", ""),
                "record_json": _canonical_json(item),
            }
        )

    for item in analysis.get("transport_identity_kind_counts") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                **common,
                "record_type": "transport_identity_kind",
                "matchability_protocol": item.get("protocol", ""),
                "matchability_direction": item.get("direction", ""),
                "matchability_transport_identity_kind": item.get("transport_identity_kind", ""),
                "matchability_count": item.get("count", ""),
                "record_json": _canonical_json(item),
            }
        )

    for item in analysis.get("repository_stats") or []:
        if not isinstance(item, dict):
            continue
        repository_id = str(item.get("repository_id", ""))
        island = island_by_repository.get(repository_id, {})
        rows.append(
            {
                **common,
                "record_type": "repository_matchability",
                **_island_columns(island),
                "repository_id": repository_id,
                "repository_half_wire_count": item.get("half_wire_count", ""),
                "repository_http_inbound_count": item.get("http_inbound_count", ""),
                "repository_http_outbound_count": item.get("http_outbound_count", ""),
                "repository_kafka_publish_count": item.get("kafka_publish_count", ""),
                "repository_kafka_consume_count": item.get("kafka_consume_count", ""),
                "repository_matched_half_wire_count": item.get("matched_half_wire_count", ""),
                "repository_unmatched_half_wire_count": item.get("unmatched_half_wire_count", ""),
                "record_json": _canonical_json(item),
            }
        )

    diagnostics = [row for row in topology.get("diagnostics") or [] if isinstance(row, dict)]
    for diagnostic in sorted(diagnostics, key=_canonical_json):
        repository_id = str(diagnostic.get("repository_id", ""))
        island = island_by_repository.get(repository_id, {})
        rows.append(
            {
                **common,
                "record_type": "diagnostic",
                **_island_columns(island),
                "repository_id": repository_id,
                "diagnostic_kind": diagnostic.get("kind", ""),
                "diagnostic_repository_id": repository_id,
                "diagnostic_observed_identity_id": diagnostic.get("observed_identity_id", ""),
                "diagnostic_protocol": diagnostic.get("protocol", ""),
                "diagnostic_direction": diagnostic.get("direction", ""),
                "diagnostic_method": diagnostic.get("method", ""),
                "diagnostic_path_status": diagnostic.get("identity_status", ""),
                "diagnostic_reason": diagnostic.get("reason", ""),
                "diagnostic_candidate_count": diagnostic.get("candidate_count", ""),
                "diagnostic_max_request_field_overlap": diagnostic.get("max_request_field_overlap", ""),
                "diagnostic_required_request_field_overlap": diagnostic.get("required_request_field_overlap", ""),
                "diagnostic_transport_identity_kind": diagnostic.get("transport_identity_kind", ""),
                "diagnostic_identities_json": _canonical_json(diagnostic.get("identities") or []),
                "record_json": _canonical_json(diagnostic),
            }
        )
    return rows


def _input_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_artifact_format": row.get("artifact_format", ""),
        "input_artifact_id": row.get("artifact_id", ""),
        "input_semantic_fingerprint": row.get("semantic_fingerprint", ""),
        "input_source_inventory_id": row.get("source_inventory_id", ""),
        "input_source_snapshot_fingerprint": row.get("source_snapshot_fingerprint", ""),
        "input_sha256": row.get("sha256", ""),
    }


def _island_columns(island: dict[str, Any]) -> dict[str, Any]:
    if not island:
        return {}
    return {
        "island_id": island.get("island_id", ""),
        "island_repository_ids_json": _canonical_json(island.get("repository_ids") or []),
        "island_edge_ids_json": _canonical_json(island.get("edge_ids") or []),
    }


def _edge_columns(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": edge.get("edge_id", ""),
        "source_repository_id": edge.get("source_repository_id", ""),
        "target_repository_id": edge.get("target_repository_id", ""),
        "protocol": edge.get("protocol", ""),
        "method": edge.get("method", ""),
        "matched_identity": edge.get("matched_identity", ""),
        "match_classification": edge.get("match_classification", ""),
        "claim_classification": edge.get("claim_classification", ""),
        "confidence": edge.get("confidence", ""),
        "source_half_wires_json": _canonical_json(edge.get("source_half_wires") or []),
        "target_half_wires_json": _canonical_json(edge.get("target_half_wires") or []),
        "edge_basis_json": _canonical_json(edge.get("basis") or []),
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _excel_safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
