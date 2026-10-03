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
        selected_repo_ids=binding.query_repo_ids(repository_id),
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
        selected_repo_ids=binding.query_repo_ids(repository_id),
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


def _exact_topology_suffix_refs(field_path: str) -> tuple[str, ...]:
    parts = [part for part in str(field_path or "").strip().split(".") if part]
    # Keep at least two exact structural segments. A one-segment leaf is handled
    # separately by reverse proof because it is too weak to establish ownership.
    return tuple(".".join(parts[index:]) for index in range(1, max(1, len(parts) - 1)))


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
        selected_repo_ids=binding.query_repo_ids(repository_id),
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


_NODE_PAGE_SIZE = 500
_STRUCTURAL_NODE_KINDS = {"field", "derivation"}


def _repository_node_catalog(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    cache: dict[tuple[str, str, str], tuple[list[Mapping[str, Any]], bool]],
) -> tuple[list[Mapping[str, Any]], bool]:
    key = (str(binding.system_id), str(binding.revision_id), repository_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    items: list[Mapping[str, Any]] = []
    page_token = ""
    seen_tokens: set[str] = set()
    complete = True
    while True:
        listing = gateway.list_repository_value_nodes(
            binding,
            repository_id=repository_id,
            max_results=_NODE_PAGE_SIZE,
            page_token=page_token,
        )
        result = _result(listing)
        rows = result.get("items")
        if not isinstance(rows, list):
            complete = False
            break
        items.extend(item for item in rows if isinstance(item, Mapping))
        next_token = str(result.get("next_token") or "")
        truncated = bool(result.get("truncated"))
        if not truncated:
            break
        if not next_token or next_token in seen_tokens:
            complete = False
            break
        seen_tokens.add(next_token)
        page_token = next_token

    value = (items, complete)
    cache[key] = value
    return value


def _node_payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("payload_json")
    return value if isinstance(value, Mapping) else {}


def _source_occurrence(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _node_payload(item).get("source_occurrence")
    return value if isinstance(value, Mapping) else {}


def _material_source_origin_gap(
    side: Mapping[str, Any],
    *,
    catalog: Sequence[Mapping[str, Any]],
    catalog_complete: bool,
) -> Mapping[str, Any] | None:
    """Classify only mechanically observed external source-origin loss.

    A resolved transport/local anchor can still end in a partial reverse path.
    That is not automatically a product gap: ordinary literals, locals, fields,
    or deliberate structural terminals remain useful observed endpoints.  The
    narrow material case handled here is a projected child whose exact object
    occurrence is an external/unresolved method result.  Public value-node
    payload already preserves both occurrence identities, so this classification
    adds no source inference and does not guess an external owner/artifact.
    """
    if not catalog_complete or str(side.get("anchor_status") or "") != "resolved":
        return None

    result = _result(side.get("query") if isinstance(side.get("query"), Mapping) else {})
    paths = [item for item in result.get("paths") or () if isinstance(item, Mapping)]
    if not paths:
        return None

    by_value_node_id = {
        str(item.get("value_node_id") or ""): item
        for item in catalog
        if str(item.get("value_node_id") or "")
    }
    by_occurrence_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in catalog:
        occurrence_id = str(_source_occurrence(item).get("occurrence_id") or "")
        if occurrence_id:
            by_occurrence_id.setdefault(occurrence_id, []).append(item)

    evidence: list[dict[str, Any]] = []
    for path in paths:
        end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
        terminal_id = str(end.get("value_node_id") or "")
        terminal_item = by_value_node_id.get(terminal_id)
        if terminal_item is None:
            continue
        terminal_occurrence = _source_occurrence(terminal_item)
        if str(terminal_occurrence.get("occurrence_kind") or "") != "projected_object_field":
            continue
        object_occurrence_id = str(terminal_occurrence.get("object_occurrence_id") or "")
        if not object_occurrence_id:
            continue
        parent_items = by_occurrence_id.get(object_occurrence_id, [])
        if len(parent_items) != 1:
            continue
        parent_occurrence = _source_occurrence(parent_items[0])
        if str(parent_occurrence.get("occurrence_kind") or "") != "method_invocation":
            continue
        if str(parent_occurrence.get("resolution_status") or "") != "external_or_unresolved":
            continue
        evidence.append({
            "terminal_value_node_id": terminal_id,
            "terminal_display_ref": str(terminal_item.get("display_ref") or end.get("display_ref") or ""),
            "parent_occurrence_id": object_occurrence_id,
            "parent_display_ref": str(parent_items[0].get("display_ref") or parent_occurrence.get("field_path") or ""),
            "parent_declared_type": str(parent_occurrence.get("declared_type") or ""),
            "parent_method_name": str(parent_occurrence.get("method_name") or ""),
            "classification_basis": "published_projected_field_parent_external_method_result",
        })

    if not evidence:
        return None
    unique = {
        (item["terminal_value_node_id"], item["parent_occurrence_id"]): item
        for item in evidence
    }
    ordered = [unique[key] for key in sorted(unique)]
    return {
        "reason": "source_external_origin_unresolved",
        "evidence": ordered,
    }


def _route_wire_candidates(
    catalog: Sequence[Mapping[str, Any]],
    *,
    edge: Mapping[str, Any],
    repository_id: str,
    transport_role: str,
    field_path: str | None = None,
) -> list[Mapping[str, Any]]:
    protocol = str(edge.get("protocol") or "").strip().casefold()
    endpoint = str(edge.get("matched_identity") or "").strip()
    method = str(edge.get("method") or "").strip().upper()
    role = str(transport_role or "").strip().casefold()
    expected_field = str(field_path or "").strip()
    if not protocol or not endpoint or role not in {"request", "response"}:
        return []

    matches: list[Mapping[str, Any]] = []
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") != "wire_field":
            continue
        if expected_field and str(item.get("wire_path") or "").strip() != expected_field:
            continue
        transport = _node_payload(item).get("transport")
        if not isinstance(transport, Mapping):
            continue
        if str(transport.get("protocol") or "").strip().casefold() != protocol:
            continue
        if str(transport.get("endpoint") or "").strip() != endpoint:
            continue
        if str(transport.get("payload_role") or "").strip().casefold() != role:
            continue
        if str(transport.get("interface_direction") or "").strip().casefold() != "outbound":
            continue
        if protocol == "http" and method and str(transport.get("http_method") or "").strip().upper() != method:
            continue
        matches.append(item)

    unique: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in matches:
        signature = (
            str(item.get("operation") or ""),
            str(item.get("wire_path") or ""),
            str(item.get("owner_ref") or ""),
        )
        current = unique.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            unique[signature] = item
    return [unique[key] for key in sorted(unique)]


def _source_counterpart_shape_proof(
    edge: Mapping[str, Any],
    *,
    field: BoundaryField,
) -> list[Mapping[str, Any]]:
    if not field.source_payload_identity or field.source_payload_identity != field.target_payload_identity:
        return []
    if "." in field.field_path:
        return []

    rows: list[Mapping[str, Any]] = []
    for flow in edge.get("attribute_flows") or ():
        if not isinstance(flow, Mapping):
            continue
        if str(flow.get("transport_role") or "").strip().casefold() != field.transport_role:
            continue
        if str(flow.get("source_repository_id") or "") != field.source_repository_id:
            continue
        if str(flow.get("target_repository_id") or "") != field.target_repository_id:
            continue
        for basis in flow.get("basis") or ():
            if not isinstance(basis, Mapping):
                continue
            if str(basis.get("attribute_name") or "") != field.field_path:
                continue
            rows.append(basis)
    if not rows:
        return []

    source_interfaces = set(field.source_interface_ids)
    target_interfaces = set(field.target_interface_ids)
    payload = field.source_payload_identity
    for item in rows:
        if str(item.get("evidence_mode") or "") != "exact_payload_identity_counterpart_shape":
            return []
        if str(item.get("payload_identity") or "") != payload:
            return []
        if str(item.get("source_shape_status") or "") != "unavailable_external_declaration":
            return []
        if str(item.get("target_shape_status") or "") != "available_local_declaration":
            return []
        source_interface = str(item.get("edge_source_interface_id") or "")
        target_interface = str(item.get("edge_target_interface_id") or "")
        if source_interface and source_interface not in source_interfaces:
            return []
        if target_interface and target_interface not in target_interfaces:
            return []
    return rows


def _published_route_wire_side(
    *,
    repository_id: str,
    binding,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": [*attempted_anchors, str(selected.get("value_node_id") or "")],
        "resolved_anchor": dict(selected),
        "anchor_status": "resolved",
        "anchor_selection_basis": "published_route_wire_field:exact_transport_and_field",
        "query": {
            "result": {
                "status": "resolved_terminal",
                "source": dict(selected),
                "paths": [],
                "gaps": [],
            }
        },
        "terminal_proof": {
            "published_wire_field": True,
            "exact_transport_context": True,
        },
    }


def _operation_accepts_payload(
    catalog: Sequence[Mapping[str, Any]],
    *,
    operation: str,
    payload_identity: str,
) -> bool:
    return any(
        str(item.get("operation") or "") == operation
        and str(item.get("type_ref") or "") == payload_identity
        and str(item.get("node_kind") or "") in {"parameter", "return_value"}
        for item in catalog
    )


def _payload_scoped_structural_candidates(
    catalog: Sequence[Mapping[str, Any]],
    *,
    repository_id: str,
    payload_identity: str,
    field_path: str,
) -> list[Mapping[str, Any]]:
    nested = "." in field_path
    suffix = "." + field_path
    candidates: list[Mapping[str, Any]] = []
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") not in _STRUCTURAL_NODE_KINDS:
            continue
        display_ref = str(item.get("display_ref") or "")
        if display_ref != field_path and not (nested and display_ref.endswith(suffix)):
            continue
        operation = str(item.get("operation") or "")
        if not operation or not _operation_accepts_payload(
            catalog,
            operation=operation,
            payload_identity=payload_identity,
        ):
            continue
        candidates.append(item)

    # Multiple source occurrences of the same structural expression are equivalent
    # for anchor selection. Keep one stable representative per semantic signature.
    unique: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for item in candidates:
        signature = (
            str(item.get("operation") or ""),
            str(item.get("display_ref") or ""),
            str(item.get("node_kind") or ""),
            str(item.get("source_path") or ""),
        )
        current = unique.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            unique[signature] = item
    return [unique[key] for key in sorted(unique)]


def _payload_instance_scoped_structural_candidates(
    catalog: Sequence[Mapping[str, Any]],
    *,
    repository_id: str,
    payload_identity: str,
    field_path: str,
) -> list[Mapping[str, Any]]:
    payload_instances: dict[str, set[str]] = {}
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("type_ref") or "") != payload_identity:
            continue
        if str(item.get("node_kind") or "") not in {"parameter", "local_value", "return_value"}:
            continue
        operation = str(item.get("operation") or "")
        display_ref = str(item.get("display_ref") or "")
        if operation and display_ref:
            payload_instances.setdefault(operation, set()).add(display_ref)

    candidates: list[Mapping[str, Any]] = []
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") not in _STRUCTURAL_NODE_KINDS:
            continue
        operation = str(item.get("operation") or "")
        display_ref = str(item.get("display_ref") or "")
        if not operation or not display_ref:
            continue
        if any(display_ref == f"{payload_ref}.{field_path}" for payload_ref in payload_instances.get(operation, ())):
            candidates.append(item)

    unique: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for item in candidates:
        signature = (
            str(item.get("operation") or ""),
            str(item.get("display_ref") or ""),
            str(item.get("node_kind") or ""),
            str(item.get("source_path") or ""),
        )
        current = unique.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            unique[signature] = item
    return [unique[key] for key in sorted(unique)]


def _source_published_fallback(
    gateway: AislPathGateway,
    *,
    edge: Mapping[str, Any],
    field: BoundaryField,
    binding,
    repository_id: str,
    payload_identity: str | None,
    field_path: str,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    cache: dict[tuple[str, str, str], tuple[list[Mapping[str, Any]], bool]],
) -> dict[str, Any] | None:
    payload = str(payload_identity or "").strip()
    if direction != "reverse" or not payload or not field_path:
        return None
    catalog, complete = _repository_node_catalog(
        gateway,
        binding=binding,
        repository_id=repository_id,
        cache=cache,
    )
    if not complete:
        return None
    candidates = _payload_instance_scoped_structural_candidates(
        catalog,
        repository_id=repository_id,
        payload_identity=payload,
        field_path=field_path,
    )
    if len(candidates) > 1:
        return None
    if len(candidates) == 1:
        selected = candidates[0]
        response, result = _run_selected(
            gateway,
            binding=binding,
            repository_id=repository_id,
            selected=selected,
            direction=direction,
        )
        status = str(result.get("status") or "")
        source = result.get("source")
        if not isinstance(source, Mapping) or status.startswith("source_") or status == "unavailable":
            return None
        attempted = [*attempted_anchors, str(selected.get("value_node_id") or "")]
        return _resolved_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=requested_anchor,
            attempted_anchors=attempted,
            response=response,
            result=result,
            selected=selected,
            basis="published_payload_instance_structural_candidate:unique_semantic_node",
        )

    wire_candidates = _route_wire_candidates(
        catalog,
        edge=edge,
        repository_id=repository_id,
        transport_role=field.transport_role,
        field_path=field.field_path,
    )
    if len(wire_candidates) == 1:
        return _published_route_wire_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=requested_anchor,
            attempted_anchors=attempted_anchors,
            selected=wire_candidates[0],
        )
    if wire_candidates:
        return None

    counterpart_proof = _source_counterpart_shape_proof(edge, field=field)
    if not counterpart_proof:
        return None
    route_nodes = _route_wire_candidates(
        catalog,
        edge=edge,
        repository_id=repository_id,
        transport_role=field.transport_role,
    )
    route_interfaces = {
        (
            str(item.get("operation") or "").strip(),
            str(item.get("owner_ref") or "").strip(),
        )
        for item in route_nodes
        if str(item.get("operation") or "").strip() and str(item.get("owner_ref") or "").strip()
    }
    if len(route_interfaces) != 1:
        return None
    operation, route_owner_ref = next(iter(route_interfaces))
    payload_instances = [
        item
        for item in catalog
        if str(item.get("repo_id") or "") == repository_id
        and str(item.get("operation") or "") == operation
        and str(item.get("type_ref") or "") == payload
        and str(item.get("node_kind") or "") in {"parameter", "local_value", "return_value"}
        and str(item.get("display_ref") or "").strip()
    ]
    semantic_instances: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in payload_instances:
        signature = (
            str(item.get("node_kind") or ""),
            str(item.get("display_ref") or ""),
            str(item.get("source_path") or ""),
        )
        current = semantic_instances.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            semantic_instances[signature] = item
    if len(semantic_instances) != 1:
        return None
    selected_payload = next(iter(semantic_instances.values()))
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": [*attempted_anchors, str(selected_payload.get("value_node_id") or "")],
        "resolved_anchor": dict(selected_payload),
        "anchor_status": "terminal",
        "anchor_selection_basis": "topology_counterpart_shape_with_unique_published_payload_instance:resolved_terminal",
        "query": {
            "result": {
                "status": "resolved_terminal",
                "source": dict(selected_payload),
                "paths": [],
                "gaps": [],
            }
        },
        "terminal_proof": {
            "payload_identity": payload,
            "field_path": field.field_path,
            "operation": operation,
            "repository_value_node_scan_complete": True,
            "exact_route_interface_count": 1,
            "route_owner_ref": route_owner_ref,
            "exact_payload_instance_count": 1,
            "topology_basis": [dict(item) for item in counterpart_proof],
        },
    }


