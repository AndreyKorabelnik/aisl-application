from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from aisl_interaction_lineage.builder import _target_semantic_projection, build_interaction_lineage
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
    assert any(call.get("repo") == "service" and call.get("direction") == "reverse" for call in gateway.calls)
    assert any(call.get("repo") == "caller" and call.get("direction") == "forward" for call in gateway.calls)


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


def test_exact_topology_suffix_refs_keep_structural_context_and_exclude_leaf() -> None:
    from aisl_interaction_lineage.builder import _exact_topology_suffix_refs

    assert _exact_topology_suffix_refs("clientInfo.identifications.documentType.code") == (
        "identifications.documentType.code",
        "documentType.code",
    )
    assert _exact_topology_suffix_refs("clientInfo.identifications.documentSeries") == (
        "identifications.documentSeries",
    )

class StructuralBoundaryCatalogGateway(FakeGateway):
    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"repo": repo, "source": source, "direction": direction, "selected_repo_ids": list(selected_repo_ids)})
        if repo == "caller" and source == wire_display_ref("response", "profile"):
            anchor = {"repo_id": repo, "owner_ref": "caller-if", "value_node_id": "wire-profile", "display_ref": source}
            end = {"repo_id": repo, "owner_ref": "Mapper.map", "value_node_id": "local-profile", "display_ref": "model.profile"}
            return {"result": {"status": "confirmed_complete", "source": anchor, "paths": [{"start": anchor, "end": end, "steps": [{"edge_kind": "field_flow"}]}], "gaps": []}}
        return super().resolve_attribute_paths(binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction)

    def list_repository_value_nodes(
        self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
        operation: str | None = None, max_results: int = 500, page_token: str = "",
    ) -> Mapping[str, Any]:
        self.calls.append({"repo": repository_id, "list_nodes": True, "operation": operation})
        if repository_id == "service" and operation is None:
            def field(path: str) -> dict[str, Any]:
                return {
                    "repo_id": "service",
                    "node_kind": "field",
                    "value_node_id": "field-" + path.replace(".", "-"),
                    "display_ref": "boundary:rest:/example:response." + path,
                    "type_ref": "String",
                    "payload_json": {"source_occurrence": {
                        "boundary_kind": "rest",
                        "boundary_path": "/example",
                        "payload_role": "response",
                        "payload_type": "ResponseDto",
                        "interaction_direction": "outbound",
                        "wire_field_path": path,
                    }},
                }
            items = [field("profile"), field("profile.id"), field("profile.name")]
            return {"result": {"items": items, "total_count": len(items), "returned_count": len(items), "truncated": False}}
        return super().list_repository_value_nodes(binding, repository_id=repository_id, node_kind=node_kind, operation=operation, max_results=max_results, page_token=page_token)


def test_http_topology_can_expand_exact_rest_boundary_shape_under_observed_branch() -> None:
    gateway = StructuralBoundaryCatalogGateway()
    result = build_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway, transport_roles=("response",),
    )
    assert [item["field_path"] for item in result["journeys"]] == ["profile", "profile.id", "profile.name"]
    expanded = next(item for item in result["journeys"] if item["field_path"] == "profile.name")
    assert expanded["topology_basis"] == "published_source_boundary_shape_under_observed_topology_branch"


class StructuralTerminalGateway(StructuralBoundaryCatalogGateway):
    def resolve_attribute_paths(
        self, binding: AislBinding, *, source: str, selected_repo_ids: Sequence[str], direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        if source.endswith("profile.name") or source == "profile.name":
            self.calls.append({"repo": repo, "source": source, "direction": direction, "selected_repo_ids": list(selected_repo_ids)})
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        return super().resolve_attribute_paths(
            binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction
        )


def test_structural_expansion_without_field_specific_flow_is_terminal_not_gap() -> None:
    result = build_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=StructuralTerminalGateway(),
        transport_roles=("response",),
    )
    expanded = next(item for item in result["journeys"] if item["field_path"] == "profile.name")
    assert expanded["source_side"]["anchor_status"] == "terminal"
    assert expanded["target_side"]["anchor_status"] == "terminal"
    assert result["summary"]["gap_count"] == 0


class SelectedRepoIdsGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.selected: list[tuple[str, ...]] = []

    def resolve_attribute_paths(
        self, binding: AislBinding, *, source: str, selected_repo_ids: Sequence[str], direction: str,
    ) -> Mapping[str, Any]:
        self.selected.append(tuple(selected_repo_ids))
        return super().resolve_attribute_paths(binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction)


def test_builder_queries_framework_composite_selected_repo_ids() -> None:
    gateway = SelectedRepoIdsGateway()
    composite = BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev", ("caller", "maven:g:a:1.2.3")),
        AislBinding("service", "service-system", "service-rev", ("service", "maven:g:b:4.5.6")),
    ])
    build_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=composite, gateway=gateway, transport_roles=("request",))
    assert ("caller", "maven:g:a:1.2.3") in gateway.selected
    assert ("service", "maven:g:b:4.5.6") in gateway.selected


