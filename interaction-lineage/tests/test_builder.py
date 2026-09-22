from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from aisl_interaction_lineage.builder import _topology_relative_suffix, build_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
from aisl_interaction_lineage.topology import boundary_fields, select_edge, wire_display_ref


EDGE_ID = "repository_edge_test"


def topology() -> dict[str, Any]:
    return {
        "format": "repository-topology/v4",
        "topology_id": "topology_test",
        "edges": [{
            "edge_id": EDGE_ID,
            "protocol": "http",
            "method": "POST",
            "matched_identity": "/example",
            "match_classification": "probable",
            "claim_classification": "probable_inference",
            "confidence": "medium_high",
            "source_repository_id": "caller",
            "target_repository_id": "service",
            "source_half_wires": [{
                "repository_id": "caller",
                "interface_id": "caller-if",
                "direction": "outbound",
                "request_payload": "RequestDto",
                "response_payload": "ResponseDto",
                "request_field_names": ["id"],
                "response_field_paths": ["profile", "profile.id"],
            }],
            "target_half_wires": [{
                "repository_id": "service",
                "interface_id": "service-if",
                "direction": "inbound",
                "request_payload": "RequestDto",
                "response_payload": "ResponseDto",
                "request_field_names": ["id"],
                "response_field_paths": ["profile", "profile.id"],
            }],
            "attribute_flows": [
                {
                    "transport_role": "request",
                    "source_repository_id": "caller",
                    "target_repository_id": "service",
                    "attribute_names": ["id"],
                },
                {
                    "transport_role": "response",
                    "source_repository_id": "service",
                    "target_repository_id": "caller",
                    "attribute_names": ["profile"],
                },
            ],
        }],
    }


class FakeGateway:
    def __init__(self, *, missing: set[tuple[str, str]] | None = None, ambiguous: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.missing = missing or set()
        self.ambiguous = ambiguous

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"repo": repo, "source": source, "direction": direction})
        if (repo, source) in self.missing:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        if self.ambiguous and source.startswith("HTTP "):
            interface = "service-if" if repo == "service" else "caller-if"
            return {
                "result": {
                    "status": "source_ambiguous",
                    "source_candidates": [
                        {"repo_id": repo, "owner_ref": "other-if", "value_node_id": f"{repo}-other"},
                        {"repo_id": repo, "owner_ref": interface, "value_node_id": f"{repo}-wanted"},
                    ],
                    "paths": [],
                    "gaps": [],
                }
            }
        node = {
            "repo_id": repo,
            "owner_ref": "service-if" if repo == "service" else "caller-if",
            "value_node_id": source,
            "display_ref": source,
        }
        return {
            "schema_version": "knowledge_attribute_path_query/v1",
            "system_id": binding.system_id,
            "revision_id": binding.revision_id,
            "result": {
                "status": "confirmed_complete",
                "source": node,
                "paths": [{"status": "complete", "start": node, "end": node, "steps": []}],
                "gaps": [],
            },
        }

    def list_repository_value_nodes(
        self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
        operation: str | None = None, max_results: int = 500, page_token: str = "",
    ) -> Mapping[str, Any]:
        self.calls.append({"repo": repository_id, "list_nodes": True, "operation": operation})
        return {"result": {"items": [], "total_count": 0, "returned_count": 0, "truncated": False}}


def bindings() -> BindingIndex:
    return BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev"),
        AislBinding("service", "service-system", "service-rev"),
    ])


def test_select_edge_is_exact_and_does_not_merge_operations() -> None:
    payload = topology()
    second = dict(payload["edges"][0])
    second["edge_id"] = "second"
    second["matched_identity"] = "/other"
    payload["edges"].append(second)
    assert select_edge(payload, EDGE_ID)["matched_identity"] == "/example"


def test_response_fields_include_nested_paths_under_published_top_level() -> None:
    fields = boundary_fields(topology()["edges"][0], transport_role="response")
    assert [(item.field_path, item.source_repository_id, item.target_repository_id) for item in fields] == [
        ("profile", "service", "caller"),
        ("profile.id", "service", "caller"),
    ]
    assert fields[1].topology_basis == "topology_payload_shape_under_published_top_level"


def test_builder_uses_reverse_on_source_side_and_forward_on_target_side() -> None:
    gateway = FakeGateway()
    result = build_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway)
    assert result["format"] == "interaction-attribute-lineage/v1"
    assert result["summary"]["journey_count"] == 3
    assert result["summary"]["resolved_crossing_count"] == 3
    response = next(item for item in result["journeys"] if item["field_path"] == "profile.id")
    assert response["source_repository_id"] == "service"
    assert response["source_side"]["direction"] == "reverse"
    assert response["target_side"]["direction"] == "forward"
    assert any(call["repo"] == "service" and call["direction"] == "reverse" for call in gateway.calls)
    assert any(call["repo"] == "caller" and call["direction"] == "forward" for call in gateway.calls)


