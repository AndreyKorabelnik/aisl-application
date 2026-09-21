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
    assert journey["source_side"]["anchor_selection_basis"] == "exact_topology_interface_id"
    assert journey["target_side"]["anchor_selection_basis"] == "exact_topology_interface_id"
    assert any(call["source"] == "caller-wanted" for call in gateway.calls)
    assert any(call["source"] == "service-wanted" for call in gateway.calls)


def test_missing_anchor_stays_partial_gap_without_guessing() -> None:
    ref = wire_display_ref("response", "profile.id")
    gateway = FakeGateway(missing={("caller", ref)})
    result = build_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway, transport_roles=("response",))
    journey = next(item for item in result["journeys"] if item["field_path"] == "profile.id")
    assert journey["crossing"]["status"] == "partial"
    assert journey["target_side"]["anchor_status"] == "unresolved"
    assert any(gap["reason"] == "target_boundary_anchor_unresolved" for gap in result["gaps"])


def test_rejects_active_revision_binding() -> None:
    with pytest.raises(ValueError, match="exact immutable revision"):
        AislBinding.from_payload({"repository_id": "r", "system_id": "s", "revision_id": "latest"})