def test_builder_preserves_external_semantic_segment_without_inventing_cross_repo_edge(monkeypatch) -> None:
    import aisl_interaction_lineage.builder as builder_mod
    from aisl_interaction_lineage.human_csv import human_rows

    def fake_resolve_side(
        gateway, *, edge, field, side, binding, repository_id, interface_ids,
        payload_identity, source_ref, direction, node_catalog_cache,
    ):
        if repository_id == "service" and side == "source" and field.field_path == "profile.id":
            return {
                "repository_id": repository_id,
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
                "direction": direction,
                "requested_anchor": source_ref,
                "attempted_anchors": [source_ref],
                "resolved_anchor": {"value_node_id": "wire-profile-id", "display_ref": source_ref},
                "anchor_status": "resolved",
                "anchor_selection_basis": "test",
                "query": {"result": {
                    "status": "partial",
                    "source": {"value_node_id": "wire-profile-id", "display_ref": source_ref},
                    "paths": [{
                        "status": "partial",
                        "start": {"value_node_id": "wire-profile-id", "display_ref": source_ref},
                        "end": {"value_node_id": "terminal-child", "display_ref": "converter.convert().id"},
                        "steps": [],
                    }],
                    "gaps": [],
                }},
            }
        node = {"value_node_id": f"{repository_id}:{source_ref}", "display_ref": source_ref, "repo_id": repository_id}
        return {
            "repository_id": repository_id,
            "system_id": binding.system_id,
            "revision_id": binding.revision_id,
            "direction": direction,
            "requested_anchor": source_ref,
            "attempted_anchors": [source_ref],
            "resolved_anchor": node,
            "anchor_status": "resolved",
            "anchor_selection_basis": "test",
            "query": {"result": {"status": "confirmed_complete", "source": node, "paths": [], "gaps": []}},
        }

    class ExternalSegmentGateway(FakeGateway):
        def list_repository_value_nodes(
            self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
            operation: str | None = None, max_results: int = 500, page_token: str = "",
        ) -> Mapping[str, Any]:
            if repository_id == "service":
                items = [
                    {"value_node_id": "terminal-child", "display_ref": "converter.convert().id", "payload_json": {"source_occurrence": {
                        "occurrence_id": "child-occ", "occurrence_kind": "projected_object_field",
                        "object_occurrence_id": "parent-occ",
                    }}},
                    {"value_node_id": "parent-node", "display_ref": "converter.convert()", "payload_json": {"source_occurrence": {
                        "occurrence_id": "parent-occ", "occurrence_kind": "method_invocation",
                        "resolution_status": "external_or_unresolved", "declared_type": "ExternalProfile", "method_name": "convert",
                    }}},
                ]
            elif repository_id == "maven:g:a:1.2.3" and node_kind == "field" and operation is None:
                items = [{"value_node_id": "external-target-id", "node_kind": "field", "operation": "Mapper.map",
                          "display_ref": "mapped.id", "source_path": "Mapper.java", "payload_json": {"source_occurrence": {
                              "occurrence_id": "mapped-id-occ", "occurrence_kind": "local_field", "property_name": "id", "operation": "Mapper.map",
                          }}}]
            elif repository_id == "maven:g:a:1.2.3" and operation == "Mapper.map":
                items = [{"value_node_id": "external-owner", "node_kind": "local_value", "operation": "Mapper.map",
                          "display_ref": "mapped", "type_ref": "ExternalProfile", "payload_json": {"source_occurrence": {
                              "occurrence_id": "mapped-occ", "occurrence_kind": "local_variable", "symbol": "mapped",
                              "declared_type": "ExternalProfile", "operation": "Mapper.map",
                          }}}]
            else:
                items = []
            return {"result": {"items": items, "total_count": len(items), "returned_count": len(items), "truncated": False}}

        def resolve_attribute_paths(
            self, binding: AislBinding, *, source: str, selected_repo_ids: Sequence[str], direction: str,
        ) -> Mapping[str, Any]:
            if source == "external-target-id" and tuple(selected_repo_ids) == ("maven:g:a:1.2.3",):
                target = {"value_node_id": source, "repo_id": "maven:g:a:1.2.3", "display_ref": "mapped.id", "node_kind": "field", "source_path": "Mapper.java"}
                origin = {"value_node_id": "external-origin-id", "repo_id": "maven:g:a:1.2.3", "display_ref": "source.id", "node_kind": "field", "source_path": "Mapper.java"}
                derivation = {"value_node_id": "derive-id", "repo_id": "maven:g:a:1.2.3", "display_ref": "Mapper.mapId()", "node_kind": "derivation", "source_path": "Mapper.java"}
                return {"result": {"status": "partial", "source": target, "paths": [{
                    "status": "partial", "hop_count": 2, "confidence": "confirmed", "start": target, "end": origin,
                    "steps": [
                        {"value_flow_edge_id": "edge-2", "source": derivation, "target": target},
                        {"value_flow_edge_id": "edge-1", "source": origin, "target": derivation},
                    ],
                }], "gaps": []}}
            return super().resolve_attribute_paths(binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction)

    composite = BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev"),
        AislBinding("service", "service-system", "service-rev-2", ("service", "maven:g:a:1.2.3")),
    ])
    monkeypatch.setattr(builder_mod, "_resolve_side", fake_resolve_side)
    result = build_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=composite, gateway=ExternalSegmentGateway(),
        transport_roles=("response",),
    )
    journey = next(item for item in result["journeys"] if item["field_path"] == "profile.id")
    evidence = journey["source_side"]["external_origin_evidence"]
    assert evidence["status"] == "semantically_covered"
    assert evidence["bridge_status"] == "cross_repository_link_not_observed"
    assert evidence["segments"][0]["origins"][0]["display_ref"] == "source.id"
    assert result["summary"]["source_material_semantic_gap_count"] == 0
    assert result["summary"]["source_external_origin_link_gap_count"] == 1
    assert not any(item["reason"] == "source_external_origin_unresolved" for item in result["gaps"])
    row = next(item for item in human_rows(result) if item["crossing_attribute"] == "profile.id")
    assert row["producer_attribute"] == "source.id"
    assert "maven:g:a:1.2.3: source.id --[Mapper.mapId()]→ mapped.id" in row["full_attribute_path"]
    assert "cross-repository link not observed" in row["full_attribute_path"]
    assert "source_external_origin_link_unproven" in row["full_attribute_path"]


