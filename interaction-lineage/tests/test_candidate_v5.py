"""Topology v5 contract gates: candidate evidence is not a transport proof."""
from __future__ import annotations

import json
from pathlib import Path

from aisl_interaction_lineage.builder import build_interaction_lineage
from aisl_interaction_lineage.checker import check_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
from aisl_interaction_lineage.prepare import prepare_interaction_lineage
from aisl_interaction_lineage.topology import boundary_fields, validate_topology

from test_check_prepare import ReadinessGateway
from test_builder import FakeGateway

EDGE_ID = "candidate-1"


def candidate_topology(*, include_fields=True):
    return {
        "format": "repository-topology/v5",
        "topology_id": "realistic-candidate",
        "edges": [{
            "edge_id": EDGE_ID, "status": "candidate", "protocol": "http", "method": "POST",
            "matched_identity": "/foo", "source_repository_id": "caller",
            "target_repository_id": "service", "basis": [{"kind": "http_method_path", "value": "POST /foo"}],
            "source_half_wires": [{
                "repository_id": "caller", "direction": "outbound",
                "interface_id": "client-if", "method": "POST", "identities": ["/foo"],
                "request_field_names": []
            }],
            "target_half_wires": [{
                "repository_id": "service", "direction": "inbound",
                "interface_id": "server-if", "method": "POST", "identities": ["/foo"],
                "request_field_names": ["clientId"] if include_fields else []
            }],
        }],
    }


def bindings():
    return BindingIndex([AislBinding("caller", "cs", "rev-c"), AislBinding("service", "ss", "rev-s")])


def test_v5_uses_observed_fields_as_probes_not_confirmed_crossings():
    payload=candidate_topology()
    validate_topology(payload)
    fields=boundary_fields(payload["edges"][0], transport_role="request")
    assert [(f.field_path,f.source_repository_id,f.target_repository_id) for f in fields]==[("clientId","caller","service")]
    assert all(f.topology_basis=="inventory_observed_candidate_field" for f in fields)
    result=build_interaction_lineage(payload,edge_id=EDGE_ID,bindings=bindings(),gateway=FakeGateway(),transport_roles=("request",))
    assert result["edge"]["status"]=="candidate"
    assert result["summary"]["resolved_crossing_count"]==0
    assert result["journeys"][0]["crossing"]["status"]=="candidate"
    assert any(g["reason"]=="candidate_transport_crossing_unverified" for g in result["gaps"])


def test_v5_no_observed_fields_is_explicit_non_ready_not_empty_success():
    payload=candidate_topology(include_fields=False)
    result=check_interaction_lineage(payload,edge_id=EDGE_ID,bindings=bindings(),gateway=ReadinessGateway())
    assert result["status"]=="not_ready"
    assert result["summary"]["repository_count"]==2
    assert len([d for d in result["diagnostics"] if d["code"]=="candidate_fields_not_observed"])==2
    build=build_interaction_lineage(payload,edge_id=EDGE_ID,bindings=bindings(),gateway=FakeGateway())
    assert build["summary"]["journey_count"]==0
    assert {g["transport_role"] for g in build["gaps"] if g["reason"]=="candidate_fields_not_observed"}=={"request","response"}


def test_v5_no_observed_fields_does_not_trigger_unnecessary_framework_prepare():
    class Guard:
        def run_preparation(self, payload):
            raise AssertionError("must not prepare already-published unrelated source without a field anchor")
    result=prepare_interaction_lineage(
        candidate_topology(include_fields=False),edge_id=EDGE_ID,
        bindings=bindings(),readiness_gateway=ReadinessGateway(),preparation_gateway=Guard()
    )
    assert result["status"]=="blocked"
    assert result["summary"]["framework_invocation_count"]==0


def test_v4_is_rejected_without_compatibility_adapter():
    payload=candidate_topology()
    payload["format"]="repository-topology/v4"
    try:
        validate_topology(payload)
    except ValueError as exc:
        assert "repository-topology/v5" in str(exc)
    else:
        raise AssertionError("legacy contract must not be accepted")


def test_batch_check_covers_every_edge_without_calling_kcp(monkeypatch, tmp_path):
    import aisl_interaction_lineage.cli as cli
    payload = candidate_topology(include_fields=False)
    other = dict(payload["edges"][0]); other["edge_id"] = "candidate-2"
    payload["edges"].append(other)
    topology_path=tmp_path/"topology.json";topology_path.write_text(json.dumps(payload))
    bindings_path=tmp_path/"bindings.json";bindings_path.write_text(json.dumps({
        "schema_version": "interaction-lineage-aisl-bindings/v1",
        "repositories": [row.to_dict() for row in bindings().all()],
    }))
    output=tmp_path/"result.json"

    class Gateway(ReadinessGateway):
        def __init__(self, *_args, **_kwargs):super().__init__()
        def close(self):pass

    monkeypatch.setattr(cli,"KnowledgeApiGateway",Gateway)
    monkeypatch.setattr(cli,"KnowledgeControlPlaneGateway",lambda *_: (_ for _ in ()).throw(AssertionError("KCP invoked by check")))
    code=cli.main(["check","--topology",str(topology_path),"--all-edges","--bindings",str(bindings_path),"--aisl-base-url","http://unused","--output",str(output)])
    result=json.loads(output.read_text())
    assert code==2
    assert result["summary"]["candidate_edge_count"]==2
    assert result["summary"]["processed_edge_count"]==2
    assert [row["edge_id"] for row in result["edges"]]==["candidate-1","candidate-2"]
    assert all(row["result"]["status"]=="not_ready" for row in result["edges"])


