"""Task 51: automatic, explicit publication without Server CLI in Producer."""
from __future__ import annotations

import hashlib
import io
import json
from urllib.error import HTTPError

import pytest

from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
from aisl_interaction_lineage.prepare import PreparationBudget, prepare_interaction_lineage
from aisl_interaction_lineage.publication import HttpPublicationGateway
from test_builder import EDGE_ID, topology
from test_check_prepare import ReadinessGateway, _not_ready_with_requirement


def _kcp_result(blob_a=b"knowledge", blob_b=b"catalogue"):
    a = hashlib.sha256(blob_a).hexdigest()
    b = hashlib.sha256(blob_b).hexdigest()
    refs = [
        {"kind": "publication_bundle", "artifact_id": "artifact-a", "sha256": a,
         "download_path": "/api/v1/artifacts/artifact-a/download"},
        {"kind": "attribute_catalogue_bundle", "artifact_id": "artifact-b", "sha256": b,
         "download_path": "/api/v1/artifacts/artifact-b/download"},
    ]
    return {"schema_version": "framework_preparation_result/v1", "outcome": "awaiting_publication",
            "final_readiness": {"state": "awaiting_publication", "preparation_context": {
                "target_system_id": "caller-system", "publication_bundle_sha256": a,
                "selected_repo_ids": ["caller"], "source_provenance_refs": [{
                    "source_kind": "repository", "repository_id": "caller", "revision": "a" * 40,
                }],
            }},
            "steps": [{"step_id": "job", "status": "awaiting_publication",
                       "publication_refs": refs, "source_provenance_refs": []}],
            "diagnostics": []}


class _Response:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size=-1): return self.body[:size] if size != -1 else self.body


def test_download_upload_digest_and_publication_are_explicit(monkeypatch):
    from aisl_interaction_lineage import publication
    trace = []

    def response(req, timeout):
        url = req.full_url
        trace.append((url, req.get_method(), req.headers))
        if url.endswith("/artifact-a/download"): return _Response(b"knowledge")
        if url.endswith("/artifact-b/download"): return _Response(b"catalogue")
        if url.endswith("/publications/import-catalogue"):
            assert req.data == b"catalogue"
            return _Response(b'{"status":"already_imported","system_id":"caller-system","revision_id":"rev-123"}')
        assert url.endswith("/publications/import") and req.data == b"knowledge"
        assert req.headers["Authorization"] == "Bearer secret"
        return _Response(b'{"status":"already_published","system_id":"caller-system","revision_id":"rev-123"}')

    monkeypatch.setattr(publication, "urlopen", response)
    client = HttpPublicationGateway(kcp_base_url="http://kcp", aisl_base_url="http://127.0.0.1:8080", token="secret")
    ref = client.publish(repository_id="caller", result=_kcp_result(), expected_commit="a" * 40)
    assert ref == AislBinding("caller", "caller-system", "rev-123", ("caller",))
    assert [method for _, method, _ in trace] == ["GET", "POST", "GET", "POST"]
    assert not any("secret" in url for url, _, _ in trace)


def test_wrong_git_revision_rejected_before_any_network(monkeypatch):
    from aisl_interaction_lineage import publication
    monkeypatch.setattr(publication, "urlopen", lambda *_a, **_kw: pytest.fail("network should not run"))
    client = HttpPublicationGateway(kcp_base_url="http://kcp", aisl_base_url="http://127.0.0.1:8080", token="secret")
    with pytest.raises(RuntimeError, match="Git commit"):
        client.publish(repository_id="caller", result=_kcp_result(), expected_commit="b" * 40)


def test_corrupted_artifact_cannot_reach_server(monkeypatch):
    from aisl_interaction_lineage import publication
    calls = []
    def response(req, timeout):
        calls.append(req.full_url)
        return _Response(b"corrupted")
    monkeypatch.setattr(publication, "urlopen", response)
    client = HttpPublicationGateway(kcp_base_url="http://kcp", aisl_base_url="http://127.0.0.1:8080", token="secret")
    with pytest.raises(RuntimeError, match="digest"):
        client.publish(repository_id="caller", result=_kcp_result())
    assert calls == ["http://kcp/api/v1/artifacts/artifact-a/download"]


