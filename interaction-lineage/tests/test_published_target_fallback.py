from __future__ import annotations

from typing import Any, Mapping, Sequence

from aisl_interaction_lineage.builder import build_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
from aisl_interaction_lineage.human_csv import human_rows

EDGE_ID = "repository_edge_published_fallback"


def _topology(field_path: str = "profile.id") -> dict[str, Any]:
    return {
        "format": "repository-topology/v4",
        "topology_id": "topology_published_fallback",
        "edges": [{
            "edge_id": EDGE_ID,
            "protocol": "http",
            "method": "POST",
            "matched_identity": "/example",
            "match_classification": "exact",
            "claim_classification": "observed",
            "confidence": "high",
            "source_repository_id": "caller",
            "target_repository_id": "service",
            "source_half_wires": [{
                "repository_id": "caller",
                "interface_id": "caller-if",
                "direction": "outbound",
                "request_payload": "RequestDto",
                "response_payload": "ResponseDto",
                "request_field_names": [],
                "response_field_paths": [field_path],
            }],
            "target_half_wires": [{
                "repository_id": "service",
                "interface_id": "service-if",
                "direction": "inbound",
                "request_payload": "RequestDto",
                "response_payload": "ResponseDto",
                "request_field_names": [],
                "response_field_paths": [field_path],
            }],
            "attribute_flows": [{
                "transport_role": "response",
                "source_repository_id": "service",
                "target_repository_id": "caller",
                "attribute_names": [field_path.split(".", 1)[0]],
            }],
        }],
    }


def _bindings() -> BindingIndex:
    return BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev"),
        AislBinding("service", "service-system", "service-rev"),
    ])


def _request_topology(field_path: str = "channel") -> dict[str, Any]:
    topology = _topology(field_path)
    edge = topology["edges"][0]
    edge["source_half_wires"][0]["request_field_names"] = [field_path]
    edge["source_half_wires"][0]["response_field_paths"] = []
    edge["target_half_wires"][0]["request_field_names"] = [field_path]
    edge["target_half_wires"][0]["response_field_paths"] = []
    edge["attribute_flows"] = [{
        "transport_role": "request",
        "source_repository_id": "caller",
        "target_repository_id": "service",
        "attribute_names": [field_path.split(".", 1)[0]],
    }]
    return topology


class PublishedFallbackGateway:
    def __init__(self, pages: dict[str, list[Mapping[str, Any]]], *, incomplete: bool = False) -> None:
        self.pages = pages
        self.incomplete = incomplete
        self.calls: list[dict[str, Any]] = []
        self.nodes_by_id = {
            str(item.get("value_node_id") or ""): item
            for rows in pages.values()
            for item in rows
            if str(item.get("value_node_id") or "")
        }

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"kind": "resolve", "repo": repo, "source": source, "direction": direction})
        if repo == "service":
            node = {"repo_id": repo, "value_node_id": source, "display_ref": source, "operation": "Service.produce"}
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": []}}
        if source in self.nodes_by_id:
            raw = self.nodes_by_id[source]
            node = {
                "repo_id": repo,
                "value_node_id": source,
                "display_ref": raw.get("display_ref"),
                "operation": raw.get("operation"),
                "node_kind": raw.get("node_kind"),
            }
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": [{"reason": "no_observed_outgoing_value_flow", "node": node}]}}
        return {"result": {"status": "source_not_found", "paths": [], "gaps": [{"reason": "source_not_found", "reference": source}]}}

    def list_repository_value_nodes(
        self,
        binding: AislBinding,
        *,
        repository_id: str,
        node_kind: str | None = None,
        operation: str | None = None,
        max_results: int = 500,
        page_token: str = "",
    ) -> Mapping[str, Any]:
        self.calls.append({"kind": "list", "repo": repository_id, "page_token": page_token, "operation": operation})
        if repository_id != "caller":
            return {"result": {"items": [], "truncated": False, "next_token": ""}}
        token = page_token or "first"
        items = list(self.pages.get(token, []))
        if token == "first" and self.incomplete:
            return {"result": {"items": items, "truncated": True, "next_token": ""}}
        if token == "first" and "second" in self.pages:
            return {"result": {"items": items, "truncated": True, "next_token": "second"}}
        return {"result": {"items": items, "truncated": False, "next_token": ""}}


