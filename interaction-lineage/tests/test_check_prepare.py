from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from aisl_interaction_lineage.checker import _external_client_boundary_requirement, check_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
import aisl_interaction_lineage.prepare as prepare_mod
from aisl_interaction_lineage.prepare import prepare_interaction_lineage

from test_builder import EDGE_ID, topology


class ReadinessGateway:
    def __init__(
        self,
        *,
        revision_status: Mapping[str, Mapping[str, Any]] | None = None,
        missing_anchors: set[tuple[str, str]] | None = None,
    ) -> None:
        self._revision_status = dict(revision_status or {})
        self.missing_anchors = missing_anchors or set()

    def revision_status(self, binding: AislBinding) -> Mapping[str, Any]:
        return self._revision_status.get(
            binding.repository_id,
            {
                "status": "ready",
                "capabilities": ["workspace.attribute-path-resolver"],
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
            },
        )

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        if (repo, source) in self.missing_anchors:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        node = {
            "repo_id": repo,
            "owner_ref": "service-if" if repo == "service" else "caller-if",
            "value_node_id": f"{repo}:{source}",
            "display_ref": source,
        }
        return {"result": {"status": "confirmed_complete", "source": node, "paths": []}}

    def list_repository_value_nodes(
        self, binding: AislBinding, *, repository_id: str, node_kind: str | None = None,
        operation: str | None = None, max_results: int = 500, page_token: str = "",
    ) -> Mapping[str, Any]:
        return {"result": {"items": [], "total_count": 0, "returned_count": 0, "truncated": False}}


def bindings() -> BindingIndex:
    return BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev"),
        AislBinding("service", "service-system", "service-rev"),
    ])


def test_check_ready_requires_revision_capability_and_boundary_anchors() -> None:
    result = check_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=ReadinessGateway())
    assert result["status"] == "ready"
    assert result["summary"] == {
        "repository_count": 2,
        "ready_repository_count": 2,
        "not_ready_repository_count": 0,
    }
    assert all(item["boundary_anchor_missing_count"] == 0 for item in result["repositories"])


def test_check_missing_binding_is_machine_readable() -> None:
    result = check_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=BindingIndex([AislBinding("caller", "caller-system", "caller-rev")]),
        gateway=ReadinessGateway(),
    )
    assert result["status"] == "not_ready"
    service = next(item for item in result["repositories"] if item["repository_id"] == "service")
    assert service["status"] == "missing_binding"
    assert any(item["code"] == "repository_resolution_failed" for item in result["diagnostics"])


def test_check_missing_capability_is_not_ready() -> None:
    result = check_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        gateway=ReadinessGateway(revision_status={"service": {"status": "ready", "capabilities": []}}),
    )
    service = next(item for item in result["repositories"] if item["repository_id"] == "service")
    assert service["status"] == "missing_required_capability"
    assert result["status"] == "not_ready"


def test_check_server_unavailable_is_not_ready_without_fallback() -> None:
    result = check_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        gateway=ReadinessGateway(revision_status={"caller": {"status": "server_unavailable", "diagnostic": "offline"}}),
    )
    caller = next(item for item in result["repositories"] if item["repository_id"] == "caller")
    assert caller["status"] == "server_unavailable"
    assert any(item["code"] == "server_unavailable" for item in result["diagnostics"])


def test_check_missing_local_anchor_is_non_blocking_coverage_gap() -> None:
    gateway = ReadinessGateway(missing_anchors={("caller", "HTTP response profile.id"), ("caller", "profile.id")})
    result = check_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway)
    caller = next(item for item in result["repositories"] if item["repository_id"] == "caller")
    assert caller["status"] == "ready"
    assert result["status"] == "ready"
    assert any(item["code"] == "local_anchor_gap" and item["blocking"] is False for item in result["diagnostics"])