def test_external_origin_evidence_accepts_nested_owner_only_with_shared_observed_origin() -> None:
    from aisl_interaction_lineage.builder import _external_origin_evidence

    class NestedExternalGateway(FakeGateway):
        def __init__(self, *, nested_origin_id: str = "external-origin-items") -> None:
            super().__init__()
            self.nested_origin_id = nested_origin_id

        def list_repository_value_nodes(
            self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
            operation: str | None = None, max_results: int = 500, page_token: str = "",
        ) -> Mapping[str, Any]:
            if repository_id != "maven:g:a:1.2.3":
                return {"result": {"items": [], "total_count": 0, "returned_count": 0, "truncated": False}}
            if node_kind == "field" and operation is None:
                items = [
                    {
                        "value_node_id": "external-target-items",
                        "node_kind": "field",
                        "operation": "Mapper.map",
                        "display_ref": "mapped.items",
                        "source_path": "Mapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_id": "mapped-items-occ",
                            "occurrence_kind": "local_field",
                            "property_name": "items",
                            "operation": "Mapper.map",
                        }},
                    },
                    {
                        "value_node_id": "external-target-nested-id",
                        "node_kind": "field",
                        "operation": "Mapper.mapItems",
                        "display_ref": "nested.id",
                        "source_path": "Mapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_id": "nested-id-occ",
                            "occurrence_kind": "local_field",
                            "property_name": "id",
                            "operation": "Mapper.mapItems",
                        }},
                    },
                ]
            elif operation == "Mapper.map":
                items = [{
                    "value_node_id": "external-owner",
                    "node_kind": "local_value",
                    "operation": "Mapper.map",
                    "display_ref": "mapped",
                    "type_ref": "ExternalProfile",
                    "payload_json": {"source_occurrence": {
                        "occurrence_id": "mapped-occ",
                        "occurrence_kind": "local_variable",
                        "symbol": "mapped",
                        "declared_type": "ExternalProfile",
                        "operation": "Mapper.map",
                    }},
                }]
            elif operation == "Mapper.mapItems":
                items = [{
                    "value_node_id": "nested-owner",
                    "node_kind": "local_value",
                    "operation": "Mapper.mapItems",
                    "display_ref": "nested",
                    "type_ref": "NestedItems",
                    "payload_json": {"source_occurrence": {
                        "occurrence_id": "nested-occ",
                        "occurrence_kind": "local_variable",
                        "symbol": "nested",
                        "declared_type": "NestedItems",
                        "operation": "Mapper.mapItems",
                    }},
                }]
            else:
                items = []
            return {"result": {
                "items": items,
                "total_count": len(items),
                "returned_count": len(items),
                "truncated": False,
            }}

        def resolve_attribute_paths(
            self, binding: AislBinding, *, source: str,
            selected_repo_ids: Sequence[str], direction: str,
        ) -> Mapping[str, Any]:
            if source not in {"external-target-items", "external-target-nested-id"}:
                return super().resolve_attribute_paths(
                    binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction,
                )
            origin_id = (
                "external-origin-items"
                if source == "external-target-items"
                else self.nested_origin_id
            )
            target_ref = "mapped.items" if source == "external-target-items" else "nested.id"
            target = {
                "value_node_id": source,
                "repo_id": "maven:g:a:1.2.3",
                "display_ref": target_ref,
                "node_kind": "field",
                "source_path": "Mapper.java",
            }
            origin = {
                "value_node_id": origin_id,
                "repo_id": "maven:g:a:1.2.3",
                "display_ref": "source.items",
                "node_kind": "field",
                "source_path": "Mapper.java",
            }
            return {"result": {
                "status": "partial",
                "source": target,
                "paths": [{
                    "status": "partial",
                    "hop_count": 1,
                    "confidence": "confirmed",
                    "start": target,
                    "end": origin,
                    "steps": [{"value_flow_edge_id": f"edge-{source}", "source": origin, "target": target}],
                }],
                "gaps": [],
            }}

    material_gap = {
        "reason": "source_external_origin_unresolved",
        "evidence": [
            {
                "terminal_value_node_id": "terminal-items",
                "terminal_display_ref": "converter.convert().items",
                "terminal_property_name": "items",
                "parent_display_ref": "converter.convert()",
                "parent_declared_type": "ExternalProfile",
            },
            {
                "terminal_value_node_id": "terminal-nested-id",
                "terminal_display_ref": "converter.convert().items.id",
                "terminal_property_name": "id",
                "parent_display_ref": "converter.convert()",
                "parent_declared_type": "ExternalProfile",
            },
        ],
    }
    binding = AislBinding(
        "service", "service-system", "service-rev",
        ("service", "maven:g:a:1.2.3"),
    )

    evidence = _external_origin_evidence(
        NestedExternalGateway(), binding=binding, repository_id="service",
        material_gap=material_gap, cache={},
    )
    assert evidence is not None
    nested = next(item for item in evidence["segments"] if item["property_name"] == "id")
    assert nested["root_declared_type"] == "ExternalProfile"
    assert nested["target_declared_type"] == "NestedItems"
    assert nested["relative_property_path"] == ["items", "id"]
    assert nested["basis"] == (
        "selected_external_repo_nested_property_shares_observed_origin_with_exact_typed_ancestor"
    )


