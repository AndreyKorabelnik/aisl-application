from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aisl_interaction_lineage.bundle_plan import plan_missing_bundles, render_preparation_script, write_bundle_plan


def _topology(repos):
    return {"format": "repository-topology/v5", "topology_id": "topo-1", "edges": [
        {"edge_id": "edge", "source_repository_id": "ucp_api", "target_repository_id": "kpk_gateway"},
    ], "repositories": repos}


def _r(rid, commit, url=None):
    return {"repository_id": rid, "repository_url": url or f"https://git.example/{rid}.git", "resolved_commit": commit}


class FakeCatalog:
    def __init__(self, published=()):
        self.rows = list(published)

    def list_systems(self):
        return [SimpleNamespace(system_id="system-of-ucp")]

    def list_revisions(self, system_id):
        return list(self.rows)

    def revision(self, system_id, revision_id):
        matches = [row for row in self.rows if row.revision_id == revision_id]
        if len(matches) != 1:
            raise ValueError("ambiguous/missing exact published revision")
        return SimpleNamespace(revision_tools=lambda: SimpleNamespace(tools=[
            {"name": "resolve_attribute_path"}
        ] if matches[0].tool_available else []))


def _rev(url, commit, *, capability=True):
    return SimpleNamespace(
        revision_id="rev-123" if url.endswith("ucp_api.git") else "rev-kpk",
        tool_available=capability,
        raw={"metadata": {"source_snapshots": [{
            "source_kind": "git", "location": url,
            "resolved_version": {"kind": "git_commit", "commit_sha": commit},
        }]}})


def test_only_missing_exact_source_gets_generated_bundle_script(tmp_path):
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    plan = plan_missing_bundles(_topology([ucp, kpk]), client=FakeCatalog([_rev(ucp["repository_url"], ucp["resolved_commit"])]))
    assert plan["summary"] == {"repository_count": 2, "ready_count": 1, "requires_bundle_count": 1, "unresolved_count": 0}
    assert plan["resolved_bindings"]["repositories"] == [
        {"repository_id": "ucp_api", "system_id": "system-of-ucp", "revision_id": "rev-123"}
    ]
    write_bundle_plan(plan, tmp_path)
    shell = (tmp_path / "prepare-missing-bundles.sh").read_text()
    assert "https://git.example/kpk_gateway.git" in shell
    assert "https://git.example/ucp_api.git" not in shell
    assert "--product attribute-lineage --scope repository" in shell
    assert "--knowledge-profile" not in shell
    assert "--system-id kpk_gateway" in shell
    assert "checkout --detach" in shell
    assert "publication_bundle.path" in shell
    assert "shutil.copy" not in shell
    assert "knowledge-api import" not in shell
    assert "scp " not in shell
    assert json.loads((tmp_path / "missing-revisions.json").read_text())["status"] == "needs_manual_bundles"


def test_wrong_git_revision_is_never_reused():
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    plan = plan_missing_bundles(_topology([ucp, kpk]), client=FakeCatalog([_rev(ucp["repository_url"], "c" * 40)]))
    assert plan["summary"]["ready_count"] == 0
    assert plan["summary"]["requires_bundle_count"] == 2


def test_no_exact_sha_blocks_source_prep_instead_of_guessing():
    ucp, kpk = _r("ucp_api", ""), _r("kpk_gateway", "b" * 40)
    plan = plan_missing_bundles(_topology([ucp, kpk]), client=FakeCatalog())
    assert plan["summary"]["unresolved_count"] == 1
    assert "BLOCKED" in render_preparation_script(plan)
    assert "https://git.example/ucp_api.git" not in render_preparation_script(plan)


def test_unsafe_git_url_fails_closed():
    ucp, kpk = _r("ucp_api", "a" * 40, "https://user:password@git.example/ucp_api.git"), _r("kpk_gateway", "b" * 40)
    with pytest.raises(ValueError, match="unsafe topology"):
        plan_missing_bundles(_topology([ucp, kpk]), client=FakeCatalog())


def test_exact_capability_required():
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    plan = plan_missing_bundles(_topology([ucp, kpk]), client=FakeCatalog([_rev(ucp["repository_url"], ucp["resolved_commit"], capability=False)]))
    assert plan["summary"]["ready_count"] == 0