class FakePreparationGateway:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self.result = dict(result)
        self.calls: list[dict[str, Any]] = []

    def run_preparation(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(dict(payload))
        return dict(self.result)


def _external_requirement() -> dict[str, Any]:
    return {
        "state": "needs_external_source",
        "repository_id": "caller",
        "system_id": "caller-system",
        "revision_id": "caller-rev",
        "edge_id": EDGE_ID,
        "transport_role": "response",
        "field_path": "profile.id",
        "side": "target",
        "direction": "forward",
        "observed_boundary": {
            "repository_id": "caller",
            "system_id": "caller-system",
            "boundary_kind": "rest",
            "boundary_direction": "inbound",
            "interaction_direction": "outbound",
            "payload_role": "response",
            "boundary_path": "/external",
            "observed_anchors": ["ExternalProfile"],
            "terminal_value_node_id": "boundary-a",
            "terminal_repo_id": "caller",
        },
        "selector_context": {
            "repository_id": "caller",
            "system_id": "caller-system",
            "attribute_path": {
                "repository_id": "caller",
                "system_id": "caller-system",
                "revision_id": "caller-rev",
                "source": "caller-source-node",
                "selected_repo_ids": ["caller"],
                "direction": "forward",
            },
        },
        "preparation_group": {
            "repository_id": "caller",
            "system_id": "caller-system",
            "boundary_path": "/external",
            "payload_type": "ExternalProfile",
            "observed_anchors": ["ExternalProfile"],
        },
    }


def _not_ready_with_requirement() -> dict[str, Any]:
    return {
        "format": "interaction-lineage-readiness/v1",
        "status": "not_ready",
        "topology_id": "topology-test",
        "edge_id": EDGE_ID,
        "repositories": [
            {"repository_id": "caller", "status": "preparable_external_boundary"},
            {"repository_id": "service", "status": "ready"},
        ],
        "preparation_requirements": [_external_requirement()],
        "diagnostics": [],
        "summary": {
            "repository_count": 2,
            "ready_repository_count": 1,
            "not_ready_repository_count": 1,
        },
    }


def _framework_result(outcome: str = "resolved_terminal") -> dict[str, Any]:
    return {
        "schema_version": "framework_preparation_result/v1",
        "outcome": outcome,
        "initial_readiness": {
            "state": "needs_external_source",
            "progress_identity": "p1",
            "diagnostics": [],
            "preparation_context": {},
            "knowledge_refs": [],
        },
        "final_readiness": {
            "state": "resolved_terminal" if outcome == "resolved_terminal" else outcome,
            "progress_identity": "p3",
            "diagnostics": [],
            "preparation_context": {},
            "knowledge_refs": [{
                "repository_id": "caller",
                "system_id": "caller-system",
                "revision_id": "caller-rev-2",
            }],
        },
        "steps": [
            {
                "step_id": "job-a",
                "status": "published",
                "publication_refs": [],
                "source_provenance_refs": [{"source_kind": "external-source"}],
                "diagnostics": [],
            },
        ],
        "diagnostics": [],
    }


def test_external_client_boundary_requirement_is_mechanical_and_request_response_symmetric() -> None:
    node = {
        "value_node_id": "terminal",
        "repo_id": "caller",
        "type_ref": "ExternalProfile",
        "boundary": {
            "boundary_direction": "inbound",
            "interaction_direction": "outbound",
            "payload_role": "response",
            "boundary_kind": "rest",
            "boundary_path": "/external",
            "payload_type": "ExternalProfile",
            "field_binding_kind": "rest_response_observed_getter_property",
        },
    }
    resolved = {
        "resolved_anchor": {"value_node_id": "source"},
        "query": {"result": {
            "status": "partial",
            "source": {"value_node_id": "source"},
            "gaps": [{"reason": "no_observed_outgoing_value_flow", "node": node}],
        }},
    }
    response = _external_client_boundary_requirement(
        resolved=resolved,
        repository_id="caller",
        system_id="caller-system",
        revision_id="caller-rev",
        edge_id=EDGE_ID,
        transport_role="response",
        field_path="profile.id",
        side="target",
        direction="forward",
    )
    assert response is not None
    assert response["state"] == "needs_external_source"
    assert response["observed_boundary"]["observed_anchors"] == ["ExternalProfile"]

    request_node = {
        **node,
        "boundary": {
            **node["boundary"],
            "payload_role": "request",
            "boundary_direction": "outbound",
            "field_binding_kind": "rest_request_observed_field",
        },
    }
    resolved["query"]["result"]["gaps"] = [{
        "reason": "no_observed_outgoing_value_flow",
        "node": request_node,
    }]
    request_requirement = _external_client_boundary_requirement(
        resolved=resolved,
        repository_id="caller",
        system_id="caller-system",
        revision_id="caller-rev",
        edge_id=EDGE_ID,
        transport_role="request",
        field_path="profile.id",
        side="source",
        direction="forward",
    )
    assert request_requirement is not None
    assert request_requirement["observed_boundary"]["payload_role"] == "request"

    server_side = {
        **node,
        "boundary": {**node["boundary"], "interaction_direction": "inbound"},
    }
    resolved["query"]["result"]["gaps"] = [{
        "reason": "no_observed_outgoing_value_flow",
        "node": server_side,
    }]
    assert _external_client_boundary_requirement(
        resolved=resolved,
        repository_id="caller",
        system_id="caller-system",
        revision_id="caller-rev",
        edge_id=EDGE_ID,
        transport_role="response",
        field_path="profile.id",
        side="target",
        direction="forward",
    ) is None


def test_prepare_is_noop_when_all_repositories_are_ready() -> None:
    prep = FakePreparationGateway(_framework_result())
    result = prepare_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        readiness_gateway=ReadinessGateway(),
        preparation_gateway=prep,
    )
    assert result["status"] == "already_prepared"
    assert prep.calls == []