def test_external_origin_evidence_rejects_nested_owner_when_origin_differs_from_ancestor() -> None:
    from aisl_interaction_lineage.builder import _external_origin_evidence

    # Reuse the positive fixture implementation from the neighboring test by
    # expressing the same public contract with a deliberately different nested
    # origin.  The direct ancestor remains proven, but the nested field must not
    # be composed merely because its property name exists in the external repo.
    class DivergentNestedGateway(FakeGateway):
        def list_repository_value_nodes(
            self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
            operation: str | None = None, max_results: int = 500, page_token: str = "",
        ) -> Mapping[str, Any]:
            if repository_id != "maven:g:a:1.2.3":
                items = []
            elif node_kind == "field" and operation is None:
                items = [
                    {
                        "value_node_id": "target-items", "node_kind": "field",
                        "operation": "Mapper.map", "display_ref": "mapped.items",
                        "payload_json": {"source_occurrence": {
                            "property_name": "items", "occurrence_kind": "local_field",
                        }},
                    },
                    {
                        "value_node_id": "target-nested-id", "node_kind": "field",
                        "operation": "Mapper.mapItems", "display_ref": "nested.id",
                        "payload_json": {"source_occurrence": {
                            "property_name": "id", "occurrence_kind": "local_field",
                        }},
                    },
                ]
            elif operation == "Mapper.map":
                items = [{
                    "value_node_id": "owner-root", "node_kind": "local_value",
                    "operation": operation, "display_ref": "mapped", "type_ref": "ExternalProfile",
                    "payload_json": {"source_occurrence": {
                        "symbol": "mapped", "declared_type": "ExternalProfile",
                        "occurrence_kind": "local_variable",
                    }},
                }]
            elif operation == "Mapper.mapItems":
                items = [{
                    "value_node_id": "owner-nested", "node_kind": "local_value",
                    "operation": operation, "display_ref": "nested", "type_ref": "NestedItems",
                    "payload_json": {"source_occurrence": {
                        "symbol": "nested", "declared_type": "NestedItems",
                        "occurrence_kind": "local_variable",
                    }},
                }]
            else:
                items = []
            return {"result": {
                "items": items, "total_count": len(items),
                "returned_count": len(items), "truncated": False,
            }}

        def resolve_attribute_paths(
            self, binding: AislBinding, *, source: str,
            selected_repo_ids: Sequence[str], direction: str,
        ) -> Mapping[str, Any]:
            origin_id = "origin-items" if source == "target-items" else "different-origin"
            target = {"value_node_id": source, "display_ref": source, "node_kind": "field"}
            origin = {"value_node_id": origin_id, "display_ref": origin_id, "node_kind": "field"}
            return {"result": {
                "status": "partial", "source": target,
                "paths": [{
                    "status": "partial", "hop_count": 1, "confidence": "confirmed",
                    "start": target, "end": origin,
                    "steps": [{"value_flow_edge_id": f"edge-{source}", "source": origin, "target": target}],
                }],
                "gaps": [],
            }}

    material_gap = {"evidence": [
        {
            "terminal_value_node_id": "terminal-items",
            "terminal_display_ref": "converter.convert().items",
            "terminal_property_name": "items",
            "parent_display_ref": "converter.convert()",
            "parent_declared_type": "ExternalProfile",
        },
        {
            "terminal_value_node_id": "terminal-nested-id",
            "terminal_display_ref": "converter.convert().items.id",
            "terminal_property_name": "id",
            "parent_display_ref": "converter.convert()",
            "parent_declared_type": "ExternalProfile",
        },
    ]}
    binding = AislBinding(
        "service", "service-system", "service-rev",
        ("service", "maven:g:a:1.2.3"),
    )
    assert _external_origin_evidence(
        DivergentNestedGateway(), binding=binding, repository_id="service",
        material_gap=material_gap, cache={},
    ) is None


def test_material_source_origin_gap_does_not_promote_untyped_external_or_unresolved_parent() -> None:
    from aisl_interaction_lineage.builder import _material_source_origin_gap

    side = {
        "anchor_status": "resolved",
        "query": {"result": {
            "status": "partial",
            "paths": [{
                "status": "partial",
                "end": {
                    "value_node_id": "terminal-status",
                    "display_ref": "future.handle().status",
                },
                "steps": [{
                    "flow_kind": "field_mapping",
                    "source_edge_kind": "method_return_field_projection",
                    "source": {"value_node_id": "terminal-status", "display_ref": "future.handle().status"},
                    "target": {"value_node_id": "return-status", "display_ref": "Service.execute.return.status"},
                }],
            }],
            "gaps": [{"reason": "no_observed_incoming_value_flow"}],
        }},
    }
    catalog = [
        {
            "value_node_id": "terminal-status",
            "display_ref": "future.handle().status",
            "payload_json": {"source_occurrence": {
                "occurrence_id": "terminal-occ",
                "occurrence_kind": "projected_object_field",
                "object_occurrence_id": "parent-occ",
                "field_path": "future.handle().status",
            }},
        },
        {
            "value_node_id": "parent-call",
            "display_ref": "future.handle()",
            "payload_json": {"source_occurrence": {
                "occurrence_id": "parent-occ",
                "occurrence_kind": "method_invocation",
                "resolution_status": "external_or_unresolved",
                "declared_type": "",
                "method_name": "handle",
            }},
        },
    ]

    assert _material_source_origin_gap(
        side, catalog=catalog, catalog_complete=True,
    ) is None


