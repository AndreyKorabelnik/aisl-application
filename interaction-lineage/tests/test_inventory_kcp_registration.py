from __future__ import annotations

import json
from pathlib import Path

import pytest

import aisl_interaction_lineage.repository_sources as sources
import aisl_interaction_lineage.prepare as prep
from aisl_interaction_lineage.contracts import BindingIndex
from aisl_interaction_lineage.prepare import PreparationBudget, prepare_interaction_lineage
from test_builder import EDGE_ID, topology
from test_check_prepare import _not_ready_with_requirement, ReadinessGateway


def _manifest(path: Path, repo="caller", url="https://git.corp/p/caller.git", commit="a" * 40,
              status="completed", ref="main"):
    path.write_text(json.dumps({
        "format": sources.MANIFEST_FORMAT,
        "repository_results": [{
            "repository_id": repo, "repository_url": url, "resolved_commit": commit,
            "requested_ref": ref, "status": status,
        }],
    }), encoding="utf-8")
    return str(path)


class Response:
    def __init__(self, value):
        self.value = value
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.value).encode("utf-8")


def test_on_demand_registration_is_single_remote_and_deferred_checkout(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path / "remote_batch_manifest.json")
    rows = []
    calls = []
    def fake_open(req, timeout):
        calls.append((req.method, req.full_url, json.loads(req.data) if req.data else None))
        if req.method == "GET":
            return Response({"items": rows[:], "page": {"offset": 0, "limit": 500, "total": len(rows)}})
        assert req.full_url.endswith("/repositories/discover")
        assert json.loads(req.data) == {
            "remotes": [{"location": "https://git.corp/p/caller.git", "name": "caller",
                         "tracked_ref": {"kind": "branch", "name": "main"}}],
            "defer_checkout": True, "refresh": False,
        }
        rows.append({"repository_id": "caller-hashed", "location": "https://git.corp/p/caller.git",
                     "metadata": {"analysis_repository_id": "caller", "tracked_ref": {"kind": "branch", "name": "main"}},
                     "revision": None})
        return Response({"repositories": rows[:], "discovered_count": 1, "warnings": []})
    monkeypatch.setattr(sources, "urlopen", fake_open)
    registrar = sources.KcpRepositoryRegistrar("http://kcp", sources.load_inventory_remote_sources([manifest]))
    assert registrar.ensure("caller")["status"] == "registered_ref_unverified"
    assert registrar.ensure("caller")["kcp_repository_id"] == "caller-hashed"
    assert len([x for x in calls if x[0] == "POST"]) == 1


def test_existing_repository_exact_commit_is_reused(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path / "manifest.json")
    def fake_open(req, timeout):
        assert req.method == "GET"
        return Response({"items": [{"repository_id": "existing-1",
            "location": "https://git.corp/p/caller.git", "revision": "a" * 40,
            "metadata": {"analysis_repository_id": "caller", "tracked_ref": {"kind": "branch", "name": "main"}}}],
            "page": {"total": 1}})
    monkeypatch.setattr(sources, "urlopen", fake_open)
    registrar = sources.KcpRepositoryRegistrar("http://kcp", sources.load_inventory_remote_sources([manifest]))
    assert registrar.ensure("caller")["status"] == "registered_exact_snapshot"


@pytest.mark.parametrize("change", ["location", "revision", "ambiguous", "tracked_ref"])
def test_conflict_blocks_without_post(tmp_path, monkeypatch, change):
    manifest = _manifest(tmp_path / "manifest.json")
    row = {"repository_id": "r-1", "location": "https://git.corp/p/caller.git",
           "revision": None, "metadata": {"analysis_repository_id": "caller",
                                              "tracked_ref": {"kind": "branch", "name": "main"}}}
    if change == "location": row["location"] = "https://other/source"
    if change == "revision": row["revision"] = "b" * 40
    if change == "tracked_ref": row["metadata"]["tracked_ref"]["name"] = "develop"
    rows = [row, row] if change == "ambiguous" else [row]
    monkeypatch.setattr(sources, "urlopen", lambda req, timeout: Response({"items": rows, "page": {"total": len(rows)}}))
    registrar = sources.KcpRepositoryRegistrar("http://kcp", sources.load_inventory_remote_sources([manifest]))
    with pytest.raises(ValueError): registrar.ensure("caller")


def test_bad_and_duplicate_manifest_fail_closed(tmp_path):
    good = _manifest(tmp_path / "good.json")
    other = _manifest(tmp_path / "other.json", url="https://git.corp/p/other.git")
    with pytest.raises(ValueError, match="ambiguous"):
        sources.load_inventory_remote_sources([good, other])
    _manifest(tmp_path / "other.json", status="failed")
    assert set(sources.load_inventory_remote_sources([good, other])) == {"caller"}
    _manifest(tmp_path / "other.json", url="https://user:pass@git.corp/secret.git")
    with pytest.raises(ValueError, match="unsafe"):
        sources.load_inventory_remote_sources([str(tmp_path / "other.json")])