def test_successful_publication_is_pinned_and_rechecked(monkeypatch):
    from aisl_interaction_lineage import prepare as module
    calls = []
    def readiness(_top, *, bindings, **kw):
        if bindings.find("caller") is None:
            return _not_ready_with_requirement()
        return {"status": "ready", "preparation_requirements": [], "repositories": [], "diagnostics": []}
    monkeypatch.setattr(module, "check_interaction_lineage", readiness)
    class Kcp:
        def run_preparation(self, request):
            calls.append("kcp")
            return _kcp_result()
    class Publisher:
        def publish(self, *, repository_id, result, expected_commit):
            calls.append("server")
            return AislBinding(repository_id, "caller-system", "rev-123")
    output = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=BindingIndex([AislBinding("service", "service-system", "rev-service")]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=Kcp(),
        publication_gateway=Publisher(), budget=PreparationBudget(1, 1),
    )
    assert calls == ["kcp", "server"]
    assert output["status"] == "prepared"
    assert output["summary"]["published_revision_count"] == 1
    assert {b["revision_id"] for b in output["bindings"]["repositories"]} == {"rev-123", "rev-service"}


def test_missing_publication_token_fails_closed_without_fake_revision(monkeypatch):
    from aisl_interaction_lineage import prepare as module
    monkeypatch.setattr(module, "check_interaction_lineage", lambda *_a, **_kw: _not_ready_with_requirement())
    class Kcp:
        def run_preparation(self, request): return _kcp_result()
    output = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=Kcp(),
        budget=PreparationBudget(1, 1),
    )
    assert output["status"] == "awaiting_publication"
    assert output["summary"]["awaiting_publication_count"] == 1
    assert output["bindings"]["repositories"] == []


def test_existing_exact_materialized_revision_is_reused_without_spending_budget(monkeypatch):
    from aisl_interaction_lineage import prepare as module
    def readiness(_top, *, bindings, **kw):
        if bindings.find("caller") is None:
            return _not_ready_with_requirement()
        return {"status": "ready", "preparation_requirements": [], "repositories": []}
    monkeypatch.setattr(module, "check_interaction_lineage", readiness)
    events = []
    class Kcp:
        def run_preparation(self, request): pytest.fail("KCP should not run when source is already published")
    def ensure(rid):
        events.append("kcp_repository_listing")
        return {"kcp_materialized_commit": "a" * 40}
    def reuse(rid, recorded):
        events.append("aisl_catalogue_lookup")
        return AislBinding("caller", "caller-system", "rev-reused")
    budget = PreparationBudget(0, 1)
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID,
        bindings=BindingIndex([AislBinding("service", "service-system", "rev-service")]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=Kcp(),
        ensure_repository=ensure, published_lookup=reuse, budget=budget,
    )
    assert result["status"] == "prepared"
    assert budget.used == 0
    assert events == ["kcp_repository_listing", "aisl_catalogue_lookup"]
    assert {x["revision_id"] for x in result["bindings"]["repositories"]} == {"rev-reused", "rev-service"}


def test_latest_eligible_revision_selection_is_exact_and_uses_server_ordinal():
    from types import SimpleNamespace
    from aisl_interaction_lineage.bundle_plan import find_exact_published_revision
    source = "https://git.example/repo.git"
    commit = "a" * 40
    def revision(ordinal, sha, tool=True):
        return SimpleNamespace(revision_id=f"rev-{ordinal}", ordinal=ordinal, raw={
            "metadata": {"source_snapshots": [{"source_kind": "git", "location": source,
                "resolved_version": {"commit_sha": sha}}]},
        }, tool=tool)
    rows = [revision(1, commit), revision(2, "b"*40), revision(3, commit), revision(4, commit, False)]
    class Catalog:
        def list_systems(self): return [SimpleNamespace(system_id="exact-system")]
        def list_revisions(self, sid): return rows
        def revision(self, sid, rid):
            row = next(x for x in rows if x.revision_id == rid)
            return SimpleNamespace(revision_tools=lambda: SimpleNamespace(tools=[
                {"name": "resolve_attribute_path"}] if row.tool else []))
    ref = find_exact_published_revision(Catalog(), repository_id="repo", repository_url=source, commit_sha=commit)
    assert ref == AislBinding("repo", "exact-system", "rev-3")


def test_catalogue_response_must_match_exact_published_revision(monkeypatch):
    from aisl_interaction_lineage import publication
    calls = []
    def response(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith("/artifact-a/download"):
            return _Response(b"knowledge")
        if req.full_url.endswith("/artifact-b/download"):
            return _Response(b"catalogue")
        if req.full_url.endswith("/publications/import"):
            return _Response(b'{"status":"published","system_id":"caller-system","revision_id":"rev-123"}')
        if req.full_url.endswith("/publications/import-catalogue"):
            return _Response(b'{"status":"imported","system_id":"other-system","revision_id":"rev-other"}')
        pytest.fail("unexpected request")
    monkeypatch.setattr(publication, "urlopen", response)
    client = HttpPublicationGateway(kcp_base_url="http://kcp", aisl_base_url="http://127.0.0.1:8080", token="secret")
    with pytest.raises(RuntimeError, match="catalogue identity differs"):
        client.publish(repository_id="caller", result=_kcp_result(), expected_commit="a"*40)
    assert len(calls) == 4