def test_external_origin_evidence_expands_exact_scalar_consumed_from_resolved_callee() -> None:
    from aisl_interaction_lineage.builder import _external_origin_evidence
    from aisl_interaction_lineage.human_csv import human_rows

    class ScalarContinuationGateway(FakeGateway):
        def __init__(self, *, direct_resolution_status: str = "resolved") -> None:
            super().__init__()
            self.direct_resolution_status = direct_resolution_status

        def list_repository_value_nodes(
            self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
            operation: str | None = None, max_results: int = 500, page_token: str = "",
        ) -> Mapping[str, Any]:
            if repository_id != "maven:g:a:1.2.3":
                items: list[Mapping[str, Any]] = []
            elif node_kind == "field" and operation is None:
                items = [
                    {
                        "value_node_id": "external-target-details",
                        "node_kind": "field",
                        "operation": "Mapper.map",
                        "display_ref": "mapped.details",
                        "source_path": "Mapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "local_field",
                            "property_name": "details",
                            "operation": "Mapper.map",
                        }},
                    },
                    {
                        "value_node_id": "external-target-details-id",
                        "node_kind": "field",
                        "operation": "FromMapper.mapDetails",
                        "display_ref": "mappedDetails.id",
                        "source_path": "FromMapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "local_field",
                            "property_name": "id",
                            "method_id": "method-map-details",
                            "operation": "FromMapper.mapDetails",
                        }},
                    },
                ]
            elif operation == "Mapper.map":
                items = [
                    {
                        "value_node_id": "external-owner-profile",
                        "node_kind": "local_value",
                        "operation": operation,
                        "display_ref": "mapped",
                        "type_ref": "ExternalProfile",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "local_variable",
                            "symbol": "mapped",
                            "declared_type": "ExternalProfile",
                            "operation": operation,
                        }},
                    },
                    {
                        "value_node_id": "derive-details",
                        "node_kind": "derivation",
                        "operation": operation,
                        "display_ref": "Mapper.mapDetails()",
                        "type_ref": "ExternalDetails",
                        "source_path": "Mapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "method_invocation",
                            "declared_type": "ExternalDetails",
                            "callee_method_id": "method-map-details",
                            "method_name": "mapDetails",
                            "resolution_status": self.direct_resolution_status,
                            "operation": operation,
                        }},
                    },
                ]
            elif operation == "FromMapper.mapDetails":
                items = [
                    {
                        "value_node_id": "mapped-details",
                        "node_kind": "local_value",
                        "operation": operation,
                        "display_ref": "mappedDetails",
                        "type_ref": "ExternalDetails",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "local_variable",
                            "symbol": "mappedDetails",
                            "declared_type": "ExternalDetails",
                            "method_id": "method-map-details",
                            "operation": operation,
                        }},
                    },
                    {
                        "value_node_id": "details-param",
                        "node_kind": "local_value",
                        "operation": operation,
                        "display_ref": "details",
                        "type_ref": "Details",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "method_parameter",
                            "symbol": "details",
                            "declared_type": "Details",
                            "method_id": "method-map-details",
                            "operation": operation,
                        }},
                    },
                    {
                        "value_node_id": "external-origin-details-id",
                        "node_kind": "field",
                        "operation": operation,
                        "display_ref": "details.id",
                        "source_path": "FromMapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "local_field",
                            "property_name": "id",
                            "method_id": "method-map-details",
                            "operation": operation,
                        }},
                    },
                    {
                        "value_node_id": "external-target-details-id",
                        "node_kind": "field",
                        "operation": operation,
                        "display_ref": "mappedDetails.id",
                        "source_path": "FromMapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "local_field",
                            "property_name": "id",
                            "method_id": "method-map-details",
                            "operation": operation,
                        }},
                    },
                    {
                        "value_node_id": "derive-id",
                        "node_kind": "derivation",
                        "operation": operation,
                        "display_ref": "FromMapper.mapId()",
                        "source_path": "FromMapper.java",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "method_invocation",
                            "method_id": "method-map-details",
                            "operation": operation,
                        }},
                    },
                ]
            else:
                items = []
            return {"result": {
                "items": items,
                "total_count": len(items),
                "returned_count": len(items),
                "truncated": False,
            }}

        def resolve_attribute_paths(
            self, binding: AislBinding, *, source: str,
            selected_repo_ids: Sequence[str], direction: str,
        ) -> Mapping[str, Any]:
            if source == "external-target-details":
                target = {
                    "value_node_id": source, "display_ref": "mapped.details",
                    "node_kind": "field", "source_path": "Mapper.java",
                }
                origin = {
                    "value_node_id": "external-origin-details", "display_ref": "source.details",
                    "node_kind": "field", "source_path": "Mapper.java",
                }
                derivation = {
                    "value_node_id": "derive-details", "display_ref": "Mapper.mapDetails()",
                    "node_kind": "derivation", "source_path": "Mapper.java",
                }
                return {"result": {
                    "status": "partial", "source": target,
                    "paths": [{
                        "status": "partial", "hop_count": 2, "confidence": "confirmed",
                        "start": target, "end": origin,
                        "steps": [
                            {"value_flow_edge_id": "edge-details-2", "source": derivation, "target": target},
                            {"value_flow_edge_id": "edge-details-1", "source": origin, "target": derivation},
                        ],
                    }], "gaps": [],
                }}
            if source == "external-target-details-id":
                target = {
                    "value_node_id": source, "display_ref": "mappedDetails.id",
                    "node_kind": "field", "source_path": "FromMapper.java",
                }
                origin = {
                    "value_node_id": "external-origin-details-id", "display_ref": "details.id",
                    "node_kind": "field", "source_path": "FromMapper.java",
                }
                derivation = {
                    "value_node_id": "derive-id", "display_ref": "FromMapper.mapId()",
                    "node_kind": "derivation", "source_path": "FromMapper.java",
                }
                return {"result": {
                    "status": "partial", "source": target,
                    "paths": [{
                        "status": "partial", "hop_count": 2, "confidence": "confirmed",
                        "start": target, "end": origin,
                        "steps": [
                            {"value_flow_edge_id": "edge-id-2", "source": derivation, "target": target},
                            {"value_flow_edge_id": "edge-id-1", "source": origin, "target": derivation},
                        ],
                    }], "gaps": [],
                }}
            return super().resolve_attribute_paths(
                binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction,
            )

    binding = AislBinding(
        "service", "service-system", "service-rev",
        ("service", "maven:g:a:1.2.3"),
    )
    material_gap = {"evidence": [{
        "terminal_value_node_id": "terminal-details",
        "terminal_display_ref": "converter.convert().details",
        "terminal_property_name": "details",
        "parent_display_ref": "converter.convert()",
        "parent_declared_type": "ExternalProfile",
    }]}
    local_side = {"query": {"result": {"paths": [{
        "confidence": "confirmed", "hop_count": 2,
        "end": {
            "value_node_id": "local-details-id", "display_ref": "details.id", "node_kind": "field",
            "operation": "LocalMapper.consume",
        },
    }]}}}
    local_catalog = [
        {
            "value_node_id": "local-details-id", "node_kind": "field",
            "operation": "LocalMapper.consume", "display_ref": "details.id",
            "payload_json": {"source_occurrence": {
                "occurrence_kind": "local_field", "property_name": "id", "operation": "LocalMapper.consume",
            }},
        },
        {
            "value_node_id": "local-details-param", "node_kind": "local_value",
            "operation": "LocalMapper.consume", "display_ref": "details", "type_ref": "ExternalDetails",
            "payload_json": {"source_occurrence": {
                "occurrence_kind": "method_parameter", "symbol": "details",
                "declared_type": "ExternalDetails", "operation": "LocalMapper.consume",
            }},
        },
    ]

    evidence = _external_origin_evidence(
        ScalarContinuationGateway(), binding=binding, repository_id="service",
        material_gap=material_gap, cache={}, resolved_side=local_side,
        local_catalog=local_catalog, local_catalog_complete=True,
    )
    assert evidence is not None
    assert len(evidence["segments"]) == 2
    nested = next(segment for segment in evidence["segments"] if segment["semantic_depth"] == 1)
    assert nested["property_name"] == "id"
    assert nested["target_declared_type"] == "ExternalDetails"
    assert nested["origins"][0]["display_ref"] == "details.id"
    assert nested["composed_origins"] == [{
        "display_ref": "source.details.id",
        "source_value_node_id": "external-origin-details",
        "nested_origin_value_node_id": "external-origin-details-id",
        "basis": "exact_resolved_callee_parameter_property_projection",
    }]
    assert nested["parent_transformation_display_ref"] == "Mapper.mapDetails()"

    source_side = {
        "anchor_status": "resolved",
        "query": {"result": {"paths": [{
            "end": {"display_ref": "details.id"}, "steps": [],
        }]}},
        "external_origin_evidence": evidence,
    }
    lineage = {
        "format": "interaction-attribute-lineage/v1",
        "edge": {"protocol": "http", "method": "POST", "matched_identity": "/example"},
        "journeys": [{
            "transport_role": "response", "field_path": "profile.details.id",
            "source_repository_id": "service", "target_repository_id": "caller",
            "source_side": source_side,
            "target_side": {"anchor_status": "terminal", "query": {"result": {"paths": []}}},
        }],
        "gaps": [],
    }
    row = human_rows(lineage)[0]
    assert row["producer_attribute"] == "source.details.id"
    assert "source.details.id --[FromMapper.mapId()]→ mappedDetails.id" in row["full_attribute_path"]
    assert "inside Mapper.mapDetails()" in row["full_attribute_path"]