def test_batch_prepare_reuses_pinned_bindings_across_candidate_edges(monkeypatch,tmp_path):
    import aisl_interaction_lineage.cli as cli
    payload=candidate_topology()
    payload["edges"].append({**payload["edges"][0],"edge_id":"candidate-2"})
    p=tmp_path/"topology.json";p.write_text(json.dumps(payload))
    o=tmp_path/"out.json"
    observed=[]
    class Gateway:
        def __init__(self,*a):pass
        def close(self):pass
    def prepare(*a,edge_id,bindings,**kw):
        observed.append((edge_id,bindings.find("caller").revision_id if bindings.find("caller") else None))
        return {
            "status":"prepared","summary":{"framework_invocation_count":1},
            "bindings":{"repositories":[{
                "repository_id":"caller", "system_id":"cs",
                "revision_id":"rev-updated"
            }]},
        }
    monkeypatch.setattr(cli,"KnowledgeApiGateway",Gateway)
    monkeypatch.setattr(cli,"KnowledgeControlPlaneGateway",lambda *a:object())
    monkeypatch.setattr(cli,"prepare_interaction_lineage",prepare)
    assert cli.main(["prepare","--topology",str(p),"--all-edges","--aisl-base-url","http://unused","--kcp-base-url","http://unused","--output",str(o)])==2  # missing immutable Topology source identity is now reported
    assert observed==[("candidate-1",None),("candidate-2","rev-updated")]
    out=json.loads(o.read_text())
    assert out["summary"]["candidate_edge_count"]==2
    assert out["bindings"]["repositories"][0]["revision_id"]=="rev-updated"


def test_v5_inventory_fingerprint_does_not_block_published_knowledge():
    payload = candidate_topology()
    payload["inputs"] = [
        {"repository_id": repo, "source_snapshot_fingerprint": "a" * 64}
        for repo in ("caller", "service")
    ]
    gateway = ReadinessGateway(revision_status={
        repo: {
            "status": "ready", "available_tools": ["resolve_attribute_path"],
            # Intentionally same-looking SHA in a different provenance domain.
            "metadata": {"source_snapshot_fingerprint": "a" * 64},
        }
        for repo in ("caller", "service")
    })
    result = check_interaction_lineage(
        payload, edge_id=EDGE_ID, bindings=bindings(), gateway=gateway,
        transport_roles=("request",),
    )
    assert result["status"] == "ready"
    assert {row["status"] for row in result["repositories"]} == {"ready"}
    assert not [d for d in result["diagnostics"] if d["code"] == "source_revision_unverified"]
    # Readiness of local evidence never converts the candidate crossing to proof.
    build = build_interaction_lineage(
        payload, edge_id=EDGE_ID, bindings=bindings(), gateway=FakeGateway(),
        transport_roles=("request",),
    )
    assert build["edge"]["status"] == "candidate"
    assert build["summary"]["resolved_crossing_count"] == 0


def test_v5_missing_binding_invokes_existing_kcp_preparation_without_git_gate():
    payload = candidate_topology()
    payload["inputs"] = [
        {"repository_id": repo, "source_snapshot_fingerprint": "d" * 64}
        for repo in ("caller", "service")
    ]
    calls = []
    class Kcp:
        def run_preparation(self, request):
            calls.append(dict(request))
            repo = request["observed_boundary"]["repository_id"]
            return {
                "outcome": "prepared",
                "final_readiness": {"knowledge_refs": [{
                    "repository_id": repo, "system_id": repo + "-system",
                    "revision_id": "rev-" + repo,
                }]},
            }
    result = prepare_interaction_lineage(
        payload, edge_id=EDGE_ID, bindings=BindingIndex([]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=Kcp(),
        transport_roles=("request",),
    )
    assert len(calls) == 2
    assert {x["observed_boundary"]["repository_id"] for x in calls} == {"caller", "service"}
    assert all(x["product_ids"] == ["attribute-lineage"] and x["execution_scope"] == "workspace" for x in calls)
    assert result["status"] == "prepared"
    assert result["summary"]["framework_invocation_count"] == 2


def test_v5_batch_build_is_not_blocked_by_unrelated_inventory_fingerprint(monkeypatch, tmp_path):
    import aisl_interaction_lineage.cli as cli
    payload = candidate_topology()
    payload["inputs"] = [
        {"repository_id": repo, "source_snapshot_fingerprint": "d" * 64}
        for repo in ("caller", "service")
    ]
    topology_path = tmp_path / "topology.json"
    topology_path.write_text(json.dumps(payload))
    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_text(json.dumps({
        "schema_version": "interaction-lineage-aisl-bindings/v1",
        "repositories": [row.to_dict() for row in bindings().all()],
    }))
    output = tmp_path / "out.json"
    class Gateway(ReadinessGateway):
        def __init__(self, *_a, **_kw): super().__init__()
        def close(self): pass
    calls = []
    def fake_build(_topology, *, edge_id, **_kwargs):
        calls.append(edge_id)
        return {"status": "candidate", "edge_id": edge_id}
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "build_interaction_lineage", fake_build)
    assert cli.main([
        "build", "--topology", str(topology_path), "--all-edges",
        "--bindings", str(bindings_path), "--aisl-base-url", "http://unused",
        "--transport-role", "request", "--output", str(output),
    ]) == 0
    rows = json.loads(output.read_text())
    assert calls == [EDGE_ID]
    assert rows["summary"]["processed_edge_count"] == 1
    assert rows["edges"][0]["result"]["status"] == "candidate"
