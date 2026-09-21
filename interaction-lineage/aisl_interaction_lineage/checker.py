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
                    binding=binding,
                    repository_id=repository_id,
                    interface_ids=interface_ids,
                    source_ref=source_ref,
                    direction=direction,
                )
                row["boundary_anchor_count"] = int(row.get("boundary_anchor_count") or 0) + 1
                if resolved["anchor_status"] != "resolved":
                    row["boundary_anchor_missing_count"] = int(row.get("boundary_anchor_missing_count") or 0) + 1
                    row["status"] = "boundary_anchor_not_published"
                    diagnostics.append({
                        "code": "boundary_anchor_missing",
                        "repository_id": repository_id,
                        "edge_id": edge_id,
                        "transport_role": field.transport_role,
                        "field_path": field.field_path,
                        "side": side,
                        "requested_anchor": source_ref,
                    })

    items = [repositories[key] for key in sorted(repositories)]
    ready = all(item.get("status") == "ready" for item in items) and bool(items)
    return {
        "format": READINESS_FORMAT,
        "status": "ready" if ready else "not_ready",
        "topology_id": str(topology.get("topology_id") or ""),
        "edge_id": edge_id,
        "repositories": items,
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