def test_registration_occurs_only_for_budgeted_preparation(monkeypatch):
    before = _not_ready_with_requirement()
    monkeypatch.setattr(prep, "check_interaction_lineage", lambda *a, **kw: before)
    seen = []
    class Recorder:
        def run_preparation(self, payload):
            seen.append(("preparation", payload))
            return {"schema_version": "framework_preparation_result/v1", "outcome": "no_progress",
                    "final_readiness": {"knowledge_refs": []}, "steps": []}
    register = lambda repo: seen.append(("registration", repo)) or {"status": "registered_ref_unverified", "inventory_resolved_commit": "a" * 40}
    args = dict(topology=topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
                readiness_gateway=ReadinessGateway(), preparation_gateway=Recorder(),
                ensure_repository=register)
    zero = prepare_interaction_lineage(**args, budget=PreparationBudget(0, 1))
    assert zero["status"] == "budget_exhausted" and not seen
    bounded = prepare_interaction_lineage(**args, budget=PreparationBudget(1, 1))
    assert bounded["status"] == "no_progress"
    assert seen[0] == ("registration", "caller")
    assert seen[1][0] == "preparation"


def test_registered_url_under_other_analysis_id_is_conflict(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path / "manifest.json")
    row = {"repository_id": "other", "name": "other", "location": "https://git.corp/p/caller.git",
           "metadata": {"analysis_repository_id": "other"}}
    monkeypatch.setattr(sources, "urlopen", lambda req, timeout: Response({"items": [row], "page": {"total": 1}}))
    with pytest.raises(ValueError, match="conflicting"):
        sources.KcpRepositoryRegistrar("http://kcp", sources.load_inventory_remote_sources([manifest])).ensure("caller")


def test_existing_without_analysis_metadata_uses_kcp_name_fallback(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path / "manifest.json")
    row = {"repository_id": "caller-hash", "name": "caller", "location": "https://git.corp/p/caller.git",
           "metadata": {"tracked_ref": {"kind": "branch", "name": "main"}}, "revision": "a" * 40}
    monkeypatch.setattr(sources, "urlopen", lambda req, timeout: Response({"items": [row], "page": {"total": 1}}))
    assert sources.KcpRepositoryRegistrar("http://kcp", sources.load_inventory_remote_sources([manifest])).ensure("caller")["revision_verified"]


def test_only_selected_sources_are_loaded_and_other_bad_rows_ignored(tmp_path):
    path = tmp_path / "manifest.json"
    payload = {"format": sources.MANIFEST_FORMAT, "repository_results": [
        {"repository_id": "caller", "repository_url": "https://git.corp/p/caller.git",
         "resolved_commit": "a" * 40, "requested_ref": "main", "status": "completed"},
        {"repository_id": "unselected", "repository_url": "https://user:password@host/bad",
         "resolved_commit": "NOT_SHA", "status": "completed"},
    ]}
    path.write_text(json.dumps(payload))
    assert list(sources.load_inventory_remote_sources([str(path)], selected_ids={"caller"})) == ["caller"]


@pytest.mark.parametrize("revision", ["b" * 40, "", None])
def test_preparation_rejects_published_source_without_exact_inventory_commit(monkeypatch, revision):
    monkeypatch.setattr(prep, "check_interaction_lineage", lambda *a, **kw: _not_ready_with_requirement())
    class Recorder:
        def run_preparation(self, _payload):
            return {"outcome": "prepared", "final_readiness": {"knowledge_refs": []},
                    "steps": [{"status": "published", "step_id": "job-1",
                               "source_provenance_refs": ([{
                                   "source_kind": "repository", "repository_id": "caller",
                                   "revision": revision}] if revision is not None else [])}]}
    with pytest.raises(RuntimeError, match="revision does not match"):
        prepare_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
            readiness_gateway=ReadinessGateway(), preparation_gateway=Recorder(), budget=PreparationBudget(1,1),
            ensure_repository=lambda repo: {"inventory_resolved_commit": "a" * 40})


def test_preparation_accepts_published_source_with_matching_commit(monkeypatch):
    monkeypatch.setattr(prep, "check_interaction_lineage", lambda *a, **kw: _not_ready_with_requirement())
    class Recorder:
        def run_preparation(self, _payload):
            return {"outcome": "no_progress", "final_readiness": {"knowledge_refs": []},
                    "steps": [{"status": "published", "step_id": "job-1",
                               "source_provenance_refs": [{"source_kind": "repository",
                                   "repository_id": "caller", "revision": "a" * 40}]}]}
    result = prepare_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=BindingIndex([]),
        readiness_gateway=ReadinessGateway(), preparation_gateway=Recorder(), budget=PreparationBudget(1,1),
        ensure_repository=lambda repo: {"inventory_resolved_commit": "a" * 40})
    assert result["framework_preparations"][0]["steps"][0]["step_id"] == "job-1"