def test_cli_prepare_emits_resolution_ledger_without_manual_script(tmp_path, monkeypatch):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    source = tmp_path / "topology.json"
    source.write_text(json.dumps(_topology([ucp, kpk])), encoding="utf-8")
    seen = []

    class FakeGateway:
        def __init__(self, base_url):
            self._client = FakeCatalog([_rev(ucp["repository_url"], ucp["resolved_commit"])])
        def close(self): pass

    def fake_prepare(_topology, *, bindings, edge_id, **kwargs):
        seen.append(bindings.find("ucp_api"))
        return {"status": "blocked", "summary": {"framework_invocation_count": 1},
                "bindings": {"repositories": []}}

    monkeypatch.setattr(cli, "KnowledgeApiGateway", FakeGateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage", fake_prepare)
    out = tmp_path / "out"
    code = cli.main(["prepare", "--topology", str(source), "--all-edges",
                     "--aisl-base-url", "http://server:8080", "--kcp-base-url", "http://kcp:8000",
                     "--output-dir", str(out)])
    assert code == 2
    assert seen[0].revision_id == "rev-123"
    assert not (out / "prepare-missing-bundles.sh").exists()
    report = json.loads((out / "missing-revisions.json").read_text())
    assert report["summary"]["unresolved_count"] == 1
    assert report["repositories"][0]["repository_id"] == "kpk_gateway"
    assert json.loads((out / "resolved-bindings.json").read_text())["repositories"][0]["revision_id"] == "rev-123"
    assert json.loads((out / "preparation.json").read_text())["status"] == "partial"


def test_cli_prepare_reuses_both_published_revisions_without_manual_work(tmp_path, monkeypatch):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    source = tmp_path / "topology.json"
    source.write_text(json.dumps(_topology([ucp, kpk])))
    class Gateway:
        def __init__(self, *_):
            self._client = FakeCatalog([_rev(ucp["repository_url"], ucp["resolved_commit"]),
                                        _rev(kpk["repository_url"], kpk["resolved_commit"])])
        def close(self): pass
    seen = []
    def fake_prepare(_topology, *, bindings, **kwargs):
        seen.append((bindings.find("ucp_api"), bindings.find("kpk_gateway")))
        return {"status": "already_prepared", "summary": {"framework_invocation_count": 0},
                "bindings": {"repositories": [b.to_dict() for b in bindings.all()]}}
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage", fake_prepare)
    out = tmp_path / "out"
    assert cli.main(["prepare", "--topology", str(source), "--all-edges",
                     "--aisl-base-url", "http://server:8080", "--kcp-base-url", "http://kcp:8000",
                     "--output-dir", str(out)]) == 0
    assert all(seen[0])
    assert json.loads((out / "missing-revisions.json").read_text())["summary"]["unresolved_count"] == 0
    assert not (out / "prepare-missing-bundles.sh").exists()


def test_cli_prepare_clears_previous_resolution_on_catalog_failure(tmp_path, monkeypatch):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    source = tmp_path / "topology.json"
    source.write_text(json.dumps(_topology([ucp, kpk])))
    state = {"available": True}
    class Catalog(FakeCatalog):
        def list_systems(self):
            if not state["available"]: raise RuntimeError("AISL catalog HTTP 503")
            return super().list_systems()
    class Gateway:
        def __init__(self, *_): self._client = Catalog([_rev(ucp["repository_url"], ucp["resolved_commit"])])
        def close(self): pass
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage", lambda *_a, **_kw: {
        "status": "already_prepared", "summary": {"framework_invocation_count": 0}})
    out = tmp_path / "out"
    cmd = ["prepare", "--topology", str(source), "--all-edges", "--aisl-base-url", "http://server:8080",
           "--kcp-base-url", "http://kcp:8000", "--output-dir", str(out)]
    assert cli.main(cmd) == 2
    assert (out / "missing-revisions.json").exists()
    state["available"] = False
    assert cli.main(cmd) == 2
    assert json.loads((out / "preparation.json").read_text())["status"] == "failed"
    for name in ("missing-revisions.json", "resolved-bindings.json", "prepare-missing-bundles.sh"):
        assert not (out / name).exists()
