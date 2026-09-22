from __future__ import annotations

from typing import Any, Mapping, Sequence

from aisl_interaction_lineage.builder import build_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
from aisl_interaction_lineage.topology import route_boundary_ref, wire_display_ref


EDGE_ID = "repository_edge_route_identity_test"


def _topology() -> dict[str, Any]:
    return {
        "format": "repository-topology/v4",
        "topology_id": "topology_route_identity_test",
        "edges": [{
            "edge_id": EDGE_ID,
            "protocol": "http",
            "method": "POST",
            "matched_identity": "/v1/task/startProcesses",
            "match_classification": "exact",
            "claim_classification": "observed",
            "confidence": "high",
            "source_repository_id": "ui",
            "target_repository_id": "bulk",
            "source_half_wires": [{
                "repository_id": "ui",
                "interface_id": "topology-ui",
                "direction": "outbound",
                "request_payload": "RequestDto",
                "request_field_names": ["processes"],
            }],
            "target_half_wires": [{
                "repository_id": "bulk",
                "interface_id": "topology-bulk",
                "direction": "inbound",
                "request_payload": "RequestDto",
                "request_field_names": ["processes"],
            }],
            "attribute_flows": [{
                "transport_role": "request",
                "source_repository_id": "ui",
                "target_repository_id": "bulk",
                "attribute_names": ["processes"],
            }],
        }],
    }


def _bindings() -> BindingIndex:
    return BindingIndex([
        AislBinding("ui", "ui-system", "ui-rev"),
        AislBinding("bulk", "bulk-system", "bulk-rev"),
    ])


class _BaseGateway:
    def list_repository_value_nodes(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        return {"result": {"items": [], "total_count": 0, "returned_count": 0}}


class _RouteGateway(_BaseGateway):
    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        wire = wire_display_ref("request", "processes")
        route = "boundary:rest:/v1/task/startProcesses:request.processes"
        if source == wire:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        if source == route:
            node = {
                "repo_id": repo,
                "value_node_id": f"{repo}-route",
                "display_ref": route,
                "operation": "op",
            }
            return {"result": {
                "status": "partial",
                "source": node,
                "paths": [{"status": "partial", "start": node, "end": node, "steps": []}],
                "gaps": [],
            }}
        return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}


class _TransportGateway(_BaseGateway):
    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        wire = wire_display_ref("request", "processes")
        route = "boundary:rest:/v1/task/startProcesses:request.processes"
        if source == wire:
            interface_direction = "outbound" if repo == "ui" else "inbound"
            candidates = []
            for suffix, endpoint in (
                ("start-processes", "/v1/task/startProcesses"),
                ("start-task", "/v1/task/startTask"),
            ):
                candidates.append({
                    "repo_id": repo,
                    "value_node_id": f"{repo}-{suffix}",
                    "owner_ref": f"framework-{suffix}",
                    "display_ref": wire,
                    "transport": {
                        "protocol": "http",
                        "interface_direction": interface_direction,
                        "payload_role": "request",
                        "http_method": "POST",
                        "endpoint": endpoint,
                    },
                })
            return {"result": {
                "status": "source_ambiguous",
                "source_candidates": candidates,
                "paths": [],
                "gaps": [],
            }}
        if source.endswith("-start-processes"):
            node = {"repo_id": repo, "value_node_id": source, "display_ref": wire}
            return {"result": {
                "status": "partial",
                "source": node,
                "paths": [{"status": "partial", "start": node, "end": node, "steps": []}],
                "gaps": [],
            }}
        if source == route:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}


def test_exact_topology_route_boundary_is_used_when_canonical_wire_ref_is_absent() -> None:
    topology = _topology()
    result = build_interaction_lineage(
        topology,
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=_RouteGateway(),
        transport_roles=("request",),
    )
    journey = result["journeys"][0]
    assert route_boundary_ref(topology["edges"][0], "request", "processes") == (
        "boundary:rest:/v1/task/startProcesses:request.processes"
    )
    assert journey["source_side"]["anchor_selection_basis"].startswith("exact_topology_route_boundary:")
    assert journey["target_side"]["anchor_selection_basis"].startswith("exact_topology_route_boundary:")


def test_ambiguous_wire_ref_is_resolved_only_by_exact_topology_transport_identity() -> None:
    result = build_interaction_lineage(
        _topology(),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=_TransportGateway(),
        transport_roles=("request",),
    )
    journey = result["journeys"][0]
    for side in ("source_side", "target_side"):
        assert journey[side]["anchor_status"] == "resolved"
        assert journey[side]["anchor_selection_basis"] == (
            "canonical_wire_display_ref:exact_topology_transport_identity"
        )
        assert journey[side]["resolved_anchor"]["value_node_id"].endswith("-start-processes")