def test_prepare_delegates_one_external_group_to_framework_and_pins_revision(monkeypatch) -> None:
    before = _not_ready_with_requirement()
    after = {
        **before,
        "status": "ready",
        "repositories": [
            {"repository_id": "caller", "status": "ready"},
            {"repository_id": "service", "status": "ready"},
        ],
        "preparation_requirements": [],
        "summary": {
            "repository_count": 2,
            "ready_repository_count": 2,
            "not_ready_repository_count": 0,
        },
    }
    calls = iter([before, after])
    monkeypatch.setattr(prepare_mod, "check_interaction_lineage", lambda *args, **kwargs: next(calls))
    prep = FakePreparationGateway(_framework_result())
    result = prepare_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        readiness_gateway=ReadinessGateway(),
        preparation_gateway=prep,
    )
    assert result["status"] == "prepared"
    assert len(prep.calls) == 1
    request = prep.calls[0]
    assert request["consumer_id"] == "interaction-lineage"
    assert "nexus" not in str(request).lower()
    pinned = {item["repository_id"]: item for item in result["bindings"]["repositories"]}
    assert pinned["caller"]["revision_id"] == "caller-rev-2"
    assert pinned["service"]["revision_id"] == "service-rev"


def test_prepare_no_progress_does_not_retry_in_application(monkeypatch) -> None:
    monkeypatch.setattr(
        prepare_mod,
        "check_interaction_lineage",
        lambda *args, **kwargs: _not_ready_with_requirement(),
    )
    result_payload = _framework_result("no_progress")
    result_payload["final_readiness"]["knowledge_refs"] = []
    prep = FakePreparationGateway(result_payload)
    result = prepare_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=bindings(),
        readiness_gateway=ReadinessGateway(),
        preparation_gateway=prep,
    )
    assert result["status"] == "no_progress"
    assert len(prep.calls) == 1


def test_prepare_missing_bindings_become_generic_repository_demands(monkeypatch) -> None:
    before = {
        "format": "interaction-lineage-readiness/v1",
        "status": "not_ready",
        "topology_id": "topology-test",
        "edge_id": EDGE_ID,
        "repositories": [
            {"repository_id": "caller", "status": "missing_binding"},
            {"repository_id": "service", "status": "missing_binding"},
        ],
        "preparation_requirements": [],
        "diagnostics": [],
        "summary": {
            "repository_count": 2,
            "ready_repository_count": 0,
            "not_ready_repository_count": 2,
        },
    }
    after = {
        **before,
        "status": "ready",
        "repositories": [
            {"repository_id": "caller", "status": "ready"},
            {"repository_id": "service", "status": "ready"},
        ],
        "summary": {
            "repository_count": 2,
            "ready_repository_count": 2,
            "not_ready_repository_count": 0,
        },
    }
    calls = iter([before, after])
    monkeypatch.setattr(prepare_mod, "check_interaction_lineage", lambda *args, **kwargs: next(calls))

    results = []
    for repository_id in ("caller", "service"):
        payload = _framework_result("prepared")
        payload["final_readiness"]["state"] = "ready"
        payload["final_readiness"]["knowledge_refs"] = [{
            "repository_id": repository_id,
            "system_id": repository_id,
            "revision_id": f"rev-{repository_id}",
        }]
        results.append(payload)

    class SequenceGateway:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def run_preparation(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
            self.calls.append(dict(payload))
            return results[len(self.calls) - 1]

    gateway = SequenceGateway()
    result = prepare_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=BindingIndex([]),
        readiness_gateway=ReadinessGateway(),
        preparation_gateway=gateway,
    )
    assert result["status"] == "prepared"
    assert len(gateway.calls) == 2
    assert {call["observed_boundary"]["repository_id"] for call in gateway.calls} == {"caller", "service"}
    assert all("nexus" not in str(call).lower() for call in gateway.calls)
    assert {item["repository_id"] for item in result["bindings"]["repositories"]} == {"caller", "service"}