def _target_published_fallback(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    payload_identity: str | None,
    field_path: str,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    cache: dict[tuple[str, str, str], tuple[list[Mapping[str, Any]], bool]],
) -> dict[str, Any] | None:
    payload = str(payload_identity or "").strip()
    if direction != "forward" or not payload or not field_path:
        return None
    catalog, complete = _repository_node_catalog(
        gateway,
        binding=binding,
        repository_id=repository_id,
        cache=cache,
    )
    if not complete:
        return None
    candidates = _payload_scoped_structural_candidates(
        catalog,
        repository_id=repository_id,
        payload_identity=payload,
        field_path=field_path,
    )
    if len(candidates) == 1:
        selected = candidates[0]
        response, result = _run_selected(
            gateway,
            binding=binding,
            repository_id=repository_id,
            selected=selected,
            direction=direction,
        )
        status = str(result.get("status") or "")
        source = result.get("source")
        if isinstance(source, Mapping) and not status.startswith("source_") and status != "unavailable":
            attempted = [*attempted_anchors, str(selected.get("value_node_id") or "")]
            return _resolved_side(
                repository_id=repository_id,
                binding=binding,
                direction=direction,
                requested_anchor=requested_anchor,
                attempted_anchors=attempted,
                response=response,
                result=result,
                selected=selected,
                basis="published_payload_structural_candidate:unique_semantic_node",
            )
    if candidates:
        return None

    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": list(attempted_anchors),
        "resolved_anchor": None,
        "anchor_status": "terminal",
        "anchor_selection_basis": "complete_published_value_node_scan:no_payload_scoped_field_specific_use",
        "query": {
            "result": {
                "status": "resolved_terminal",
                "paths": [],
                "gaps": [],
            }
        },
        "terminal_proof": {
            "payload_identity": payload,
            "field_path": field_path,
            "repository_value_node_scan_complete": True,
            "payload_scoped_structural_candidate_count": 0,
        },
    }


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