def test_ambiguous_display_ref_is_resolved_only_by_exact_topology_interface_id() -> None:
    gateway = FakeGateway(ambiguous=True)
    result = build_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway, transport_roles=("request",))
    journey = result["journeys"][0]
    assert journey["source_side"]["anchor_selection_basis"] == "canonical_wire_display_ref:exact_topology_interface_id"
    assert journey["target_side"]["anchor_selection_basis"] == "canonical_wire_display_ref:exact_topology_interface_id"
    assert any(call["source"] == "caller-wanted" for call in gateway.calls)
    assert any(call["source"] == "service-wanted" for call in gateway.calls)


def test_missing_anchor_stays_partial_gap_without_guessing() -> None:
    ref = wire_display_ref("response", "profile.id")
    gateway = FakeGateway(missing={("caller", ref), ("caller", "profile.id")})
    result = build_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway, transport_roles=("response",))
    journey = next(item for item in result["journeys"] if item["field_path"] == "profile.id")
    assert journey["crossing"]["status"] == "resolved"
    assert journey["target_side"]["anchor_status"] == "unresolved"
    assert any(gap["reason"] == "target_local_anchor_unresolved" for gap in result["gaps"])


def test_rejects_active_revision_binding() -> None:
    with pytest.raises(ValueError, match="exact immutable revision"):
        AislBinding.from_payload({"repository_id": "r", "system_id": "s", "revision_id": "latest"})


def test_exact_topology_local_payload_binding_can_anchor_when_wire_ref_is_absent() -> None:
    payload = topology()
    payload["edges"][0]["source_half_wires"][0]["resolution_traces"] = [{
        "local_bindings": [{
            "declared_type": "RequestDto",
            "binding_status": "exact_single_assignment",
            "symbol": "request",
        }]
    }]
    wire = wire_display_ref("request", "id")
    gateway = FakeGateway(missing={("caller", wire)})
    result = build_interaction_lineage(
        payload,
        edge_id=EDGE_ID,
        bindings=bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    journey = result["journeys"][0]
    assert journey["source_side"]["anchor_status"] == "resolved"
    assert journey["source_side"]["anchor_selection_basis"] == (
        "exact_topology_local_payload_binding:unique_exact_display_ref"
    )
    assert any(call.get("source") == "request.id" for call in gateway.calls)


class ReverseProofGateway(FakeGateway):
    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"repo": repo, "source": source, "direction": direction})
        if source in {wire_display_ref("response", "profile.id"), "profile.id"}:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        if source == "id":
            return {"result": {
                "status": "source_ambiguous",
                "source_candidates": [
                    {"repo_id": repo, "owner_ref": "Mapper.other", "operation": "Mapper.other", "value_node_id": "other-id", "display_ref": "id"},
                    {"repo_id": repo, "owner_ref": "Mapper.map", "operation": "Mapper.map", "value_node_id": "wanted-id", "display_ref": "id"},
                ],
                "paths": [],
                "gaps": [],
            }}
        if source == "other-id":
            node = {"repo_id": repo, "operation": "Mapper.other", "value_node_id": source, "display_ref": "id"}
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": []}}
        if source == "wanted-id":
            node = {"repo_id": repo, "operation": "Mapper.map", "value_node_id": source, "display_ref": "id"}
            upstream = {"repo_id": repo, "operation": "Mapper.map", "value_node_id": "profile-id", "display_ref": "request.profile.id"}
            reverse = {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": upstream, "steps": []}], "gaps": []}}
            if direction == "reverse":
                return reverse
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": []}}
        return super().resolve_attribute_paths(binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction)


def test_nested_leaf_ambiguity_resolves_only_with_exact_reverse_path_proof() -> None:
    gateway = ReverseProofGateway()
    result = build_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    journey = next(item for item in result["journeys"] if item["field_path"] == "profile.id")
    assert journey["target_side"]["anchor_status"] == "resolved"
    assert journey["target_side"]["resolved_anchor"]["value_node_id"] == "wanted-id"
    assert journey["target_side"]["anchor_selection_basis"] == "exact_reverse_path_to_topology_field"


class ChildExpansionGateway(FakeGateway):
    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"repo": repo, "source": source, "direction": direction})
        if source == wire_display_ref("response", "profile") and repo == "caller":
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        if source == "profile" and repo == "caller":
            node = {
                "repo_id": repo,
                "owner_ref": "Mapper.map",
                "operation": "Mapper.map",
                "value_node_id": "profile-node",
                "display_ref": "profile",
            }
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": []}}
        if source in {"profile-name", "profile-surname"}:
            node = {"repo_id": repo, "operation": "Mapper.map", "value_node_id": source, "display_ref": "profile." + ("name" if source.endswith("name") else "surname")}
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": []}}
        return super().resolve_attribute_paths(binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction)

    def list_repository_value_nodes(
        self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
        operation: str | None = None, max_results: int = 500, page_token: str = "",
    ) -> Mapping[str, Any]:
        self.calls.append({"repo": repository_id, "list_nodes": True, "operation": operation})
        if repository_id == "caller" and operation == "Mapper.map":
            return {"result": {
                "items": [
                    {"repo_id": repository_id, "operation": operation, "node_kind": "field", "value_node_id": "profile-name", "display_ref": "profile.name"},
                    {"repo_id": repository_id, "operation": operation, "node_kind": "field", "value_node_id": "profile-surname", "display_ref": "profile.surname"},
                    {"repo_id": repository_id, "operation": operation, "node_kind": "field", "value_node_id": "deep", "display_ref": "profile.address.city"},
                ],
                "total_count": 3,
                "returned_count": 3,
                "truncated": False,
            }}
        return {"result": {"items": [], "total_count": 0, "returned_count": 0, "truncated": False}}


