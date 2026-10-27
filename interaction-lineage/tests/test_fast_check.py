"""Cheap admission must never masquerade as producer-evidence validation."""
from __future__ import annotations

import json

import aisl_interaction_lineage.cli as cli
from aisl_interaction_lineage.checker import check_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex

from test_candidate_v5 import candidate_topology
from test_check_prepare import ReadinessGateway


def _bindings() -> BindingIndex:
    return BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev"),
        AislBinding("service", "service-system", "service-rev"),
    ])


class NoPathGateway(ReadinessGateway):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_calls = 0
    def revision_status(self, binding):
        self.status_calls += 1
        return super().revision_status(binding)
    def resolve_attribute_paths(self, *args, **kwargs):
        raise AssertionError("cheap check must not resolve paths")
    def list_repository_value_nodes(self, *args, **kwargs):
        raise AssertionError("cheap check must not read node catalog")
    def close(self):
        pass


def test_fast_check_declares_unverified_field_anchors_without_path_queries():
    gateway = NoPathGateway()
    out = check_interaction_lineage(
        candidate_topology(), edge_id="candidate-1", bindings=_bindings(),
        gateway=gateway, prerequisites_only=True, transport_roles=("request",),
    )
    assert gateway.status_calls == 2
    assert out["status"] == "prerequisites_satisfied"
    assert out["readiness_scope"] == "repository_revision_tools_only"
    assert out["summary"]["attribute_path_resolution"] == "deferred"
    assert out["preparation_requirements"] == []
    assert all("boundary_anchor_count" not in row for row in out["repositories"])
    assert {d["code"] for d in out["diagnostics"]} == {"attribute_path_resolution_deferred"}
    assert out["topology_edge_status"] == "candidate"


def test_fast_check_retains_missing_binding_capability_server_diagnostics():
    gateway = NoPathGateway(revision_status={
        "caller": {"status": "server_unavailable", "diagnostic": "network error"},
    })
    out = check_interaction_lineage(
        candidate_topology(), edge_id="candidate-1",
        bindings=BindingIndex([AislBinding("caller", "cs", "rev")]),
        gateway=gateway, prerequisites_only=True, transport_roles=("request",),
    )
    assert out["status"] == "not_ready"
    assert {d["code"] for d in out["diagnostics"]} >= {
        "server_unavailable", "repository_resolution_failed", "attribute_path_resolution_deferred",
    }
    out = check_interaction_lineage(
        candidate_topology(), edge_id="candidate-1", bindings=_bindings(),
        gateway=NoPathGateway(revision_status={"service": {"status": "ready", "available_tools": []}}),
        prerequisites_only=True, transport_roles=("request",),
    )
    assert out["status"] == "not_ready"
    assert any(d["code"] == "required_revision_tool_missing" for d in out["diagnostics"])


def test_fast_check_retains_missing_field_probe_and_does_not_infer_absence_of_anchors():
    out = check_interaction_lineage(
        candidate_topology(include_fields=False), edge_id="candidate-1",
        bindings=_bindings(), gateway=NoPathGateway(), prerequisites_only=True,
    )
    assert out["status"] == "not_ready"
    assert {d["transport_role"] for d in out["diagnostics"]
            if d["code"] == "candidate_fields_not_observed"} == {"request", "response"}
    assert not any(d["code"] == "local_anchor_gap" for d in out["diagnostics"])


def test_cli_defaults_fast_and_deep_is_explicit(tmp_path, monkeypatch):
    class CountGateway(ReadinessGateway):
        requests = []
        def __init__(self, *_args):
            super().__init__()
        def close(self):
            pass
        def revision_status(self, binding):
            self.requests.append("revision_status")
            return super().revision_status(binding)
        def resolve_attribute_paths(self, *args, **kwargs):
            self.requests.append("resolve_attribute_paths")
            return super().resolve_attribute_paths(*args, **kwargs)
        def list_repository_value_nodes(self, *args, **kwargs):
            self.requests.append("list_repository_value_nodes")
            return super().list_repository_value_nodes(*args, **kwargs)

    monkeypatch.setattr(cli, "KnowledgeApiGateway", CountGateway)
    topology_file = tmp_path / "topology.json"
    topology_file.write_text(json.dumps(candidate_topology()), encoding="utf8")
    bindings_file = tmp_path / "bindings.json"
    bindings_file.write_text(json.dumps({
        "schema_version": "interaction-lineage-aisl-bindings/v1",
        "repositories": [r.to_dict() for r in _bindings().all()],
    }), encoding="utf8")
    output = tmp_path / "out.json"
    args = ["check", "--topology", str(topology_file), "--edge-id", "candidate-1",
            "--bindings", str(bindings_file), "--aisl-base-url", "http://unused", "--output", str(output)]
    assert cli.main(args) == 2  # response role has no observed fields
    shallow = json.loads(output.read_text())
    assert shallow["readiness_scope"] == "repository_revision_tools_only"
    assert shallow["status"] == "not_ready"
    assert "resolve_attribute_paths" not in CountGateway.requests
    assert CountGateway.requests.count("revision_status") == 2
    CountGateway.requests.clear()
    assert cli.main(args + ["--deep"]) == 2
    deep = json.loads(output.read_text())
    assert "readiness_scope" not in deep
    assert "resolve_attribute_paths" in CountGateway.requests


def test_cli_fast_success_is_explicitly_provisional(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "KnowledgeApiGateway", lambda *_: NoPathGateway())
    payload = candidate_topology()
    payload["edges"][0]["target_half_wires"][0]["response_field_names"] = ["status"]
    p = tmp_path / "topology.json"; p.write_text(json.dumps(payload))
    b = tmp_path / "bindings.json"; b.write_text(json.dumps({
        "schema_version":"interaction-lineage-aisl-bindings/v1",
        "repositories":[x.to_dict() for x in _bindings().all()],
    }))
    out = tmp_path / "check.json"
    assert cli.main(["check", "--topology", str(p), "--edge-id", "candidate-1",
                    "--bindings", str(b), "--aisl-base-url", "http://unused", "--output", str(out)]) == 0
    result=json.loads(out.read_text())
    assert result["status"]=="prerequisites_satisfied"
    assert result["topology_edge_status"]=="candidate"
    assert result["summary"]["attribute_path_resolution"]=="deferred"