def _local_continuation_score(
    result: Mapping[str, Any],
    *,
    anchor: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    """Rank only exact deterministic anchors by observed local continuation.

    Different exact aliases can identify the same transport field.  A wire alias
    often resolves only to itself while an exact local payload alias reaches the
    already-published repository-local value-flow.  Prefer the alias that exposes
    more observed continuation; never use names, fuzzy matching, or semantic
    inference.  Stable attempt order remains the tie-breaker.
    """
    paths = [item for item in result.get("paths") or () if isinstance(item, Mapping)]
    anchor_id = str(anchor.get("value_node_id") or "")
    anchor_ref = str(anchor.get("display_ref") or "")
    max_steps = 0
    non_self_paths = 0
    transformed_paths = 0
    for path in paths:
        steps = [item for item in path.get("steps") or () if isinstance(item, Mapping)]
        max_steps = max(max_steps, len(steps))
        if steps:
            transformed_paths += 1
        end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
        end_id = str(end.get("value_node_id") or "")
        end_ref = str(end.get("display_ref") or "")
        if (anchor_id and end_id and end_id != anchor_id) or (anchor_ref and end_ref and end_ref != anchor_ref):
            non_self_paths += 1
    return (max_steps, non_self_paths, transformed_paths, len(paths))


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
    node_catalog_cache: dict[tuple[str, str, str], tuple[list[Mapping[str, Any]], bool]] | None = None,
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
    for suffix_ref in _exact_topology_suffix_refs(field.field_path):
        attempts.append((suffix_ref, "exact_topology_structural_suffix"))
    if "." not in field.field_path:
        attempts.append((f"this.{field.field_path}", "exact_payload_field"))

    seen: set[str] = set()
    last: tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None = None
    best: tuple[tuple[int, int, int, int], int, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None = None
    for attempt_index, (ref, strategy) in enumerate(attempts):
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
        resolved_basis = f"{strategy}:{basis}"
        last = (response, result, selected, resolved_basis)
        status = str(result.get("status") or "")
        anchor = result.get("source") if isinstance(result.get("source"), Mapping) else selected
        if anchor is not None and not status.startswith("source_") and status != "unavailable":
            score = _local_continuation_score(result, anchor=anchor)
            candidate = (score, -attempt_index, response, result, selected, resolved_basis)
            if best is None or candidate[:2] > best[:2]:
                best = candidate

    if best is not None:
        _score, _order, response, result, selected, basis = best
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

    if side == "source":
        fallback = _source_published_fallback(
            gateway,
            edge=edge,
            field=field,
            binding=binding,
            repository_id=repository_id,
            payload_identity=payload_identity,
            field_path=field.field_path,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            cache=node_catalog_cache if node_catalog_cache is not None else {},
        )
        if fallback is not None:
            return fallback

    if side == "target":
        fallback = _target_published_fallback(
            gateway,
            binding=binding,
            repository_id=repository_id,
            payload_identity=payload_identity,
            field_path=field.field_path,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            cache=node_catalog_cache if node_catalog_cache is not None else {},
        )
        if fallback is not None:
            return fallback

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
            selected_repo_ids=binding.query_repo_ids(repository_id),
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



def _side_has_observed_continuation(side: Mapping[str, Any]) -> bool:
    if str(side.get("anchor_status") or "") != "resolved":
        return False
    anchor = side.get("resolved_anchor")
    query = side.get("query")
    if not isinstance(anchor, Mapping) or not isinstance(query, Mapping):
        return False
    result = _result(query)
    score = _local_continuation_score(result, anchor=anchor)
    return score[0] > 0 or score[1] > 0


def _is_collection_type(type_ref: str) -> bool:
    text = str(type_ref or "").replace(" ", "")
    return text.endswith("[]") or any(
        marker in text for marker in ("List<", "Set<", "Collection<", "Iterable<")
    )


def _source_boundary_shape_fields(
    catalog: Sequence[Mapping[str, Any]],
    *,
    edge: Mapping[str, Any],
    parent_fields: Sequence[BoundaryField],
    expandable_parents: set[str],
) -> list[BoundaryField]:
    """Project exact published source boundary structure under used topology branches.

    Topology remains the transport owner: this only extends an already matched edge
    under a published topology parent.  Structure comes from the exact route/payload
    boundary facts already published by AISL.  The most-specific published topology
    parent gates each descendant, so an unused sibling branch cannot expand merely
    because its schema exists.
    """
    if not parent_fields:
        return []
    exemplar = parent_fields[0]
    endpoint = str(edge.get("matched_identity") or "").strip()
    role = exemplar.transport_role
    payload_identity = str(exemplar.source_payload_identity or "").strip()
    repository_id = exemplar.source_repository_id

    raw_nodes: dict[str, Mapping[str, Any]] = {}
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") != "field":
            continue
        payload = _node_payload(item)
        occurrence = payload.get("source_occurrence")
        if not isinstance(occurrence, Mapping):
            continue
        boundary_kind = str(occurrence.get("boundary_kind") or "").strip().casefold()
        edge_protocol = str(edge.get("protocol") or "").strip().casefold()
        if edge_protocol == "http":
            if boundary_kind not in {"http", "rest"}:
                continue
        elif boundary_kind != edge_protocol:
            continue
        if str(occurrence.get("boundary_path") or "").strip() != endpoint:
            continue
        if str(occurrence.get("payload_role") or "").strip().casefold() != role:
            continue
        if str(occurrence.get("interaction_direction") or "").strip().casefold() != "outbound":
            continue
        if payload_identity and str(occurrence.get("payload_type") or "").strip() != payload_identity:
            continue
        raw_path = str(occurrence.get("wire_field_path") or item.get("wire_path") or "").strip()
        if not raw_path:
            continue
        current = raw_nodes.get(raw_path)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            raw_nodes[raw_path] = item

    if not raw_nodes:
        return []

    collection_prefixes = {
        path for path, item in raw_nodes.items()
        if _is_collection_type(str(item.get("type_ref") or ""))
    }

    def canonical_path(raw_path: str) -> str:
        parts = raw_path.split(".")
        out: list[str] = []
        prefix: list[str] = []
        for index, part in enumerate(parts):
            prefix.append(part)
            rendered = part
            if index < len(parts) - 1 and ".".join(prefix) in collection_prefixes:
                rendered += "[]"
            out.append(rendered)
        return ".".join(out)

    base_paths = {field.field_path for field in parent_fields}
    result: list[BoundaryField] = []
    seen: set[str] = set()
    for raw_path in sorted(raw_nodes):
        path = canonical_path(raw_path)
        if path in base_paths:
            continue
        matching_parents = [
            parent for parent in base_paths
            if path.startswith(parent + ".") or path.startswith(parent + "[]" + ".")
        ]
        if not matching_parents:
            continue
        most_specific = max(matching_parents, key=lambda value: (len(value), value))
        if most_specific not in expandable_parents:
            continue
        if path in seen:
            continue
        seen.add(path)
        result.append(BoundaryField(
            transport_role=role,
            field_path=path,
            source_repository_id=exemplar.source_repository_id,
            target_repository_id=exemplar.target_repository_id,
            source_interface_ids=exemplar.source_interface_ids,
            target_interface_ids=exemplar.target_interface_ids,
            source_payload_identity=exemplar.source_payload_identity,
            target_payload_identity=exemplar.target_payload_identity,
            topology_basis="published_source_boundary_shape_under_observed_topology_branch",
        ))
    return result


def _structural_terminal_side(
    *, repository_id: str, binding, direction: str, field: BoundaryField,
) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": wire_display_ref(field.transport_role, field.field_path),
        "attempted_anchors": [],
        "resolved_anchor": None,
        "anchor_status": "terminal",
        "anchor_selection_basis": "exact_transport_structure_no_observed_local_use",
        "query": {"result": {"status": "resolved_terminal", "paths": [], "gaps": []}},
        "terminal_proof": {
            "source_boundary_structure": True,
            "payload_identity_exact": _payload_compatible(field),
            "field_path": field.field_path,
        },
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
    node_catalog_cache: dict[tuple[str, str, str], tuple[list[Mapping[str, Any]], bool]] = {}

    def process(field: BoundaryField, *, structural_expansion: bool = False) -> dict[str, Any]:
        source_binding = bindings.require(field.source_repository_id)
        target_binding = bindings.require(field.target_repository_id)
        used_bindings[source_binding.repository_id] = source_binding
        used_bindings[target_binding.repository_id] = target_binding
        source_ref = wire_display_ref(field.transport_role, field.field_path)
        source_side = _resolve_side(
            gateway, edge=edge, field=field, side="source", binding=source_binding,
            repository_id=field.source_repository_id, interface_ids=field.source_interface_ids,
            payload_identity=field.source_payload_identity, source_ref=source_ref, direction="reverse",
            node_catalog_cache=node_catalog_cache,
        )
        target_side = _resolve_side(
            gateway, edge=edge, field=field, side="target", binding=target_binding,
            repository_id=field.target_repository_id, interface_ids=field.target_interface_ids,
            payload_identity=field.target_payload_identity, source_ref=source_ref, direction="forward",
            node_catalog_cache=node_catalog_cache,
        )
        if structural_expansion and _payload_compatible(field):
            # A structural-expanded row asserts only exact transport shape beneath
            # an already-observed topology branch.  If repository-local value flow
            # does not resolve on either side, preserve that distinction as a
            # terminal/no-field-specific-flow state rather than manufacturing a
            # lineage gap.  Any observed local flow still wins and stays resolved.
            if source_side["anchor_status"] == "unresolved":
                source_side = _structural_terminal_side(
                    repository_id=field.source_repository_id, binding=source_binding,
                    direction="reverse", field=field,
                )
            if target_side["anchor_status"] == "unresolved":
                target_side = _structural_terminal_side(
                    repository_id=field.target_repository_id, binding=target_binding,
                    direction="forward", field=field,
                )

        payload_compatible = _payload_compatible(field)
        crossing_status = "resolved" if payload_compatible else "partial"
        crossing_basis = (
            "exact_field_path_within_matched_transport_payload"
            if payload_compatible else "insufficient_exact_boundary_evidence"
        )
        if not payload_compatible:
            gaps.append(_gap(field.source_repository_id, field, "crossing", "payload_identity_not_exactly_compatible"))
        if source_side["anchor_status"] == "unresolved":
            gaps.append(_gap(field.source_repository_id, field, "source", "source_local_anchor_unresolved"))
        if target_side["anchor_status"] == "unresolved":
            gaps.append(_gap(field.target_repository_id, field, "target", "target_local_anchor_unresolved"))

        if source_side["anchor_status"] == "resolved" and not structural_expansion:
            source_catalog, source_catalog_complete = _repository_node_catalog(
                gateway,
                binding=source_binding,
                repository_id=field.source_repository_id,
                cache=node_catalog_cache,
            )
            material_gap = _material_source_origin_gap(
                source_side,
                catalog=source_catalog,
                catalog_complete=source_catalog_complete,
            )
            if material_gap is not None:
                gap = _gap(
                    field.source_repository_id, field, "source",
                    str(material_gap["reason"]),
                )
                gap["evidence"] = list(material_gap.get("evidence") or ())
                gaps.append(gap)

        identity = {
            "edge_id": edge_id,
            "transport_role": field.transport_role,
            "field_path": field.field_path,
            "source_repository_id": field.source_repository_id,
            "target_repository_id": field.target_repository_id,
        }
        journey = {
            "journey_id": "interaction_attribute_journey_" + _fingerprint(identity)[:24],
            **identity,
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
        }
        journeys.append(journey)
        return journey

    for role in transport_roles:
        base_fields = boundary_fields(edge, transport_role=role)
        base_journeys: dict[str, dict[str, Any]] = {}
        for field in base_fields:
            base_journeys[field.field_path] = process(field)

        # Old topology fixtures intentionally publish only stable branch roots.
        # Extend those roots from exact source route-boundary facts, but only below
        # the most-specific topology branch that has observed consumer continuation.
        expandable = {
            path for path, journey in base_journeys.items()
            if _side_has_observed_continuation(journey["target_side"])
        }
        if base_fields and expandable:
            source_binding = bindings.require(base_fields[0].source_repository_id)
            catalog, complete = _repository_node_catalog(
                gateway, binding=source_binding,
                repository_id=base_fields[0].source_repository_id, cache=node_catalog_cache,
            )
            if complete:
                for field in _source_boundary_shape_fields(
                    catalog, edge=edge, parent_fields=base_fields, expandable_parents=expandable,
                ):
                    process(field, structural_expansion=True)

    # Attach direct observed target child evidence for diagnostics/UI only; the
    # canonical journey rows above already include permitted structural expansion.
    for journey in journeys:
        target_binding = bindings.require(journey["target_repository_id"])
        child_expansion = _observed_child_expansion(
            gateway, binding=target_binding, repository_id=journey["target_repository_id"],
            side=journey["target_side"],
        )
        if child_expansion is not None:
            journey["target_side"]["observed_child_expansion"] = child_expansion

    journeys.sort(key=lambda item: (item["transport_role"], item["field_path"], item["journey_id"]))
    gaps.sort(key=lambda item: (item["transport_role"], item["field_path"], item["side"], item["repository_id"], item["reason"]))
    output = {
        "format": OUTPUT_FORMAT,
        "topology_id": str(topology.get("topology_id") or ""),
        "topology_fingerprint": _fingerprint(topology),
        "edge": {
            "edge_id": str(edge.get("edge_id") or ""), "protocol": edge.get("protocol"),
            "method": edge.get("method"), "matched_identity": edge.get("matched_identity"),
            "match_classification": edge.get("match_classification"),
            "claim_classification": edge.get("claim_classification"), "confidence": edge.get("confidence"),
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
            "source_material_semantic_gap_count": sum(1 for item in gaps if item["reason"] == "source_external_origin_unresolved"),
            "target_local_anchor_gap_count": sum(1 for item in gaps if item["reason"] == "target_local_anchor_unresolved"),
            "gap_count": len(gaps),
        },
    }
    output["content_fingerprint"] = _fingerprint(output)
    return output

