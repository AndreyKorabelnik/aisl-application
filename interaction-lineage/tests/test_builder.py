from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from aisl_interaction_lineage.builder import build_interaction_lineage
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
