from __future__ import annotations

from typing import Any, Mapping, Sequence

from .aisl import AislReadinessGateway
from .builder import _resolve_side
from .contracts import BindingIndex
from .topology import boundary_fields, select_edge, wire_display_ref

READINESS_FORMAT = "interaction-lineage-readiness/v1"
_REQUIRED_CAPABILITY = "workspace.attribute-path-resolver"


def _repo_ids(edge: Mapping[str, Any], roles: Sequence[str]) -> list[str]:
    values: set[str] = set()
    for role in roles:
        for field in boundary_fields(edge, transport_role=role):
            values.add(field.source_repository_id)
            values.add(field.target_repository_id)
    return sorted(values)



def _result(response: Mapping[str, Any]) -> Mapping[str, Any]:
    value = response.get("result")
    return value if isinstance(value, Mapping) else response


def _external_client_boundary_requirement(
    *,
    resolved: Mapping[str, Any],
    repository_id: str,
    system_id: str,
    revision_id: str,
    edge_id: str,
    transport_role: str,
    field_path: str,
    side: str,
    direction: str,
) -> dict[str, Any] | None:
    """Return a preparation hint only from producer-owned client boundary facts."""
    query = resolved.get("query")
    if not isinstance(query, Mapping):
        return None
    result = _result(query)
    terminal_reason = (
        "no_observed_incoming_value_flow"
        if direction == "reverse"
        else "no_observed_outgoing_value_flow"
    )
    candidates: list[tuple[Mapping[str, Any], Mapping[str, Any], list[str]]] = []
    for gap in result.get("gaps") or ():
        if not isinstance(gap, Mapping) or str(gap.get("reason") or "") != terminal_reason:
            continue
        node = gap.get("node")
        if not isinstance(node, Mapping):
            continue
        boundary = node.get("boundary")
        if not isinstance(boundary, Mapping):
            continue
        payload_role = str(boundary.get("payload_role") or "").strip()
        expected_direction = {"request": "outbound", "response": "inbound"}.get(payload_role)
        if expected_direction is None or str(boundary.get("boundary_direction") or "") != expected_direction:
            continue
        interaction_direction = str(boundary.get("interaction_direction") or "").strip()
        if interaction_direction and interaction_direction != "outbound":
            continue
        anchors: list[str] = []
        for value in (boundary.get("payload_type"), node.get("type_ref")):
            text = str(value or "").strip()
            if text and text not in anchors:
                anchors.append(text)
        if not anchors:
            continue
        candidates.append((node, boundary, anchors))
    if not candidates:
        return None

    signatures = {
        (
            str(node.get("value_node_id") or ""),
            tuple(anchors),
            str(boundary.get("boundary_path") or ""),
        )
        for node, boundary, anchors in candidates
    }
    if len(signatures) != 1:
        return {
            "state": "ambiguous",
            "repository_id": repository_id,
            "system_id": system_id,
            "revision_id": revision_id,
            "edge_id": edge_id,
            "transport_role": transport_role,
            "field_path": field_path,
            "side": side,
            "direction": direction,
            "diagnostic": "multiple_external_terminal_boundaries",
        }

    node, boundary, anchors = candidates[0]
    source_node = result.get("source")
    source_id = (
        str(source_node.get("value_node_id") or "")
        if isinstance(source_node, Mapping)
        else ""
    )
    if not source_id:
        anchor = resolved.get("resolved_anchor")
        if isinstance(anchor, Mapping):
            source_id = str(anchor.get("value_node_id") or "")
    if not source_id:
        return None

    observed_boundary = {
        "repository_id": repository_id,
        "system_id": system_id,
        "boundary_kind": boundary.get("boundary_kind"),
        "boundary_direction": boundary.get("boundary_direction"),
        "interaction_direction": boundary.get("interaction_direction"),
        "payload_role": boundary.get("payload_role"),
        "boundary_path": boundary.get("boundary_path"),
        "field_binding_kind": boundary.get("field_binding_kind"),
        "observed_anchors": anchors,
        "terminal_value_node_id": str(node.get("value_node_id") or ""),
        "terminal_repo_id": str(node.get("repo_id") or repository_id),
    }
    return {
        "state": "needs_external_source",
        "repository_id": repository_id,
        "system_id": system_id,
        "revision_id": revision_id,
        "edge_id": edge_id,
        "transport_role": transport_role,
        "field_path": field_path,
        "side": side,
        "direction": direction,
        "observed_boundary": observed_boundary,
        "selector_context": {
            "repository_id": repository_id,
            "system_id": system_id,
            "attribute_path": {
                "repository_id": repository_id,
                "system_id": system_id,
                "revision_id": revision_id,
                "source": source_id,
                "selected_repo_ids": [repository_id],
                "direction": direction,
            },
        },
        "preparation_group": {
            "repository_id": repository_id,
            "system_id": system_id,
            "boundary_path": boundary.get("boundary_path"),
            "payload_type": boundary.get("payload_type"),
            "observed_anchors": anchors,
        },
    }


