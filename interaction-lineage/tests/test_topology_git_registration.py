from __future__ import annotations

import json
from pathlib import Path
import pytest

from aisl_interaction_lineage.repository_sources import load_topology_remote_sources, KcpRepositoryRegistrar
from aisl_interaction_lineage import repository_sources as sources

def _topology(commit="", url="https://git.sc.example.corp/groups/kpk.git"):
    return {"format": "repository-topology/v5", "topology_id": "test", "repositories": [
        {"repository_id": "kpk", "repository_url": url, "resolved_commit": commit},
        {"repository_id": "unused", "repository_url": "https://attacker/steal", "resolved_commit": "bad"},
    ], "edges": [{"source_repository_id": "kpk", "target_repository_id": "ucp"}]}


def test_selected_topology_url_registers_without_manifest_and_without_fabricated_sha(monkeypatch):
    records = load_topology_remote_sources(_topology(), selected_ids={"kpk"})
    assert records["kpk"].resolved_commit == ""
    calls = []
    rows = []
    class Response:
        def __init__(self, result): self.result = result
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(self.result).encode()
    def fake_open(req, timeout):
        calls.append((req.method, req.full_url, json.loads(req.data) if req.data else None))
        if req.method == "GET":
            return Response({"items": list(rows), "page": {"total": len(rows)}})
        assert req.full_url.endswith("/repositories/discover")
        assert calls[-1][2] == {"remotes": [{"location": records["kpk"].repository_url,
                                              "name": "kpk"}], "defer_checkout": True, "refresh": False}
        rows.append({"repository_id": "registered-kpk", "location": records["kpk"].repository_url,
                     "metadata": {"analysis_repository_id": "kpk", "tracked_ref": {"kind": "head", "name": None}},
                     "revision": None})
        return Response({"repositories": list(rows), "discovered_count": 1, "warnings": []})
    monkeypatch.setattr(sources, "urlopen", fake_open)
    registrar = KcpRepositoryRegistrar("http://kcp", records)
    result = registrar.ensure("kpk")
    assert result["status"] == "registered_ref_unverified_against_topology"
    assert result["inventory_resolved_commit"] == ""
    assert result["revision_verified"] is False
    assert len([x for x in calls if x[0] == "POST"]) == 1


def test_selected_manifest_less_topology_rejects_unsafe_urls_and_preserves_exact_urls():
    # Which Git hosts are approved belongs to the KCP source-acquisition policy.
    scoped = load_topology_remote_sources(_topology(url="https://stash.example.corp/scm/r.git"),
                                          selected_ids={"kpk"})
    assert scoped["kpk"].repository_url == "https://stash.example.corp/scm/r.git"
    assert not load_topology_remote_sources(_topology(url=""), selected_ids={"kpk"})
    assert list(load_topology_remote_sources(_topology(), selected_ids={"kpk", "ucp"})) == ["kpk"]
    with pytest.raises(ValueError, match="unsafe"):
        load_topology_remote_sources(_topology(url="https://user:password@stash.example.corp/scm/a.git"),
                                     selected_ids={"kpk"})
    with pytest.raises(ValueError, match="HTTPS"):
        load_topology_remote_sources(_topology(url="http://stash.example.corp/scm/a.git"), selected_ids={"kpk"})


def test_snapshot_provenance_when_topology_contains_sha():
    commit = "a" * 40
    records = load_topology_remote_sources(_topology(commit=commit),
                                            selected_ids={"kpk"})
    assert records["kpk"].resolved_commit == commit