def _payload_parameter() -> dict[str, Any]:
    return {
        "repo_id": "caller",
        "value_node_id": "payload-param",
        "node_kind": "parameter",
        "operation": "Mapper.map",
        "display_ref": "payload",
        "type_ref": "ResponseDto",
        "source_path": "Mapper.java",
    }


def _candidate(value_node_id: str = "candidate-good", display_ref: str = "status") -> dict[str, Any]:
    return {
        "repo_id": "caller",
        "value_node_id": value_node_id,
        "node_kind": "field",
        "operation": "Mapper.map",
        "display_ref": display_ref,
        "type_ref": None,
        "source_path": "Mapper.java",
    }


def _payload_local(
    value_node_id: str = "payload-local",
    *,
    operation: str = "Client.call",
    display_ref: str = "request",
    type_ref: str = "RequestDto",
    source_path: str = "Client.java",
) -> dict[str, Any]:
    return {
        "repo_id": "caller",
        "value_node_id": value_node_id,
        "node_kind": "local_value",
        "operation": operation,
        "display_ref": display_ref,
        "type_ref": type_ref,
        "source_path": source_path,
    }


def _source_candidate(
    value_node_id: str = "source-candidate-good",
    *,
    operation: str = "Client.call",
    display_ref: str = "request.channel",
    source_path: str = "Client.java",
) -> dict[str, Any]:
    return {
        "repo_id": "caller",
        "value_node_id": value_node_id,
        "node_kind": "field",
        "operation": operation,
        "display_ref": display_ref,
        "type_ref": None,
        "source_path": source_path,
    }


def _journey(result: Mapping[str, Any], field_path: str) -> Mapping[str, Any]:
    return next(item for item in result["journeys"] if item["field_path"] == field_path)


def test_target_fallback_paginates_and_resolves_unique_payload_scoped_structural_node() -> None:
    gateway = PublishedFallbackGateway({"first": [_payload_parameter()], "second": [_candidate()]})
    result = build_interaction_lineage(_topology("status"), edge_id=EDGE_ID, bindings=_bindings(), gateway=gateway, transport_roles=("response",))
    journey = _journey(result, "status")
    assert journey["target_side"]["anchor_status"] == "resolved"
    assert journey["target_side"]["resolved_anchor"]["value_node_id"] == "candidate-good"
    assert journey["target_side"]["anchor_selection_basis"] == "published_payload_structural_candidate:unique_semantic_node"
    assert result["summary"]["target_local_anchor_gap_count"] == 0
    assert [
        call["page_token"]
        for call in gateway.calls
        if call["kind"] == "list" and call["repo"] == "caller" and call["operation"] is None
    ] == ["", "second"]


def test_nested_structural_suffix_is_resolved_only_inside_exact_payload_operation() -> None:
    suffix = _candidate("candidate-message", "output.status.message")
    unrelated = {
        **_candidate("candidate-unrelated", "other.status.message"),
        "operation": "Other.map",
    }
    unrelated_payload = {**_payload_parameter(), "value_node_id": "other-param", "operation": "Other.map", "type_ref": "OtherResponse"}
    gateway = PublishedFallbackGateway({"first": [_payload_parameter(), unrelated_payload, suffix, unrelated]})
    result = build_interaction_lineage(_topology("status.message"), edge_id=EDGE_ID, bindings=_bindings(), gateway=gateway, transport_roles=("response",))
    journey = _journey(result, "status.message")
    assert journey["target_side"]["anchor_status"] == "resolved"
    assert journey["target_side"]["resolved_anchor"]["value_node_id"] == "candidate-message"


def test_complete_scan_without_payload_scoped_field_use_is_terminal_not_gap() -> None:
    gateway = PublishedFallbackGateway({"first": [_payload_parameter()]})
    result = build_interaction_lineage(_topology("missing"), edge_id=EDGE_ID, bindings=_bindings(), gateway=gateway, transport_roles=("response",))
    journey = _journey(result, "missing")
    assert journey["target_side"]["anchor_status"] == "terminal"
    assert journey["target_side"]["terminal_proof"]["repository_value_node_scan_complete"] is True
    assert result["summary"]["target_local_anchor_gap_count"] == 0
    row = next(row for row in human_rows(result) if row["crossing_attribute"] == "missing")
    assert row["consumer_attribute"] == ""
    assert row["gap"] == ""
    assert "[unresolved target]" not in row["full_attribute_path"]