def test_external_origin_evidence_does_not_expand_scalar_without_exact_resolved_callee() -> None:
    # Reuse the positive test's public behavior indirectly: a direct mapper
    # invocation that is not mechanically resolved may still prove the object
    # property, but it must not authorize projection of child scalar fields.
    from aisl_interaction_lineage.builder import _external_origin_evidence

    class Gateway(FakeGateway):
        def list_repository_value_nodes(
            self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
            operation: str | None = None, max_results: int = 500, page_token: str = "",
        ) -> Mapping[str, Any]:
            if repository_id == "maven:g:a:1.2.3" and node_kind == "field" and operation is None:
                items = [{
                    "value_node_id": "target-details", "node_kind": "field",
                    "operation": "Mapper.map", "display_ref": "mapped.details",
                    "payload_json": {"source_occurrence": {
                        "property_name": "details", "occurrence_kind": "local_field",
                    }},
                }]
            elif repository_id == "maven:g:a:1.2.3" and operation == "Mapper.map":
                items = [
                    {
                        "value_node_id": "owner", "node_kind": "local_value",
                        "operation": operation, "display_ref": "mapped", "type_ref": "ExternalProfile",
                        "payload_json": {"source_occurrence": {
                            "symbol": "mapped", "declared_type": "ExternalProfile",
                            "occurrence_kind": "local_variable",
                        }},
                    },
                    {
                        "value_node_id": "derive", "node_kind": "derivation",
                        "operation": operation, "display_ref": "Mapper.mapDetails()", "type_ref": "ExternalDetails",
                        "payload_json": {"source_occurrence": {
                            "occurrence_kind": "method_invocation", "declared_type": "ExternalDetails",
                            "method_name": "mapDetails", "resolution_status": "external_or_unresolved",
                        }},
                    },
                ]
            else:
                items = []
            return {"result": {"items": items, "total_count": len(items), "returned_count": len(items), "truncated": False}}

        def resolve_attribute_paths(
            self, binding: AislBinding, *, source: str,
            selected_repo_ids: Sequence[str], direction: str,
        ) -> Mapping[str, Any]:
            if source == "target-details":
                target = {"value_node_id": source, "display_ref": "mapped.details", "node_kind": "field"}
                origin = {"value_node_id": "origin-details", "display_ref": "source.details", "node_kind": "field"}
                derive = {"value_node_id": "derive", "display_ref": "Mapper.mapDetails()", "node_kind": "derivation"}
                return {"result": {"status": "partial", "source": target, "paths": [{
                    "hop_count": 2, "confidence": "confirmed", "start": target, "end": origin,
                    "steps": [
                        {"value_flow_edge_id": "e2", "source": derive, "target": target},
                        {"value_flow_edge_id": "e1", "source": origin, "target": derive},
                    ],
                }], "gaps": []}}
            return super().resolve_attribute_paths(binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction)

    binding = AislBinding("service", "system", "rev", ("service", "maven:g:a:1.2.3"))
    evidence = _external_origin_evidence(
        Gateway(), binding=binding, repository_id="service",
        material_gap={"evidence": [{
            "terminal_value_node_id": "terminal-details",
            "terminal_display_ref": "converter.convert().details",
            "terminal_property_name": "details",
            "parent_display_ref": "converter.convert()",
            "parent_declared_type": "ExternalProfile",
        }]},
        cache={},
        resolved_side={"query": {"result": {"paths": [{
            "confidence": "confirmed", "hop_count": 1,
            "end": {"value_node_id": "local-id", "display_ref": "details.id", "node_kind": "field", "operation": "Local.consume"},
        }]}}},
        local_catalog=[
            {"value_node_id": "local-id", "node_kind": "field", "operation": "Local.consume", "display_ref": "details.id",
             "payload_json": {"source_occurrence": {"property_name": "id", "occurrence_kind": "local_field"}}},
            {"value_node_id": "local-owner", "node_kind": "local_value", "operation": "Local.consume", "display_ref": "details", "type_ref": "ExternalDetails",
             "payload_json": {"source_occurrence": {"symbol": "details", "declared_type": "ExternalDetails", "occurrence_kind": "method_parameter"}}},
        ],
        local_catalog_complete=True,
    )
    assert evidence is not None
    assert len(evidence["segments"]) == 1
    assert evidence["segments"][0]["semantic_depth"] == 0



