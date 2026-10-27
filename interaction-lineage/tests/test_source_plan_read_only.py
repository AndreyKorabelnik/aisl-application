from __future__ import annotations

import json
from pathlib import Path

import pytest

from aisl_interaction_lineage.cli import main
from aisl_interaction_lineage.source_plan import plan_interaction_sources


def topology():
    return {"format": "repository-topology/v5", "topology_id": "test", "repositories": [
        {"repository_id": "a", "repository_url": "https://git.example/one/a.git", "resolved_commit": "a" * 40},
        {"repository_id": "b", "repository_url": "https://git.example/one/b.git"},
        {"repository_id": "other", "repository_url": "https://evil.example/other.git"},
    ], "edges": [{"edge_id": "edge1", "source_repository_id": "a", "target_repository_id": "b"},
                  {"edge_id": "edge2", "source_repository_id": "b", "target_repository_id": "other"}]}


def test_offline_selected_edge_is_bounded_and_side_effect_free():
    result = plan_interaction_sources(topology(), edge_ids=["edge1"])
    assert [r["repository_id"] for r in result["repositories"]] == ["a", "b"]
    assert result["side_effects"] == {"git_clones": 0, "nexus_downloads": 0,
                                      "kcp_registrations": 0, "aisl_publications": 0}
    assert result["repositories"][1]["next_action"] == "resolve_git_commit_then_check_publication"
    assert result["repositories"][1]["git_url_status"] == "topology_https_url_validated_kcp_authorization_pending"
    assert result["nexus_artifacts"]["confirmed_exact_downloads"] == []
    assert result["summary"]["selected_repositories"] == 2


def test_known_exact_publication_is_reused(monkeypatch):
    import aisl_interaction_lineage.source_plan as mod

    def fake_bundle_plan(topo, *, client, bindings):
        assert [e["edge_id"] for e in topo["edges"]] == ["edge1"]
        return {"repositories": [
            {"repository_id": "a", "status": "ready", "published_matches": [
                {"repository_id": "a", "system_id": "system-a", "revision_id": "rev-123"}]},
            {"repository_id": "b", "status": "source_identity_missing", "published_matches": []},
        ]}

    monkeypatch.setattr(mod, "plan_missing_bundles", fake_bundle_plan)
    result = plan_interaction_sources(topology(), edge_ids=["edge1"], aisl_client=object())
    assert result["repositories"][0]["next_action"] == "reuse_published_exact_revision"
    assert result["repositories"][0]["download_decision"] == "not_required_exact_published_knowledge"
    assert result["summary"]["already_published_exact"] == 1


def test_kcp_is_get_only_no_registration(monkeypatch):
    import aisl_interaction_lineage.source_plan as mod

    class Registrar:
        def __init__(self, url, sources):
            assert url == "http://kcp" and not sources
        def _matches(self, rid, url):
            assert url.startswith("https://git.example/")
            return [{"location": url, "repository_id": "stored-" + rid}] if rid == "a" else []

    monkeypatch.setattr(mod, "KcpRepositoryRegistrar", Registrar)
    rows = plan_interaction_sources(topology(), edge_ids=["edge1"], kcp_base_url="http://kcp")
    assert rows["repositories"][0]["kcp_registry_status"] == "registered"
    assert rows["repositories"][1]["kcp_registry_status"] == "not_registered"


def test_untrusted_git_url_fails_closed():
    obj = topology()
    obj["repositories"][0]["repository_url"] = "https://user:token@git.example/one/a.git"
    with pytest.raises(ValueError, match="unsafe"):
        plan_interaction_sources(obj, edge_ids=["edge1"])


def test_cli_plan_creates_only_json_and_never_needs_kcp(tmp_path):
    src = tmp_path / "topology.json"
    src.write_text(json.dumps(topology()), encoding="utf-8")
    dest = tmp_path / "out" / "plan.json"
    assert main(["plan", "--topology", str(src), "--edge-id", "edge1", "--output", str(dest)]) == 0
    out = json.loads(dest.read_text())
    assert out["operation"] == "read_only_preview"
    assert {p.name for p in dest.parent.iterdir()} == {"plan.json"}
    assert main(["plan", "--topology", str(src), "--edge-id", "missing", "--output", str(dest)]) == 2
