from __future__ import annotations

import json
from pathlib import Path

import aisl_interaction_lineage.cli as cli_mod
import aisl_interaction_lineage.prepare as prep_mod
from aisl_interaction_lineage.contracts import BindingIndex
from aisl_interaction_lineage.prepare import PreparationBudget, prepare_interaction_lineage
from test_builder import EDGE_ID, topology
from test_check_prepare import _framework_result, _not_ready_with_requirement, ReadinessGateway


def _two_groups():
    first = _not_ready_with_requirement()
    second = dict(first["preparation_requirements"][0])
    second["field_path"] = "profile.other"
    second["preparation_group"] = {"repository_id": "service", "boundary_path": "/different"}
    first["preparation_requirements"] = [*first["preparation_requirements"], second]
    return first


class RecordingPreparation:
    def __init__(self):
        self.calls = []

    def run_preparation(self, payload):
        self.calls.append(dict(payload))
        result = _framework_result("no_progress")
        result["final_readiness"]["knowledge_refs"] = []
        return result


def test_budget_one_preparation_keeps_deferred_and_pins_server_max_steps(monkeypatch):
    monkeypatch.setattr(prep_mod, "check_interaction_lineage", lambda *a, **kw: _two_groups())
    sink = []
    gateway = RecordingPreparation()
    budget = PreparationBudget(1, 1)
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=gateway,
        budget=budget, progress=sink.append,
    )
    assert result["status"] == "no_progress"
    assert result["summary"]["framework_invocation_count"] == 1
    assert result["summary"]["deferred_group_count"] >= 1
    assert len(gateway.calls) == 1 and gateway.calls[0]["max_steps"] == 1
    assert gateway.calls[0]["product_ids"] == ["attribute-lineage"] and gateway.calls[0]["execution_scope"] == "workspace"
    assert any(event["event"] == "preparation.started" for event in sink)
    assert not any(event["event"] == "preparation.budget_exhausted" for event in sink)
    assert all(row["reason"] == "previous_preparation_stopped" for row in result["deferred_groups"])


def test_zero_budget_cannot_call_kcp(monkeypatch):
    monkeypatch.setattr(prep_mod, "check_interaction_lineage", lambda *a, **kw: _two_groups())
    gateway = RecordingPreparation()
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=gateway,
        budget=PreparationBudget(0, 1),
    )
    assert result["status"] == "budget_exhausted"
    assert not gateway.calls
    assert result["summary"]["deferred_group_count"] == 2


def test_budget_rejects_invalid_step_count():
    import pytest
    with pytest.raises(ValueError, match="1, 32"):
        PreparationBudget(1, 33)
    with pytest.raises(ValueError, match="negative"):
        PreparationBudget(-1, 1)


def test_cli_budget_shared_across_candidates(monkeypatch, tmp_path: Path):
    item = topology()
    second = dict(item["edges"][0])
    second["edge_id"] = "second-candidate"
    item["edges"] = [*item["edges"], second]
    input_path = tmp_path / "topology.json"
    input_path.write_text(json.dumps(item), encoding="utf-8")
    output = tmp_path / "output.json"
    events_path = tmp_path / "progress.jsonl"
    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_text(json.dumps({"schema_version": "interaction-lineage-aisl-bindings/v1", "repositories": []}))
    monkeypatch.setattr(prep_mod, "check_interaction_lineage", lambda *a, **kw: _two_groups())

    class Aisl:
        def __init__(self, *_a, **_kw): pass
        def close(self): pass

    gateway = RecordingPreparation()
    monkeypatch.setattr(cli_mod, "KnowledgeApiGateway", Aisl)
    monkeypatch.setattr(cli_mod, "KnowledgeControlPlaneGateway", lambda *_a, **_kw: gateway)
    code = cli_mod.main([
        "prepare", "--topology", str(input_path), "--all-edges", "--bindings", str(bindings_path),
        "--aisl-base-url", "http://aisl", "--kcp-base-url", "http://kcp", "--output", str(output),
        "--max-preparations", "1", "--max-kcp-steps", "1", "--progress-jsonl", str(events_path),
    ])
    assert code == 2
    result = json.loads(output.read_text())
    assert result["summary"]["candidate_edge_count"] == 2
    assert result["summary"]["framework_invocation_count"] == 1
    assert result["summary"]["deferred_group_count"] >= 3
    assert len(gateway.calls) == 1
    assert len(events_path.read_text().splitlines()) >= 3