def test_incomplete_node_scan_does_not_invent_terminal() -> None:
    gateway = PublishedFallbackGateway({"first": [_payload_parameter()]}, incomplete=True)
    result = build_interaction_lineage(_topology("missing"), edge_id=EDGE_ID, bindings=_bindings(), gateway=gateway, transport_roles=("response",))
    journey = _journey(result, "missing")
    assert journey["target_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["target_local_anchor_gap_count"] == 1


def test_multiple_payload_scoped_structural_candidates_remain_unresolved() -> None:
    second_parameter = {
        **_payload_parameter(),
        "value_node_id": "payload-param-2",
        "operation": "Mapper2.map",
    }
    second_candidate = {
        **_candidate("candidate-second", "status"),
        "operation": "Mapper2.map",
        "source_path": "Mapper2.java",
    }
    pages = {"first": [_payload_parameter(), _candidate(), second_parameter, second_candidate]}
    gateway = PublishedFallbackGateway(pages)
    result = build_interaction_lineage(_topology("status"), edge_id=EDGE_ID, bindings=_bindings(), gateway=gateway, transport_roles=("response",))
    journey = _journey(result, "status")
    assert journey["target_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["target_local_anchor_gap_count"] == 1


def test_source_fallback_resolves_exact_field_of_exact_payload_instance() -> None:
    gateway = PublishedFallbackGateway({"first": [_payload_local(), _source_candidate()]})
    result = build_interaction_lineage(
        _request_topology("channel"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    journey = _journey(result, "channel")
    assert journey["source_side"]["anchor_status"] == "resolved"
    assert journey["source_side"]["resolved_anchor"]["value_node_id"] == "source-candidate-good"
    assert journey["source_side"]["anchor_selection_basis"] == (
        "published_payload_instance_structural_candidate:unique_semantic_node"
    )
    assert result["summary"]["source_local_anchor_gap_count"] == 0


def test_source_fallback_requires_exact_payload_type_context() -> None:
    wrong_payload = _payload_local(type_ref="OtherRequest")
    gateway = PublishedFallbackGateway({"first": [wrong_payload, _source_candidate()]})
    result = build_interaction_lineage(
        _request_topology("channel"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    journey = _journey(result, "channel")
    assert journey["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_fallback_keeps_multiple_exact_payload_operations_ambiguous() -> None:
    pages = {
        "first": [
            _payload_local(),
            _source_candidate(),
            _payload_local("payload-local-2", operation="Client2.call", source_path="Client2.java"),
            _source_candidate(
                "source-candidate-2",
                operation="Client2.call",
                source_path="Client2.java",
            ),
        ]
    }
    gateway = PublishedFallbackGateway(pages)
    result = build_interaction_lineage(
        _request_topology("channel"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    journey = _journey(result, "channel")
    assert journey["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_fallback_does_not_resolve_from_incomplete_node_scan() -> None:
    gateway = PublishedFallbackGateway(
        {"first": [_payload_local(), _source_candidate()]},
        incomplete=True,
    )
    result = build_interaction_lineage(
        _request_topology("channel"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    journey = _journey(result, "channel")
    assert journey["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


class RoutePublishedGateway:
    def __init__(
        self,
        nodes_by_repo: dict[str, list[Mapping[str, Any]]],
        *,
        resolved_repos: set[str],
        incomplete_repos: set[str] | None = None,
    ) -> None:
        self.nodes_by_repo = nodes_by_repo
        self.resolved_repos = resolved_repos
        self.incomplete_repos = incomplete_repos or set()
        self.calls: list[dict[str, Any]] = []

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        self.calls.append({"kind": "resolve", "repo": repo, "source": source, "direction": direction})
        if repo in self.resolved_repos:
            node = {"repo_id": repo, "value_node_id": f"resolved-{source}", "display_ref": source, "operation": "Resolved.op"}
            return {"result": {"status": "partial", "source": node, "paths": [{"start": node, "end": node, "steps": []}], "gaps": []}}
        return {"result": {"status": "source_not_found", "paths": [], "gaps": [{"reason": "source_not_found", "reference": source}]}}

    def list_repository_value_nodes(
        self,
        binding: AislBinding,
        *,
        repository_id: str,
        node_kind: str | None = None,
        operation: str | None = None,
        max_results: int = 500,
        page_token: str = "",
    ) -> Mapping[str, Any]:
        self.calls.append({"kind": "list", "repo": repository_id, "page_token": page_token, "operation": operation})
        items = [dict(item) for item in self.nodes_by_repo.get(repository_id, [])]
        if node_kind:
            items = [item for item in items if item.get("node_kind") == node_kind]
        if operation:
            items = [item for item in items if item.get("operation") == operation]
        if repository_id in self.incomplete_repos:
            return {"result": {"items": items, "truncated": True, "next_token": ""}}
        return {"result": {"items": items, "truncated": False, "next_token": ""}}


def _route_wire_node(
    repo: str,
    *,
    value_node_id: str,
    operation: str,
    role: str,
    field_path: str,
    endpoint: str = "/example",
    owner_ref: str | None = None,
    interface_direction: str = "outbound",
) -> dict[str, Any]:
    return {
        "repo_id": repo,
        "value_node_id": value_node_id,
        "node_kind": "wire_field",
        "operation": operation,
        "owner_ref": owner_ref or f"{operation}-if",
        "display_ref": f"HTTP {role} {field_path}",
        "type_ref": "string",
        "wire_path": field_path,
        "source_path": None,
        "payload_json": {
            "transport": {
                "protocol": "http",
                "http_method": "POST",
                "endpoint": endpoint,
                "payload_role": role,
                "interface_direction": interface_direction,
            }
        },
    }


def _counterpart_request_topology(field_path: str = "missing") -> dict[str, Any]:
    topology = _request_topology(field_path)
    edge = topology["edges"][0]
    edge["source_half_wires"][0]["request_shape_status"] = "unavailable_external_declaration"
    edge["target_half_wires"][0]["request_shape_status"] = "available_local_declaration"
    edge["attribute_flows"][0]["basis"] = [{
        "attribute_name": field_path,
        "edge_source_interface_id": "caller-if",
        "edge_target_interface_id": "service-if",
        "evidence_mode": "exact_payload_identity_counterpart_shape",
        "payload_identity": "RequestDto",
        "source_shape_status": "unavailable_external_declaration",
        "target_shape_status": "available_local_declaration",
    }]
    return topology


def test_source_fallback_resolves_unique_wire_field_in_exact_published_transport_context() -> None:
    gateway = RoutePublishedGateway(
        {
            "service": [
                _route_wire_node(
                    "service",
                    value_node_id="wire-contexts",
                    operation="Service.start",
                    role="response",
                    field_path="contexts",
                )
            ]
        },
        resolved_repos={"caller"},
    )
    result = build_interaction_lineage(
        _topology("contexts"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    journey = _journey(result, "contexts")
    assert journey["source_side"]["anchor_status"] == "resolved"
    assert journey["source_side"]["resolved_anchor"]["value_node_id"] == "wire-contexts"
    assert journey["source_side"]["anchor_selection_basis"] == "published_route_wire_field:exact_transport_and_field"
    assert result["summary"]["source_local_anchor_gap_count"] == 0


def test_source_wire_fallback_keeps_same_route_multiple_operations_ambiguous() -> None:
    gateway = RoutePublishedGateway(
        {
            "service": [
                _route_wire_node("service", value_node_id="wire-a", operation="Service.a", role="response", field_path="contexts"),
                _route_wire_node("service", value_node_id="wire-b", operation="Service.b", role="response", field_path="contexts"),
            ]
        },
        resolved_repos={"caller"},
    )
    result = build_interaction_lineage(
        _topology("contexts"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    assert _journey(result, "contexts")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_wire_fallback_is_case_sensitive() -> None:
    gateway = RoutePublishedGateway(
        {
            "service": [
                _route_wire_node(
                    "service",
                    value_node_id="wire-contexts",
                    operation="Service.start",
                    role="response",
                    field_path="Contexts",
                )
            ]
        },
        resolved_repos={"caller"},
    )
    result = build_interaction_lineage(
        _topology("contexts"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    assert _journey(result, "contexts")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_wire_fallback_requires_expected_interface_direction() -> None:
    gateway = RoutePublishedGateway(
        {
            "service": [
                _route_wire_node(
                    "service",
                    value_node_id="wire-contexts",
                    operation="Service.start",
                    role="response",
                    field_path="contexts",
                    interface_direction="inbound",
                )
            ]
        },
        resolved_repos={"caller"},
    )
    result = build_interaction_lineage(
        _topology("contexts"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("response",),
    )
    assert _journey(result, "contexts")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_counterpart_shape_terminal_requires_unique_route_interface() -> None:
    gateway = RoutePublishedGateway(
        {
            "caller": [
                _route_wire_node(
                    "caller", value_node_id="wire-a", operation="Client.call", role="request",
                    field_path="id", owner_ref="client-if-a"
                ),
                _route_wire_node(
                    "caller", value_node_id="wire-b", operation="Client.call", role="request",
                    field_path="other", owner_ref="client-if-b"
                ),
                _payload_local(value_node_id="payload-request", operation="Client.call", display_ref="payload", type_ref="RequestDto"),
            ]
        },
        resolved_repos={"service"},
    )
    result = build_interaction_lineage(
        _counterpart_request_topology("missing"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    assert _journey(result, "missing")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_counterpart_shape_can_terminate_at_unique_exact_route_payload_instance() -> None:
    gateway = RoutePublishedGateway(
        {
            "caller": [
                _route_wire_node("caller", value_node_id="wire-id", operation="Client.call", role="request", field_path="id"),
                _payload_local(value_node_id="payload-request", operation="Client.call", display_ref="payload", type_ref="RequestDto"),
            ]
        },
        resolved_repos={"service"},
    )
    result = build_interaction_lineage(
        _counterpart_request_topology("missing"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    journey = _journey(result, "missing")
    assert journey["source_side"]["anchor_status"] == "terminal"
    assert journey["source_side"]["resolved_anchor"]["value_node_id"] == "payload-request"
    assert journey["source_side"]["terminal_proof"]["operation"] == "Client.call"
    assert journey["source_side"]["anchor_selection_basis"] == (
        "topology_counterpart_shape_with_unique_published_payload_instance:resolved_terminal"
    )
    assert result["summary"]["source_local_anchor_gap_count"] == 0
    row = next(row for row in human_rows(result) if row["crossing_attribute"] == "missing")
    assert row["producer_attribute"] == ""
    assert row["gap"] == ""
    assert "caller: payload → missing" in row["full_attribute_path"]
    assert "[unresolved source]" not in row["full_attribute_path"]


def test_source_counterpart_shape_terminal_requires_exact_topology_basis() -> None:
    gateway = RoutePublishedGateway(
        {
            "caller": [
                _route_wire_node("caller", value_node_id="wire-id", operation="Client.call", role="request", field_path="id"),
                _payload_local(value_node_id="payload-request", operation="Client.call", display_ref="payload", type_ref="RequestDto"),
            ]
        },
        resolved_repos={"service"},
    )
    result = build_interaction_lineage(
        _request_topology("missing"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    assert _journey(result, "missing")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_counterpart_shape_terminal_requires_unique_route_operation() -> None:
    gateway = RoutePublishedGateway(
        {
            "caller": [
                _route_wire_node("caller", value_node_id="wire-a", operation="Client.a", role="request", field_path="id"),
                _route_wire_node("caller", value_node_id="wire-b", operation="Client.b", role="request", field_path="other"),
                _payload_local(value_node_id="payload-a", operation="Client.a", display_ref="payloadA", type_ref="RequestDto"),
                _payload_local(value_node_id="payload-b", operation="Client.b", display_ref="payloadB", type_ref="RequestDto"),
            ]
        },
        resolved_repos={"service"},
    )
    result = build_interaction_lineage(
        _counterpart_request_topology("missing"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    assert _journey(result, "missing")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1


def test_source_route_fallback_requires_complete_public_node_scan() -> None:
    gateway = RoutePublishedGateway(
        {
            "caller": [
                _route_wire_node("caller", value_node_id="wire-id", operation="Client.call", role="request", field_path="id"),
                _payload_local(value_node_id="payload-request", operation="Client.call", display_ref="payload", type_ref="RequestDto"),
            ]
        },
        resolved_repos={"service"},
        incomplete_repos={"caller"},
    )
    result = build_interaction_lineage(
        _counterpart_request_topology("missing"),
        edge_id=EDGE_ID,
        bindings=_bindings(),
        gateway=gateway,
        transport_roles=("request",),
    )
    assert _journey(result, "missing")["source_side"]["anchor_status"] == "unresolved"
    assert result["summary"]["source_local_anchor_gap_count"] == 1
