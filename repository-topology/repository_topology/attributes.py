from __future__ import annotations

from typing import Any

from .model import HalfWire


ATTRIBUTE_NAME_COMPARISON = "exact_case_sensitive"
RENAME_INFERENCE = "forbidden"


def pair_attribute_flows(source: HalfWire, target: HalfWire) -> list[dict[str, Any]]:
    """Derive exact-name attribute crossings for one already matched half-wire pair.

    This function never decides whether repositories/half-wires match. It only
    projects attribute names that are observed on both sides of a Match.
    """
    if source.protocol != target.protocol:
        raise ValueError("matched half-wire protocol mismatch")

    if source.protocol == "http":
        flows: list[dict[str, Any]] = []
        request_names = sorted(set(source.request_field_names) & set(target.request_field_names))
        response_names = sorted(set(source.response_field_names) & set(target.response_field_names))
        if request_names:
            flows.append(
                {
                    "transport_role": "request",
                    "source_repository_id": source.repository_id,
                    "target_repository_id": target.repository_id,
                    "attribute_names": request_names,
                }
            )
        if response_names:
            flows.append(
                {
                    "transport_role": "response",
                    "source_repository_id": target.repository_id,
                    "target_repository_id": source.repository_id,
                    "attribute_names": response_names,
                }
            )
        return flows

    if source.protocol == "kafka":
        payload_names = sorted(set(source.payload_field_names) & set(target.payload_field_names))
        if payload_names:
            return [
                {
                    "transport_role": "payload",
                    "source_repository_id": source.repository_id,
                    "target_repository_id": target.repository_id,
                    "attribute_names": payload_names,
                }
            ]
    return []


def edge_attribute_flows(edge: dict[str, Any]) -> list[dict[str, Any]]:
    """Return canonical pair-preserving attribute flows stored on a v2 edge."""
    flows = edge.get("attribute_flows")
    if not isinstance(flows, list):
        raise ValueError("repository-topology/v3 edge is missing attribute_flows")
    return [flow for flow in flows if isinstance(flow, dict)]


def edge_display_attributes(edge: dict[str, Any]) -> dict[str, list[str]]:
    """Return transport-role -> exact shared names for compact graph labels."""
    return {
        str(flow["transport_role"]): list(flow.get("attribute_names") or [])
        for flow in edge_attribute_flows(edge)
    }