def check_interaction_lineage(
    topology: Mapping[str, Any],
    *,
    edge_id: str,
    bindings: BindingIndex,
    gateway: AislReadinessGateway,
    transport_roles: Sequence[str] = ("request", "response"),
) -> dict[str, Any]:
    edge = select_edge(topology, edge_id)
    repositories: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    preparation_requirements: list[dict[str, Any]] = []

    for repository_id in _repo_ids(edge, transport_roles):
        binding = bindings.find(repository_id)
        if binding is None:
            repositories[repository_id] = {
                "repository_id": repository_id,
                "status": "missing_binding",
            }
            diagnostics.append({
                "code": "repository_resolution_failed",
                "repository_id": repository_id,
                "reason": "missing_exact_aisl_binding",
            })
            continue

        revision = dict(gateway.revision_status(binding))
        revision_status = str(revision.get("status") or "")
        if revision_status != "ready":
            status = {
                "server_unavailable": "server_unavailable",
                "missing_revision": "missing_compatible_revision",
            }.get(revision_status, "revision_unavailable")
            repositories[repository_id] = {
                "repository_id": repository_id,
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
                "status": status,
                "diagnostic": revision.get("diagnostic"),
            }
            diagnostics.append({
                "code": "server_unavailable" if revision_status == "server_unavailable" else "compatible_revision_not_found",
                "repository_id": repository_id,
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
                "reason": revision_status or "revision_unavailable",
            })
            continue

        capabilities = sorted({str(value) for value in revision.get("capabilities") or () if str(value)})
        if _REQUIRED_CAPABILITY not in capabilities:
            repositories[repository_id] = {
                "repository_id": repository_id,
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
                "status": "missing_required_capability",
                "missing_capabilities": [_REQUIRED_CAPABILITY],
                "capabilities": capabilities,
            }
            diagnostics.append({
                "code": "required_capability_missing",
                "repository_id": repository_id,
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
                "capability": _REQUIRED_CAPABILITY,
            })
            continue

        repositories[repository_id] = {
            "repository_id": repository_id,
            "system_id": binding.system_id,
            "revision_id": binding.revision_id,
            "status": "ready",
            "capabilities": capabilities,
            "boundary_anchor_count": 0,
            "boundary_anchor_missing_count": 0,
        }

    for role in transport_roles:
        for field in boundary_fields(edge, transport_role=role):
            source_ref = wire_display_ref(field.transport_role, field.field_path)
            for repository_id, interface_ids, direction, side in (
                (field.source_repository_id, field.source_interface_ids, "reverse", "source"),
                (field.target_repository_id, field.target_interface_ids, "forward", "target"),
            ):
                row = repositories.get(repository_id)
                if not row or row.get("status") != "ready":
                    continue
                binding = bindings.require(repository_id)
                resolved = _resolve_side(
                    gateway,
                    edge=edge,
                    field=field,
                    side=side,
                    binding=binding,
                    repository_id=repository_id,
                    interface_ids=interface_ids,
                    payload_identity=(
                        field.source_payload_identity if side == "source" else field.target_payload_identity
                    ),
                    source_ref=source_ref,
                    direction=direction,
                )
                row["boundary_anchor_count"] = int(row.get("boundary_anchor_count") or 0) + 1
                if resolved["anchor_status"] != "resolved":
                    row["boundary_anchor_missing_count"] = int(row.get("boundary_anchor_missing_count") or 0) + 1
                    diagnostics.append({
                        "code": "local_anchor_gap",
                        "repository_id": repository_id,
                        "edge_id": edge_id,
                        "transport_role": field.transport_role,
                        "field_path": field.field_path,
                        "side": side,
                        "requested_anchor": source_ref,
                        "blocking": False,
                    })
                else:
                    requirement = _external_client_boundary_requirement(
                        resolved=resolved,
                        repository_id=repository_id,
                        system_id=binding.system_id,
                        revision_id=binding.revision_id,
                        edge_id=edge_id,
                        transport_role=field.transport_role,
                        field_path=field.field_path,
                        side=side,
                        direction=direction,
                    )
                    if requirement is not None:
                        preparation_requirements.append(requirement)
                        if requirement.get("state") == "ambiguous":
                            row["status"] = "preparation_ambiguous"
                            diagnostics.append({
                                "code": "preparation_boundary_ambiguous",
                                "repository_id": repository_id,
                                "edge_id": edge_id,
                                "transport_role": field.transport_role,
                                "field_path": field.field_path,
                                "side": side,
                            })
                        elif row.get("status") == "ready":
                            row["status"] = "preparable_external_boundary"

    items = [repositories[key] for key in sorted(repositories)]
    ready = all(item.get("status") == "ready" for item in items) and bool(items)
    return {
        "format": READINESS_FORMAT,
        "status": "ready" if ready else "not_ready",
        "topology_id": str(topology.get("topology_id") or ""),
        "edge_id": edge_id,
        "repositories": items,
        "preparation_requirements": sorted(
            preparation_requirements,
            key=lambda item: (
                str(item.get("repository_id") or ""),
                str(item.get("transport_role") or ""),
                str(item.get("field_path") or ""),
                str(item.get("side") or ""),
            ),
        ),
        "diagnostics": sorted(
            diagnostics,
            key=lambda item: (
                str(item.get("repository_id") or ""),
                str(item.get("code") or ""),
                str(item.get("transport_role") or ""),
                str(item.get("field_path") or ""),
                str(item.get("side") or ""),
            ),
        ),
        "summary": {
            "repository_count": len(items),
            "ready_repository_count": sum(1 for item in items if item.get("status") == "ready"),
            "not_ready_repository_count": sum(1 for item in items if item.get("status") != "ready"),
        },
    }
