"""Contract regression: revision-scoped tools and direct KCP product selection."""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from aisl_interaction_lineage.aisl import KnowledgeApiGateway
from aisl_interaction_lineage.contracts import AislBinding
from aisl_interaction_lineage.prepare import PreparationBudget, prepare_interaction_lineage
from test_builder import EDGE_ID, topology
from test_check_prepare import ReadinessGateway, _framework_result
from aisl_interaction_lineage.contracts import BindingIndex


def _sdk_shim(monkeypatch):
    mod = ModuleType("aisl_sdk")
    class ApiError(Exception):
        status_code = 404
    class ContractError(Exception):
        pass
    class TransportError(Exception):
        pass
    mod.AislApiError = ApiError
    mod.AislContractError = ContractError
    mod.AislTransportError = TransportError
    monkeypatch.setitem(sys.modules, "aisl_sdk", mod)
    return ContractError


def test_revision_status_reads_pinned_tools_not_removed_capabilities(monkeypatch):
    _sdk_shim(monkeypatch)
    seen = []
    class Pinned:
        system_id = "demo"
        revision_id = "rev-pinned"
        def revision_tools(self):
            seen.append("revision-tools")
            return SimpleNamespace(tools=[{"name": "resolve_attribute_path"}, {"name": "list_revisions"}])
    gateway = object.__new__(KnowledgeApiGateway)
    gateway._client = SimpleNamespace(revision=lambda s, r: Pinned())
    status = gateway.revision_status(AislBinding("repo", "demo", "rev-pinned"))
    assert status == {"status": "ready", "system_id": "demo", "revision_id": "rev-pinned",
                      "available_tools": ["list_revisions", "resolve_attribute_path"]}
    assert seen == ["revision-tools"]


def test_revision_tools_contract_error_is_not_silently_readied(monkeypatch):
    ContractError = _sdk_shim(monkeypatch)
    def fail():
        raise ContractError("unverified or missing published tools")
    gateway = object.__new__(KnowledgeApiGateway)
    gateway._client = SimpleNamespace(revision=lambda s, r: SimpleNamespace(revision_tools=fail))
    status = gateway.revision_status(AislBinding("repo", "demo", "rev-pinned"))
    assert status["status"] == "contract_error"
    assert status["available_tools"] == []


def test_preparation_emits_current_kcp_contract(monkeypatch):
    import aisl_interaction_lineage.prepare as module
    calls = []
    readiness = {
        "status": "not_ready", "preparation_requirements": [{
            "state": "needs_repository_preparation", "repository_id": "caller",
            "system_id": "caller-system", "observed_boundary": {"repository_id": "caller"},
            "selector_context": {"repository_id": "caller"},
        }], "repositories": [{"repository_id": "caller", "status": "missing_binding"}],
    }
    monkeypatch.setattr(module, "check_interaction_lineage", lambda *args, **kw: readiness)
    class Gateway:
        def run_preparation(self, payload):
            calls.append(payload)
            return _framework_result("blocked")
    prepare_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
                                readiness_gateway=ReadinessGateway(), preparation_gateway=Gateway(),
                                budget=PreparationBudget(1, 1))
    assert len(calls) == 1
    call = calls[0]
    assert call["product_ids"] == ["attribute-lineage"]
    assert call["execution_scope"] == "workspace"
    assert "required_capabilities" not in call
    assert "analysis_profile_id" not in call
    assert call["max_steps"] == 1
