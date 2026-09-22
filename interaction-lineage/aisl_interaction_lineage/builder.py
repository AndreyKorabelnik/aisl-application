from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from .aisl import AislPathGateway
from .contracts import BindingIndex, OUTPUT_FORMAT
from .topology import (
    BoundaryField,
    boundary_fields,
    expected_interface_direction,
    local_payload_binding_symbols,
    route_boundary_ref,
    select_edge,
    wire_display_ref,
)


def _fingerprint(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("result")
    return value if isinstance(value, Mapping) else payload


def _candidate_rows(result: Mapping[str, Any], *, repository_id: str) -> list[Mapping[str, Any]]:
    rows = result.get("source_candidates")
    if not isinstance(rows, list):
        return []
    return [
        item for item in rows
        if isinstance(item, Mapping) and str(item.get("repo_id") or "") == repository_id
    ]


def _anchor_candidate_by_interface(
    result: Mapping[str, Any],
    *,
    repository_id: str,
    interface_ids: Sequence[str],
) -> Mapping[str, Any] | None:
    allowed = set(interface_ids)
    matches = [item for item in _candidate_rows(result, repository_id=repository_id) if str(item.get("owner_ref") or "") in allowed]
    return matches[0] if len(matches) == 1 else None


def _anchor_candidate_by_transport(
    result: Mapping[str, Any],
    *,
    edge: Mapping[str, Any],
    repository_id: str,
    transport_role: str,
) -> Mapping[str, Any] | None:
    protocol = str(edge.get("protocol") or "").strip().casefold()
    endpoint = str(edge.get("matched_identity") or "").strip()
    method = str(edge.get("method") or "").strip().upper()
    role = str(transport_role or "").strip().casefold()
    interface_direction = expected_interface_direction(edge, repository_id)
    if not protocol or not endpoint or role not in {"request", "response"} or interface_direction is None:
        return None

    matches: list[Mapping[str, Any]] = []
    for item in _candidate_rows(result, repository_id=repository_id):
        transport = item.get("transport")
        if not isinstance(transport, Mapping):
            continue
        if str(transport.get("protocol") or "").strip().casefold() != protocol:
            continue
        if str(transport.get("endpoint") or "").strip() != endpoint:
            continue
        if str(transport.get("payload_role") or "").strip().casefold() != role:
            continue
        if str(transport.get("interface_direction") or "").strip().casefold() != interface_direction:
            continue
        if protocol == "http" and method and str(transport.get("http_method") or "").strip().upper() != method:
            continue
        matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _operation_owner(item: Mapping[str, Any]) -> str:
    return str(item.get("operation") or "").split(".", 1)[0]


def _bean_accessors(payload_identity: str, field_path: str) -> set[str]:
    leaf = str(field_path or "").split(".")[-1]
    if not leaf:
        return set()
    suffix = leaf[0].upper() + leaf[1:]
    return {f"{payload_identity}.get{suffix}", f"{payload_identity}.is{suffix}"}


def _anchor_candidate_by_payload_owner(
    result: Mapping[str, Any],
    *,
    repository_id: str,
    payload_identity: str | None,
    field_path: str,
    direction: str,
) -> Mapping[str, Any] | None:
    payload = str(payload_identity or "").strip()
    if not payload:
        return None
    matches = [item for item in _candidate_rows(result, repository_id=repository_id) if _operation_owner(item) == payload]
    if len(matches) == 1:
        return matches[0]
    if direction == "forward" and matches:
        accessors = _bean_accessors(payload, field_path)
        getter_matches = [item for item in matches if str(item.get("operation") or "") in accessors]
        if len(getter_matches) == 1:
            return getter_matches[0]
    return None


def _iter_query_nodes(result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("source", "target"):
        value = result.get(key)
        if isinstance(value, Mapping):
            yield value
    for path in result.get("paths") or ():
        if not isinstance(path, Mapping):
            continue
        for key in ("start", "end"):
            value = path.get(key)
            if isinstance(value, Mapping):
                yield value
        for step in path.get("steps") or ():
            if not isinstance(step, Mapping):
                continue
            for key in ("source", "target"):
                value = step.get(key)
                if isinstance(value, Mapping):
                    yield value


def _query_proves_topology_field(result: Mapping[str, Any], field_path: str) -> bool:
    expected = str(field_path or "").strip()
    if not expected:
        return False
    suffix = "." + expected
    return any(
        str(node.get("display_ref") or "") == expected
        or str(node.get("display_ref") or "").endswith(suffix)
        for node in _iter_query_nodes(result)
    )


def _run_selected(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    selected: Mapping[str, Any],
    direction: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    query_ref = str(selected.get("value_node_id") or "")
    response = gateway.resolve_attribute_paths(
        binding,
        source=query_ref,
        selected_repo_ids=[repository_id],
        direction=direction,
    )
    return response, _result(response)


def _attempt_ref(
    gateway: AislPathGateway,
    *,
    binding,
    edge: Mapping[str, Any],
    transport_role: str,
    repository_id: str,
    interface_ids: Sequence[str],
    payload_identity: str | None,
    field_path: str,
    source_ref: str,
    direction: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str]:
    response = gateway.resolve_attribute_paths(
        binding,
        source=source_ref,
        selected_repo_ids=[repository_id],
        direction=direction,
    )
    result = _result(response)
    if str(result.get("status") or "") != "source_ambiguous":
        return response, result, None, "unique_exact_display_ref"

    selected = _anchor_candidate_by_interface(result, repository_id=repository_id, interface_ids=interface_ids)
    basis = "exact_topology_interface_id"
    if selected is None:
        selected = _anchor_candidate_by_transport(
            result,
            edge=edge,
            repository_id=repository_id,
            transport_role=transport_role,
        )
        basis = "exact_topology_transport_identity"
    if selected is None:
        selected = _anchor_candidate_by_payload_owner(
            result,
            repository_id=repository_id,
            payload_identity=payload_identity,
            field_path=field_path,
            direction=direction,
        )
        basis = "exact_payload_owner_accessor"
    if selected is None:
        return response, result, None, "ambiguous_exact_anchor"
    second, second_result = _run_selected(
        gateway,
        binding=binding,
        repository_id=repository_id,
        selected=selected,
        direction=direction,
    )
    return second, second_result, selected, basis


def _resolve_leaf_by_reverse_proof(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    field_path: str,
    direction: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None:
    if "." not in field_path:
        return None
    leaf = field_path.rsplit(".", 1)[-1]
    first = gateway.resolve_attribute_paths(
        binding,
        source=leaf,
        selected_repo_ids=[repository_id],
        direction="reverse",
    )
    first_result = _result(first)
    candidates: list[Mapping[str, Any]] = []
    status = str(first_result.get("status") or "")
    if status == "source_ambiguous":
        candidates = _candidate_rows(first_result, repository_id=repository_id)
    else:
        source = first_result.get("source")
        if isinstance(source, Mapping):
            candidates = [source]

    proven: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for candidate in candidates:
        proof_response, proof_result = _run_selected(
            gateway,
            binding=binding,
            repository_id=repository_id,
            selected=candidate,
            direction="reverse",
        )
        if _query_proves_topology_field(proof_result, field_path):
            proven.append((candidate, proof_response))
    if len(proven) != 1:
        return None
    selected, proof_response = proven[0]
    if direction == "reverse":
        return proof_response, _result(proof_response), selected, "exact_reverse_path_to_topology_field"
    response, result = _run_selected(
        gateway,
        binding=binding,
        repository_id=repository_id,
        selected=selected,
        direction=direction,
    )
    return response, result, selected, "exact_reverse_path_to_topology_field"


def _resolved_side(
    *,
    repository_id: str,
    binding,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    response: Mapping[str, Any],
    result: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
    basis: str,
) -> dict[str, Any]:
    status = str(result.get("status") or "")
    anchor = result.get("source") if isinstance(result.get("source"), Mapping) else selected
    anchor_resolved = bool(anchor) and not status.startswith("source_") and status != "unavailable"
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": attempted_anchors,
        "resolved_anchor": dict(anchor) if isinstance(anchor, Mapping) else None,
        "anchor_status": "resolved" if anchor_resolved else "unresolved",
        "anchor_selection_basis": basis,
        "query": dict(response),
    }


def _resolve_side(
    gateway: AislPathGateway,
    *,
    edge: Mapping[str, Any],
    field: BoundaryField,
    side: str,
    binding,
    repository_id: str,
    interface_ids: Sequence[str],
    payload_identity: str | None,
    source_ref: str,
    direction: str,
) -> dict[str, Any]:
    attempted: list[str] = []
    attempts: list[tuple[str, str]] = [(source_ref, "canonical_wire_display_ref")]
    route_ref = route_boundary_ref(edge, field.transport_role, field.field_path)
    if route_ref:
        attempts.append((route_ref, "exact_topology_route_boundary"))

    for symbol in local_payload_binding_symbols(
        edge,
        repository_id=repository_id,
        payload_identity=payload_identity,
    ):
        attempts.append((f"{symbol}.{field.field_path}", "exact_topology_local_payload_binding"))

    attempts.append((field.field_path, "exact_topology_field_path"))
    if "." not in field.field_path:
        attempts.append((f"this.{field.field_path}", "exact_payload_field"))

    seen: set[str] = set()
    last: tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None = None
    for ref, strategy in attempts:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        attempted.append(ref)
        response, result, selected, basis = _attempt_ref(
            gateway,
            binding=binding,
            edge=edge,
            transport_role=field.transport_role,
            repository_id=repository_id,
            interface_ids=interface_ids,
            payload_identity=payload_identity,
            field_path=field.field_path,
            source_ref=ref,
            direction=direction,
        )
        last = (response, result, selected, f"{strategy}:{basis}")
        status = str(result.get("status") or "")
        anchor = result.get("source") if isinstance(result.get("source"), Mapping) else selected
        if anchor is not None and not status.startswith("source_") and status != "unavailable":
            return _resolved_side(
                repository_id=repository_id,
                binding=binding,
                direction=direction,
                requested_anchor=source_ref,
                attempted_anchors=attempted,
                response=response,
                result=result,
                selected=selected,
                basis=f"{strategy}:{basis}",
            )

    leaf = _resolve_leaf_by_reverse_proof(
        gateway,
        binding=binding,
        repository_id=repository_id,
        field_path=field.field_path,
        direction=direction,
    )
    if leaf is not None:
        response, result, selected, basis = leaf
        attempted.append(field.field_path.rsplit(".", 1)[-1])
        return _resolved_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            response=response,
            result=result,
            selected=selected,
            basis=basis,
        )

    if last is None:
        response: Mapping[str, Any] = {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        result = _result(response)
        selected = None
        basis = "no_deterministic_anchor_candidate"
    else:
        response, result, selected, basis = last
    return _resolved_side(
        repository_id=repository_id,
        binding=binding,
        direction=direction,
        requested_anchor=source_ref,
        attempted_anchors=attempted,
        response=response,
        result=result,
        selected=selected,
        basis=basis,
    )


def _observed_child_expansion(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    side: Mapping[str, Any],
) -> dict[str, Any] | None:
    anchor = side.get("resolved_anchor")
    if not isinstance(anchor, Mapping):
        return None
    operation = str(anchor.get("operation") or "").strip()
    parent_ref = str(anchor.get("display_ref") or "").strip()
    if not operation or not parent_ref:
        return None
    listing = gateway.list_repository_value_nodes(
        binding,
        repository_id=repository_id,
        node_kind="field",
        operation=operation,
        max_results=500,
    )
    listing_result = _result(listing)
    prefix = parent_ref + "."
    children: list[dict[str, Any]] = []
    for node in listing_result.get("items") or ():
        if not isinstance(node, Mapping):
            continue
        display_ref = str(node.get("display_ref") or "")
        if not display_ref.startswith(prefix):
            continue
        remainder = display_ref[len(prefix):]
        if not remainder or "." in remainder:
            continue
        value_node_id = str(node.get("value_node_id") or "")
        if not value_node_id:
            continue
        query = gateway.resolve_attribute_paths(
            binding,
            source=value_node_id,
            selected_repo_ids=[repository_id],
            direction="forward",
        )
        children.append({
            "field": remainder,
            "node": dict(node),
            "query": dict(query),
        })
    if not children:
        return None
    children.sort(key=lambda item: (item["field"], str(item["node"].get("value_node_id") or "")))
    return {
        "basis": "exact_operation_local_field_prefix",
        "operation": operation,
        "parent_display_ref": parent_ref,
        "children": children,
        "listing_truncated": bool(listing_result.get("truncated")),
        "next_token": listing_result.get("next_token"),
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
                edge=edge,
                field=field,
                side="source",
                binding=source_binding,
                repository_id=field.source_repository_id,
                interface_ids=field.source_interface_ids,
                payload_identity=field.source_payload_identity,
                source_ref=source_ref,
                direction="reverse",
            )
            target_side = _resolve_side(
                gateway,
                edge=edge,
                field=field,
                side="target",
                binding=target_binding,
                repository_id=field.target_repository_id,
                interface_ids=field.target_interface_ids,
                payload_identity=field.target_payload_identity,
                source_ref=source_ref,
                direction="forward",
            )
            child_expansion = _observed_child_expansion(
                gateway,
                binding=target_binding,
                repository_id=field.target_repository_id,
                side=target_side,
            )
            if child_expansion is not None:
                target_side["observed_child_expansion"] = child_expansion

            payload_compatible = _payload_compatible(field)
            crossing_status = "resolved" if payload_compatible else "partial"
            crossing_basis = (
                "exact_field_path_within_matched_transport_payload"
                if payload_compatible
                else "insufficient_exact_boundary_evidence"
            )
            if not payload_compatible:
                gaps.append(_gap(field.source_repository_id, field, "crossing", "payload_identity_not_exactly_compatible"))
            if source_side["anchor_status"] != "resolved":
                gaps.append(_gap(field.source_repository_id, field, "source", "source_local_anchor_unresolved"))
            if target_side["anchor_status"] != "resolved":
                gaps.append(_gap(field.target_repository_id, field, "target", "target_local_anchor_unresolved"))

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
            "source_local_anchor_gap_count": sum(1 for item in gaps if item["reason"] == "source_local_anchor_unresolved"),
            "target_local_anchor_gap_count": sum(1 for item in gaps if item["reason"] == "target_local_anchor_unresolved"),
            "gap_count": len(gaps),
        },
    }
    output["content_fingerprint"] = _fingerprint(output)
    return output