def test_target_semantic_projection_preserves_proven_nested_consumer_chain() -> None:
    anchor = {
        "value_node_id": "anchor",
        "node_kind": "field",
        "display_ref": "payload.date",
        "operation": "Boundary.consume",
    }
    person = {
        "value_node_id": "person-birthday",
        "node_kind": "field",
        "display_ref": "person.birthday",
        "operation": "Mapper.toPerson",
    }
    customer = {
        "value_node_id": "customer-birthday",
        "node_kind": "field",
        "display_ref": "customer.personInfo.birthday",
        "operation": "Handler.fill",
    }
    account = {
        "value_node_id": "account-birthday",
        "node_kind": "field",
        "display_ref": "account.custInfo.personInfo.birthday",
        "operation": "Handler.fill",
    }
    bank = {
        "value_node_id": "bank-birthday",
        "node_kind": "field",
        "display_ref": "bank.cardAcctId.custInfo.personInfo.birthday",
        "operation": "Response.map",
    }
    rows = {
        "value_node_id": "rows-birthday",
        "node_kind": "field",
        "display_ref": "rows.cardAcctId.custInfo.personInfo.birthday",
        "operation": "Response.collect",
    }
    side = {
        "anchor_status": "resolved",
        "resolved_anchor": anchor,
        "query": {"result": {"paths": [{
            "start": anchor,
            "steps": [
                {"target": person},
                {"target": customer},
                {"target": account},
                {"target": bank},
                {"target": rows},
            ],
            "end": rows,
        }]}},
    }
    catalog = [
        anchor,
        {
            **person,
            "occurrence_id": "person-field-occ",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "person-object", "property_name": "birthday"}},
        },
        {
            "value_node_id": "person-object-node", "occurrence_id": "person-object", "node_kind": "local_value",
            "display_ref": "person", "type_ref": "PersonInfo",
            "payload_json": {"source_occurrence": {"declared_type": "PersonInfo"}},
        },
        {
            **customer,
            "occurrence_id": "customer-field-occ",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "customer-object", "property_name": "personInfo.birthday"}},
        },
        {
            "value_node_id": "customer-object-node", "occurrence_id": "customer-object", "node_kind": "local_value",
            "display_ref": "customer", "type_ref": "CustInfo",
            "payload_json": {"source_occurrence": {"declared_type": "CustInfo"}},
        },
        {
            **account,
            "occurrence_id": "account-field-occ",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "account-object", "property_name": "custInfo.personInfo.birthday"}},
        },
        {
            "value_node_id": "account-object-node", "occurrence_id": "account-object", "node_kind": "local_value",
            "display_ref": "account", "type_ref": "CardAcctId",
            "payload_json": {"source_occurrence": {"declared_type": "CardAcctId"}},
        },
        {
            **bank,
            "occurrence_id": "bank-field-occ",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "bank-object", "property_name": "cardAcctId.custInfo.personInfo.birthday"}},
        },
        {
            "value_node_id": "bank-object-node", "occurrence_id": "bank-object", "node_kind": "local_value",
            "display_ref": "bank", "type_ref": "BankAcctRec",
            "payload_json": {"source_occurrence": {"declared_type": "BankAcctRec"}},
        },
        {
            **rows,
            "occurrence_id": "rows-field-occ",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "rows-object", "property_name": "cardAcctId.custInfo.personInfo.birthday"}},
        },
        {
            "value_node_id": "rows-object-node", "occurrence_id": "rows-object", "node_kind": "local_value",
            "display_ref": "rows", "type_ref": "List",
            "payload_json": {"source_occurrence": {"declared_type": "List"}},
        },
    ]

    projection = _target_semantic_projection(side, catalog=catalog)

    assert projection is not None
    assert projection["entry_consumer_attribute"] == "PersonInfo.birthday"
    assert projection["consumer_attribute"] == "rows[].cardAcctId.custInfo.personInfo.birthday"
    assert [item["semantic_ref"] for item in projection["chain"]] == [
        "PersonInfo.birthday",
        "CustInfo.personInfo.birthday",
        "CardAcctId.custInfo.personInfo.birthday",
        "BankAcctRec.cardAcctId.custInfo.personInfo.birthday",
        "rows[].cardAcctId.custInfo.personInfo.birthday",
    ]


def test_target_semantic_projection_fails_closed_when_first_consumer_is_ambiguous() -> None:
    anchor = {"value_node_id": "anchor", "node_kind": "field", "display_ref": "payload.date"}
    one = {"value_node_id": "one", "node_kind": "field", "display_ref": "one.birthday"}
    two = {"value_node_id": "two", "node_kind": "field", "display_ref": "two.birthday"}
    side = {
        "anchor_status": "resolved",
        "resolved_anchor": anchor,
        "query": {"result": {"paths": [
            {"start": anchor, "steps": [{"target": one}], "end": one},
            {"start": anchor, "steps": [{"target": two}], "end": two},
        ]}},
    }
    catalog = [
        anchor,
        {
            **one, "occurrence_id": "one-field",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "one-object", "property_name": "birthday"}},
        },
        {
            "value_node_id": "one-object-node", "occurrence_id": "one-object", "node_kind": "local_value",
            "display_ref": "one", "type_ref": "PersonInfo",
            "payload_json": {"source_occurrence": {"declared_type": "PersonInfo"}},
        },
        {
            **two, "occurrence_id": "two-field",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "two-object", "property_name": "birthday"}},
        },
        {
            "value_node_id": "two-object-node", "occurrence_id": "two-object", "node_kind": "local_value",
            "display_ref": "two", "type_ref": "OtherInfo",
            "payload_json": {"source_occurrence": {"declared_type": "OtherInfo"}},
        },
    ]

    assert _target_semantic_projection(side, catalog=catalog) is None



def test_target_semantic_projection_does_not_replace_boundary_for_untyped_first_consumer() -> None:
    anchor = {"value_node_id": "anchor", "node_kind": "field", "display_ref": "payload.id"}
    first = {"value_node_id": "first", "node_kind": "field", "display_ref": "parameters.id"}
    typed = {"value_node_id": "typed", "node_kind": "field", "display_ref": "request.id"}
    side = {
        "anchor_status": "resolved",
        "resolved_anchor": anchor,
        "query": {"result": {"paths": [{
            "start": anchor,
            "steps": [{"target": first}, {"target": typed}],
            "end": typed,
        }]}},
    }
    catalog = [
        anchor,
        {
            **first,
            "occurrence_id": "first-field",
            "payload_json": {"source_occurrence": {"property_name": "id"}},
        },
        {
            **typed,
            "occurrence_id": "typed-field",
            "payload_json": {"source_occurrence": {"object_occurrence_id": "typed-object", "property_name": "id"}},
        },
        {
            "value_node_id": "typed-object-node", "occurrence_id": "typed-object", "node_kind": "local_value",
            "display_ref": "request", "type_ref": "RequestDto",
            "payload_json": {"source_occurrence": {"declared_type": "RequestDto"}},
        },
    ]
    assert _target_semantic_projection(side, catalog=catalog) is None



