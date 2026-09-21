from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .aisl import AislPathGateway
from .contracts import BindingIndex, OUTPUT_FORMAT
from .topology import BoundaryField, boundary_fields, select_edge, wire_display_ref


def _fingerprint(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("result")
    return value if isinstance(value, Mapping) else payload


def _anchor_candidate(
    result: Mapping[str, Any],
    *,
    repository_id: str,
    interface_ids: Sequence[str],
) -> Mapping[str, Any] | None:
    candidates = result.get("source_candidates")
    if not isinstance(candidates, list):
        return None
    allowed = set(interface_ids)
    matches = [
        item for item in candidates
        if isinstance(item, Mapping)
        and str(item.get("repo_id") or "") == repository_id
        and str(item.get("owner_ref") or "") in allowed
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_side(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    interface_ids: Sequence[str],
    source_ref: str,
    direction: str,
) -> dict[str, Any]:
    first = gateway.resolve_attribute_paths(
        binding,
        source=source_ref,
        selected_repo_ids=[repository_id],
        direction=direction,
    )
    first_result = _result(first)
    query_ref = source_ref
    selection_basis = "unique_exact_display_ref"
    selected = None
    if str(first_result.get("status") or "") == "source_ambiguous":
        selected = _anchor_candidate(first_result, repository_id=repository_id, interface_ids=interface_ids)
        if selected is not None:
            query_ref = str(selected.get("value_node_id") or "")
            selection_basis = "exact_topology_interface_id"
            second = gateway.resolve_attribute_paths(
                binding,
                source=query_ref,
                selected_repo_ids=[repository_id],
                direction=direction,
            )
            response = second
            resolved = _result(second)
        else:
            response = first
            resolved = first_result
            selection_basis = "ambiguous_topology_interface_anchor"
    else:
        response = first
        resolved = first_result

    status = str(resolved.get("status") or "")
    anchor = resolved.get("source") if isinstance(resolved.get("source"), Mapping) else selected
    anchor_resolved = bool(anchor) and not status.startswith("source_") and status != "unavailable"
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": source_ref,
        "resolved_anchor": dict(anchor) if isinstance(anchor, Mapping) else None,
        "anchor_status": "resolved" if anchor_resolved else "unresolved",
        "anchor_selection_basis": selection_basis,
        "query": dict(response),
    }


def _payload_compatible(field: BoundaryField) -> bool:
    return bool(
        field.source_payload_identity
        and field.target_payload_identity
        and field.source_payload_identity == field.target_payload_identity
    )


def _gap(repository_id: str, field: BoundaryField, side: str, reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "repository_id": repository_id,
        "transport_role": field.transport_role,
        "field_path": field.field_path,
        "side": side,
    }


def build_interaction_lineage(
    topology: Mapping[str, Any],
    *,
    edge_id: str,
    bindings: BindingIndex,
    gateway: AislPathGateway,
    transport_roles: Sequence[str] = ("request", "response"),
) -> dict[str, Any]:
    edge = select_edge(topology, edge_id)
    journeys: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    used_bindings: dict[str, Any] = {}

    for role in transport_roles:
        for field in boundary_fields(edge, transport_role=role):
            source_binding = bindings.require(field.source_repository_id)
            target_binding = bindings.require(field.target_repository_id)
            used_bindings[source_binding.repository_id] = source_binding
            used_bindings[target_binding.repository_id] = target_binding
            source_ref = wire_display_ref(field.transport_role, field.field_path)

            source_side = _resolve_side(
                gateway,
                binding=source_binding,
                repository_id=field.source_repository_id,
                interface_ids=field.source_interface_ids,
                source_ref=source_ref,
                direction="reverse",
            )
            target_side = _resolve_side(
                gateway,
                binding=target_binding,
                repository_id=field.target_repository_id,
                interface_ids=field.target_interface_ids,
                source_ref=source_ref,
                direction="forward",
            )

            payload_compatible = _payload_compatible(field)
            both_anchors = source_side["anchor_status"] == "resolved" and target_side["anchor_status"] == "resolved"
            crossing_status = "resolved" if payload_compatible and both_anchors else "partial"
            crossing_basis = (
                "exact_field_path_within_matched_transport_payload"
                if crossing_status == "resolved"
                else "insufficient_exact_boundary_evidence"
            )
            if not payload_compatible:
                gaps.append(_gap(field.source_repository_id, field, "crossing", "payload_identity_not_exactly_compatible"))
            if source_side["anchor_status"] != "resolved":
                gaps.append(_gap(field.source_repository_id, field, "source", "source_boundary_anchor_unresolved"))
            if target_side["anchor_status"] != "resolved":
                gaps.append(_gap(field.target_repository_id, field, "target", "target_boundary_anchor_unresolved"))

            journey_identity = {
                "edge_id": edge_id,
                "transport_role": field.transport_role,
                "field_path": field.field_path,
                "source_repository_id": field.source_repository_id,
                "target_repository_id": field.target_repository_id,
            }
            journeys.append({
                "journey_id": "interaction_attribute_journey_" + _fingerprint(journey_identity)[:24],
                **journey_identity,
                "topology_basis": field.topology_basis,
                "crossing": {
                    "status": crossing_status,
                    "basis": crossing_basis,
                    "source_payload_identity": field.source_payload_identity,
                    "target_payload_identity": field.target_payload_identity,
                    "source_interface_ids": list(field.source_interface_ids),
                    "target_interface_ids": list(field.target_interface_ids),
                },
                "source_side": source_side,
                "target_side": target_side,
            })

    journeys.sort(key=lambda item: (item["transport_role"], item["field_path"], item["journey_id"]))
    gaps.sort(key=lambda item: (item["transport_role"], item["field_path"], item["side"], item["repository_id"], item["reason"]))
    output = {
        "format": OUTPUT_FORMAT,
        "topology_id": str(topology.get("topology_id") or ""),
        "topology_fingerprint": _fingerprint(topology),
        "edge": {
            "edge_id": str(edge.get("edge_id") or ""),
            "protocol": edge.get("protocol"),
            "method": edge.get("method"),
            "matched_identity": edge.get("matched_identity"),
            "match_classification": edge.get("match_classification"),
            "claim_classification": edge.get("claim_classification"),
            "confidence": edge.get("confidence"),
            "source_repository_id": edge.get("source_repository_id"),
            "target_repository_id": edge.get("target_repository_id"),
        },
        "aisl_inputs": [used_bindings[key].to_dict() for key in sorted(used_bindings)],
        "journeys": journeys,
        "gaps": gaps,
        "summary": {
            "journey_count": len(journeys),
            "resolved_crossing_count": sum(1 for item in journeys if item["crossing"]["status"] == "resolved"),
            "partial_crossing_count": sum(1 for item in journeys if item["crossing"]["status"] != "resolved"),
            "gap_count": len(gaps),
        },
    }
    output["content_fingerprint"] = _fingerprint(output)
    return output
