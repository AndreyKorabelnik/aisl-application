"""Read-only batch cache preserves exact revision/parameter semantics."""
from __future__ import annotations

from collections import Counter

from aisl_interaction_lineage.batch_cache import BatchCachingGateway
from aisl_interaction_lineage.contracts import AislBinding


class Gateway:
    def __init__(self):
        self.calls = Counter()
        self.fail_status = False
        self.fail_paths = False
        self.fail_catalog = False

    def revision_status(self, binding):
        self.calls["revision_status"] += 1
        if self.fail_status:
            return {"status": "server_unavailable", "available_tools": []}
        return {"status": "ready", "available_tools": ["resolve_attribute_path"],
                "system_id": binding.system_id, "revision_id": binding.revision_id}

    def resolve_attribute_paths(self, binding, *, source, selected_repo_ids, direction):
        self.calls["resolve_attribute_paths"] += 1
        if self.fail_paths:
            return {"result": {"status": "api_error", "paths": []}}
        return {"result": {"status": "confirmed_complete", "paths": [],
                "query_identity": [binding.system_id, binding.revision_id, source, list(selected_repo_ids), direction]}}

    def list_repository_value_nodes(self, binding, *, repository_id, node_kind=None,
                                    operation=None, max_results=500, page_token=""):
        self.calls["list_repository_value_nodes"] += 1
        if self.fail_catalog:
            return {"result": {"status": "server_unavailable", "items": []}}
        return {"result": {"items": [{"id": repository_id}], "truncated": False,
                "params": [repository_id, node_kind, operation, max_results, page_token]}}


def test_cache_full_identity_preserves_query_distinctions_and_copy_isolation():
    raw = Gateway()
    cached = BatchCachingGateway(raw)
    a = AislBinding("repo", "system", "rev-1")
    other_revision = AislBinding("repo", "system", "rev-2")
    assert cached.revision_status(a) == cached.revision_status(a)
    assert cached.revision_status(other_revision)["revision_id"] == "rev-2"
    assert raw.calls["revision_status"] == 2

    kw = {"source": "this.id", "selected_repo_ids": ["repo", "child"], "direction": "reverse"}
    first = cached.resolve_attribute_paths(a, **kw)
    first["result"]["paths"].append("client_mutation")
    second = cached.resolve_attribute_paths(a, **kw)
    assert second["result"]["paths"] == []
    cached.resolve_attribute_paths(a, **{**kw, "direction": "forward"})
    cached.resolve_attribute_paths(a, **{**kw, "selected_repo_ids": ["child", "repo"]})
    cached.resolve_attribute_paths(a, **{**kw, "source": "id"})
    cached.resolve_attribute_paths(other_revision, **kw)
    assert raw.calls["resolve_attribute_paths"] == 5

    cat = {"repository_id": "repo", "operation": "GET", "node_kind": "field", "max_results": 3, "page_token": "p1"}
    cached.list_repository_value_nodes(a, **cat)
    cached.list_repository_value_nodes(a, **cat)
    cached.list_repository_value_nodes(a, **{**cat, "page_token": "p2"})
    cached.list_repository_value_nodes(a, **{**cat, "max_results": 4})
    cached.list_repository_value_nodes(a, **{**cat, "node_kind": None})
    cached.list_repository_value_nodes(a, **{**cat, "operation": "POST"})
    cached.list_repository_value_nodes(other_revision, **cat)
    assert raw.calls["list_repository_value_nodes"] == 6
    assert cached.statistics()["cache_hit_count"] == 3


def test_cache_does_not_store_errors_or_exceptions():
    raw = Gateway()
    cached = BatchCachingGateway(raw)
    a = AislBinding("repo", "system", "rev-1")
    raw.fail_status = True
    cached.revision_status(a)
    cached.revision_status(a)
    raw.fail_status = False
    assert cached.revision_status(a)["status"] == "ready"
    assert raw.calls["revision_status"] == 3
    raw.fail_paths = True
    for _ in range(2):
        assert cached.resolve_attribute_paths(a, source="x", selected_repo_ids=["repo"], direction="forward")["result"]["status"] == "api_error"
    raw.fail_paths = False
    assert cached.resolve_attribute_paths(a, source="x", selected_repo_ids=["repo"], direction="forward")["result"]["status"] == "confirmed_complete"
    assert raw.calls["resolve_attribute_paths"] == 3
    raw.fail_catalog = True
    for _ in range(2):
        cached.list_repository_value_nodes(a, repository_id="repo")
    raw.fail_catalog = False
    cached.list_repository_value_nodes(a, repository_id="repo")
    assert raw.calls["list_repository_value_nodes"] == 3


def test_cache_is_per_batch_instance_and_does_not_reuse_between_runs():
    raw = Gateway()
    a = AislBinding("repo", "system", "rev-1")
    BatchCachingGateway(raw).revision_status(a)
    BatchCachingGateway(raw).revision_status(a)
    assert raw.calls["revision_status"] == 2
