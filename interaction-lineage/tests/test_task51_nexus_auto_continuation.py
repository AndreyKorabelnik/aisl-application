"""Task 51: finite AISL-first continuation for newly discovered external boundaries."""
from __future__ import annotations

from copy import deepcopy

import aisl_interaction_lineage.prepare as preparation
from aisl_interaction_lineage.contracts import BindingIndex
from aisl_interaction_lineage.prepare import PreparationBudget, prepare_interaction_lineage
from test_builder import EDGE_ID, topology
from test_check_prepare import ReadinessGateway, _framework_result, _not_ready_with_requirement, bindings


def _second_boundary(first):
    other = deepcopy(first)
    demand = other["preparation_requirements"][0]
    demand["observed_boundary"]["boundary_path"] = "/nexus-mapper"
    demand["observed_boundary"]["observed_anchors"] = ["org.example.NextModel"]
    demand["preparation_group"]["boundary_path"] = "/nexus-mapper"
    demand["preparation_group"]["observed_anchors"] = ["org.example.NextModel"]
    demand["revision_id"] = "caller-rev-2"
    return other


def _ready():
    row = deepcopy(_not_ready_with_requirement())
    row.update(status="ready", preparation_requirements=[],
               repositories=[{"repository_id": "caller", "status": "ready"},
                             {"repository_id": "service", "status": "ready"}])
    return row


class RecordingKcp:
    def __init__(self):
        self.calls = []

    def run_preparation(self, request):
        self.calls.append(dict(request))
        result = _framework_result("prepared")
        result["final_readiness"]["knowledge_refs"][0]["revision_id"] = f"caller-rev-{len(self.calls) + 1}"
        return result


def _evaluate(monkeypatch, statuses, *, max_preparations):
    calls = iter(statuses)
    monkeypatch.setattr(preparation, "check_interaction_lineage", lambda *a, **kw: next(calls))
    kcp = RecordingKcp()
    events = []
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        readiness_gateway=ReadinessGateway(), preparation_gateway=kcp,
        budget=PreparationBudget(max_preparations, 4), progress=events.append,
    )
    return result, kcp, events


def test_new_external_boundary_triggers_next_nexus_preparation_without_manual_rerun(monkeypatch):
    first = _not_ready_with_requirement()
    second = _second_boundary(first)
    result, kcp, events = _evaluate(monkeypatch, [first, second, _ready()], max_preparations=3)
    assert result["status"] == "prepared"
    assert len(kcp.calls) == 2
    assert kcp.calls[0]["observed_boundary"]["boundary_path"] == "/external"
    assert kcp.calls[1]["observed_boundary"]["boundary_path"] == "/nexus-mapper"
    assert kcp.calls[1]["pinned_revision_context"]["caller"] == "caller-rev-2"
    assert result["summary"]["new_requirement_group_count"] == 1
    assert result["summary"]["framework_invocation_count"] == 2
    assert any(x["event"] == "preparation.readiness_rechecked" and x["new_group_count"] == 1 for x in events)


def test_budget_exhaustion_preserves_newly_discovered_dependency(monkeypatch):
    first = _not_ready_with_requirement()
    second = _second_boundary(first)
    result, kcp, events = _evaluate(monkeypatch, [first, second], max_preparations=1)
    assert result["status"] == "budget_exhausted"
    assert len(kcp.calls) == 1
    assert result["summary"]["deferred_group_count"] == 1
    assert result["deferred_groups"][0]["requirements"][0]["observed_boundary"]["boundary_path"] == "/nexus-mapper"
    assert any(x["event"] == "preparation.budget_exhausted" for x in events)


def test_new_revision_does_not_cause_duplicate_preparation_for_same_external_boundary(monkeypatch):
    first = _not_ready_with_requirement()
    unchanged = deepcopy(first)
    unchanged["preparation_requirements"][0]["revision_id"] = "caller-rev-99"
    result, kcp, events = _evaluate(monkeypatch, [first, unchanged], max_preparations=9)
    assert len(kcp.calls) == 1
    assert result["status"] == "no_progress"
    assert result["diagnostics"][0]["code"] == "preparation_no_new_supported_boundary"
    assert any(x["event"] == "preparation.readiness_rechecked" and x["new_group_count"] == 0 for x in events)


def test_no_kcp_calls_when_budget_is_zero_even_with_new_requirement(monkeypatch):
    first = _not_ready_with_requirement()
    result, kcp, events = _evaluate(monkeypatch, [first], max_preparations=0)
    assert result["status"] == "budget_exhausted"
    assert not kcp.calls
    assert len(result["deferred_groups"]) == 1


def test_kcp_step_limit_can_continue_only_with_new_observed_boundary(monkeypatch):
    first = _not_ready_with_requirement()
    second = _second_boundary(first)
    statuses = iter([first, second, _ready()])
    monkeypatch.setattr(preparation, "check_interaction_lineage", lambda *a, **kw: next(statuses))

    class LimitedKcp(RecordingKcp):
        def run_preparation(self, request):
            result = super().run_preparation(request)
            if len(self.calls) == 1:
                result["outcome"] = "step_limit"
            return result

    kcp = LimitedKcp()
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        readiness_gateway=ReadinessGateway(), preparation_gateway=kcp,
        budget=PreparationBudget(3, 2),
    )
    assert len(kcp.calls) == 2
    assert result["status"] == "prepared"  # final public knowledge is READY


def test_independent_maven_revision_is_reported_but_not_falsely_bound_as_root(monkeypatch):
    first = _not_ready_with_requirement()
    states = iter([first, _ready()])
    monkeypatch.setattr(preparation, "check_interaction_lineage", lambda *a, **kw: next(states))

    class Kcp(RecordingKcp):
        def run_preparation(self, request):
            result = super().run_preparation(request)
            result["final_readiness"]["knowledge_refs"].append({
                "repository_id": "maven:g:a:2", "system_id": "maven-sys",
                "revision_id": "published-revision-2",
            })
            return result

    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        readiness_gateway=ReadinessGateway(), preparation_gateway=Kcp(),
        budget=PreparationBudget(2, 2),
    )
    assert result["status"] == "prepared"
    assert result["published_dependency_revisions"] == [{
        "repository_id": "maven:g:a:2", "system_id": "maven-sys",
        "revision_id": "published-revision-2",
    }]
    assert "maven:g:a:2" not in {row["repository_id"] for row in result["bindings"]["repositories"]}