def test_observed_child_expansion_lists_only_direct_children_of_exact_anchor_operation() -> None:
    gateway = ChildExpansionGateway()
    result = build_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    journey = next(item for item in result["journeys"] if item["field_path"] == "profile")
    expansion = journey["target_side"]["observed_child_expansion"]
    assert expansion["basis"] == "exact_operation_local_field_prefix"
    assert expansion["operation"] == "Mapper.map"
    assert [item["field"] for item in expansion["children"]] == ["name", "surname"]
    assert all(item["query"]["result"]["status"] == "partial" for item in expansion["children"])


class RelativeCompositeGateway(FakeGateway):
    def __init__(self, *, mismatched_child_operation: bool = False) -> None:
        super().__init__()
        self.mismatched_child_operation = mismatched_child_operation

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"repo": repo, "source": source, "direction": direction})

        # Force the nested topology path to need composition rather than a direct
        # wire/full-path anchor.
        if repo == "caller" and source in {
            wire_display_ref("response", "profile.id"),
            "boundary:rest:/example:response.profile.id",
            "profile.id",
            "id",
        }:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}

        # The exact topology parent maps to a shorter repository-local symbol.
        if repo == "caller" and source == wire_display_ref("response", "profile"):
            parent = {
                "repo_id": repo,
                "owner_ref": "Mapper.map",
                "operation": "Mapper.map",
                "value_node_id": "identity-parent",
                "display_ref": "identity",
            }
            return {
                "result": {
                    "status": "partial",
                    "source": parent,
                    "paths": [{"start": parent, "end": parent, "steps": []}],
                    "gaps": [],
                }
            }

        if repo == "caller" and source == "identity.id":
            operation = "Mapper.other" if self.mismatched_child_operation else "Mapper.map"
            child = {
                "repo_id": repo,
                "owner_ref": operation,
                "operation": operation,
                "value_node_id": "identity-id",
                "display_ref": "identity.id",
            }
            destination = {
                "repo_id": repo,
                "owner_ref": operation,
                "operation": operation,
                "value_node_id": "target-id",
                "display_ref": "target.id",
            }
            return {
                "result": {
                    "status": "partial",
                    "source": child,
                    "paths": [{"start": child, "end": destination, "steps": []}],
                    "gaps": [],
                }
            }

        return super().resolve_attribute_paths(
            binding,
            source=source,
            selected_repo_ids=selected_repo_ids,
            direction=direction,
        )


def test_nested_topology_child_resolves_only_under_exact_local_parent_operation() -> None:
    gateway = RelativeCompositeGateway()
    result = build_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )

    parent = next(item for item in result["journeys"] if item["field_path"] == "profile")
    child = next(item for item in result["journeys"] if item["field_path"] == "profile.id")

    assert parent["target_side"]["resolved_anchor"]["display_ref"] == "identity"
    assert child["target_side"]["anchor_status"] == "resolved"
    assert child["target_side"]["resolved_anchor"]["display_ref"] == "identity.id"
    assert child["target_side"]["resolved_anchor"]["operation"] == "Mapper.map"
    assert child["target_side"]["anchor_selection_basis"] == (
        "exact_topology_relative_child_under_resolved_parent_operation"
    )
    assert any(call.get("source") == "identity.id" for call in gateway.calls)


def test_nested_topology_child_does_not_cross_operation_boundary() -> None:
    gateway = RelativeCompositeGateway(mismatched_child_operation=True)
    result = build_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    child = next(item for item in result["journeys"] if item["field_path"] == "profile.id")

    assert child["target_side"]["anchor_status"] == "unresolved"
    assert any(
        gap["reason"] == "target_local_anchor_unresolved"
        and gap["field_path"] == "profile.id"
        for gap in result["gaps"]
    )


def test_topology_relative_suffix_preserves_array_item_semantics() -> None:
    assert _topology_relative_suffix("items", "items[].code") == "[].code"
    assert _topology_relative_suffix("items", "itemsExtra.code") is None