def test_target_semantic_projection_skips_untyped_alias_and_missing_intermediate_level() -> None:
    anchor = {"value_node_id": "anchor", "node_kind": "field", "display_ref": "clientInfo.identifications.documentSeries"}
    alias = {"value_node_id": "alias", "node_kind": "field", "display_ref": "identifications.documentSeries"}
    person = {"value_node_id": "person", "node_kind": "field", "display_ref": "person.identityCard.idNum"}
    customer = {"value_node_id": "customer", "node_kind": "field", "display_ref": "customer.personInfo.identityCard.idNum"}
    bank = {"value_node_id": "bank", "node_kind": "field", "display_ref": "bank.cardAcctId.custInfo.personInfo.identityCard.idNum"}
    rows = {"value_node_id": "rows", "node_kind": "field", "display_ref": "rows.cardAcctId.custInfo.personInfo.identityCard.idNum"}
    side = {
        "anchor_status": "resolved",
        "resolved_anchor": anchor,
        "query": {"result": {"paths": [{
            "start": anchor,
            "steps": [{"target": alias}, {"target": person}, {"target": customer}, {"target": bank}, {"target": rows}],
            "end": rows,
        }]}},
    }
    catalog = [
        anchor,
        {**alias, "occurrence_id": "alias-field", "payload_json": {"source_occurrence": {"property_name": "documentSeries"}}},
        {**person, "occurrence_id": "person-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "person-object", "property_name": "identityCard.idNum"}}},
        {"value_node_id": "person-object-node", "occurrence_id": "person-object", "node_kind": "local_value", "display_ref": "person", "type_ref": "PersonInfo", "payload_json": {"source_occurrence": {"declared_type": "PersonInfo"}}},
        {**customer, "occurrence_id": "customer-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "customer-object", "property_name": "personInfo.identityCard.idNum"}}},
        {"value_node_id": "customer-object-node", "occurrence_id": "customer-object", "node_kind": "local_value", "display_ref": "customer", "type_ref": "CustInfo", "payload_json": {"source_occurrence": {"declared_type": "CustInfo"}}},
        {**bank, "occurrence_id": "bank-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "bank-object", "property_name": "cardAcctId.custInfo.personInfo.identityCard.idNum"}}},
        {"value_node_id": "bank-object-node", "occurrence_id": "bank-object", "node_kind": "local_value", "display_ref": "bank", "type_ref": "BankAcctRec", "payload_json": {"source_occurrence": {"declared_type": "BankAcctRec"}}},
        {**rows, "occurrence_id": "rows-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "rows-object", "property_name": "cardAcctId.custInfo.personInfo.identityCard.idNum"}}},
        {"value_node_id": "rows-object-node", "occurrence_id": "rows-object", "node_kind": "local_value", "display_ref": "rows", "type_ref": "List", "payload_json": {"source_occurrence": {"declared_type": "List"}}},
    ]
    projection = _target_semantic_projection(side, catalog=catalog)
    assert projection is not None
    assert projection["entry_consumer_attribute"] == "PersonInfo.identityCard.idNum"
    assert projection["consumer_attribute"] == "rows[].cardAcctId.custInfo.personInfo.identityCard.idNum"
    assert [item["semantic_ref"] for item in projection["chain"]] == [
        "PersonInfo.identityCard.idNum",
        "CustInfo.personInfo.identityCard.idNum",
        "BankAcctRec.cardAcctId.custInfo.personInfo.identityCard.idNum",
        "rows[].cardAcctId.custInfo.personInfo.identityCard.idNum",
    ]


def test_target_semantic_projection_does_not_promote_concrete_collection_class() -> None:
    anchor = {"value_node_id": "anchor", "node_kind": "field", "display_ref": "clientInfo.birthDate"}
    person = {"value_node_id": "person", "node_kind": "field", "display_ref": "person.birthday"}
    customer = {"value_node_id": "customer", "node_kind": "field", "display_ref": "customer.personInfo.birthday"}
    array_list = {"value_node_id": "array", "node_kind": "field", "display_ref": "result.bankAcctRec.cardAcctId.custInfo.personInfo.birthday"}
    side = {
        "anchor_status": "resolved",
        "resolved_anchor": anchor,
        "query": {"result": {"paths": [{
            "start": anchor,
            "steps": [{"target": person}, {"target": customer}, {"target": array_list}],
            "end": array_list,
        }]}},
    }
    catalog = [
        anchor,
        {**person, "occurrence_id": "person-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "person-object", "property_name": "birthday"}}},
        {"value_node_id": "person-object-node", "occurrence_id": "person-object", "node_kind": "local_value", "display_ref": "person", "type_ref": "PersonInfo", "payload_json": {"source_occurrence": {"declared_type": "PersonInfo"}}},
        {**customer, "occurrence_id": "customer-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "customer-object", "property_name": "personInfo.birthday"}}},
        {"value_node_id": "customer-object-node", "occurrence_id": "customer-object", "node_kind": "local_value", "display_ref": "customer", "type_ref": "CustInfo", "payload_json": {"source_occurrence": {"declared_type": "CustInfo"}}},
        {**array_list, "occurrence_id": "array-field", "payload_json": {"source_occurrence": {"object_occurrence_id": "array-object", "property_name": "bankAcctRec.cardAcctId.custInfo.personInfo.birthday"}}},
        {"value_node_id": "array-object-node", "occurrence_id": "array-object", "node_kind": "local_value", "display_ref": "result", "type_ref": "ArrayList", "payload_json": {"source_occurrence": {"declared_type": "ArrayList"}}},
    ]
    projection = _target_semantic_projection(side, catalog=catalog)
    assert projection is not None
    assert projection["consumer_attribute"] == "result[].bankAcctRec.cardAcctId.custInfo.personInfo.birthday"
    assert all(not item["semantic_ref"].startswith("ArrayList.") for item in projection["chain"])
