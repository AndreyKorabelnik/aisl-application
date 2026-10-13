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


def _rev(url, commit, *, capability=True):
    return SimpleNamespace(
        revision_id="rev-123",
        capabilities=["workspace.attribute-path-resolver"] if capability else [],
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
    assert "--knowledge-profile attribute-lineage-v1" in shell
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


def test_cli_prepare_emits_bundle_script_after_kcp_and_reuses_published_before_kcp(tmp_path, monkeypatch, capsys):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    source = tmp_path / "topology.json"
    source.write_text(json.dumps(_topology([ucp, kpk])), encoding="utf-8")
    seen = []

    class FakeGateway:
        def __init__(self, base_url):
            assert base_url == "http://server:8080"
            self._client = FakeCatalog([_rev(ucp["repository_url"], ucp["resolved_commit"])])
        def close(self):
            pass

    def fake_prepare(_topology, *, bindings, edge_id, **kwargs):
        seen.append({"edge_id": edge_id, "published_bound": bindings.find("ucp_api")})
        return {"status": "prepared", "summary": {"framework_invocation_count": 1},
                "bindings": {"repositories": [
                    {"repository_id": "kpk_gateway", "system_id": "kpk_gateway", "revision_id": "job-pending"}
                ]}}

    monkeypatch.setattr(cli, "KnowledgeApiGateway", FakeGateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_args: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage", fake_prepare)
    output = tmp_path / "out"
    code = cli.main(["prepare", "--topology", str(source), "--all-edges",
                     "--aisl-base-url", "http://server:8080", "--kcp-base-url", "http://kcp:8000",
                     "--output-dir", str(output)])
    assert code == 2  # manual KPK bundle remains after bounded automatic preparation
    assert seen[0]["edge_id"] == "edge"
    assert seen[0]["published_bound"].revision_id == "rev-123"
    report = json.loads((output / "missing-revisions.json").read_text())
    script = (output / "prepare-missing-bundles.sh").read_text()
    assert report["summary"]["requires_bundle_count"] == 1
    assert (output / "prepare-missing-bundles.sh").stat().st_mode & 0o111
    assert "--repository work/repo-0001" in script
    assert "https://git.example/kpk_gateway.git" in script
    assert "https://git.example/ucp_api.git" not in script
    assert "knowledge-control-plane run" in script
    assert "knowledge-api import" not in script
    assert "publication_bundle.path" in script
    result = json.loads((output / "preparation.json").read_text())
    assert result["status"] == "partial"
    assert result["summary"]["framework_invocation_count"] == 1
    assert result["manual_bundles"]["status"] == "needs_manual_bundles"
    assert json.loads((output / "resolved-bindings.json").read_text())["repositories"][0]["system_id"] == "system-of-ucp"


def test_cli_prepare_resumes_after_manual_publication(tmp_path, monkeypatch):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    source = tmp_path / "topology.json"
    source.write_text(json.dumps(_topology([ucp, kpk])))

    class FakeGateway:
        def __init__(self, *_):
            self._client = FakeCatalog([_rev(ucp["repository_url"], ucp["resolved_commit"]),
                                        _rev(kpk["repository_url"], kpk["resolved_commit"])])
        def close(self):
            pass

    observed = []
    def fake_prepare(_topology, *, bindings, **kwargs):
        observed.append((bindings.find("ucp_api"), bindings.find("kpk_gateway")))
        return {"status": "already_prepared", "summary": {"framework_invocation_count": 0},
                "bindings": {"repositories": [b.to_dict() for b in bindings.all()]}}

    monkeypatch.setattr(cli, "KnowledgeApiGateway", FakeGateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_args: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage", fake_prepare)
    out = tmp_path / "out"
    assert cli.main(["prepare", "--topology", str(source), "--all-edges",
                     "--aisl-base-url", "http://server:8080", "--kcp-base-url", "http://kcp:8000",
                     "--output-dir", str(out)]) == 0
    assert all(observed[0])
    assert json.loads((out / "missing-revisions.json").read_text())["status"] == "ready"
    assert 'No mechanically executable' in (out / "prepare-missing-bundles.sh").read_text()


def test_cli_prepare_clears_previous_bundle_plan_on_catalog_failure(tmp_path, monkeypatch):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    topology_file = tmp_path / "topology.json"
    topology_file.write_text(json.dumps(_topology([ucp, kpk])))
    state = {"available": True}

    class Catalog(FakeCatalog):
        def list_systems(self):
            if not state["available"]:
                raise RuntimeError("AISL catalog HTTP 503")
            return super().list_systems()

    class Gateway:
        def __init__(self, *_):
            self._client = Catalog([_rev(ucp["repository_url"], ucp["resolved_commit"])])
        def close(self):
            pass

    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage",
                        lambda *_args, **_kwargs: {"status": "already_prepared"})
    out = tmp_path / "out"
    cmd = ["prepare", "--topology", str(topology_file), "--all-edges",
           "--aisl-base-url", "http://server:8080", "--kcp-base-url", "http://kcp:8000",
           "--max-preparations", "0", "--output-dir", str(out)]
    assert cli.main(cmd) == 2
    assert "kpk_gateway" in (out / "prepare-missing-bundles.sh").read_text()
    state["available"] = False
    assert cli.main(cmd) == 2
    assert json.loads((out / "preparation.json").read_text())["status"] == "failed"
    for name in ("missing-revisions.json", "resolved-bindings.json",
                 "prepare-missing-bundles.sh"):
        assert not (out / name).exists(), name


def test_cli_prepare_clears_partial_plan_files_if_plan_writer_fails(tmp_path, monkeypatch):
    from aisl_interaction_lineage import cli
    ucp, kpk = _r("ucp_api", "a" * 40), _r("kpk_gateway", "b" * 40)
    topology_file = tmp_path / "topology.json"
    topology_file.write_text(json.dumps(_topology([ucp, kpk])))

    class Gateway:
        def __init__(self, *_):
            self._client = FakeCatalog([])
        def close(self):
            pass

    original = cli.write_bundle_plan
    def interrupted_write(plan, root):
        original(plan, root)
        raise RuntimeError("simulated output interruption")

    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "KnowledgeControlPlaneGateway", lambda *_: object())
    monkeypatch.setattr(cli, "prepare_interaction_lineage",
                        lambda *_args, **_kwargs: {"status": "already_prepared"})
    monkeypatch.setattr(cli, "write_bundle_plan", interrupted_write)
    out = tmp_path / "out"
    assert cli.main(["prepare", "--topology", str(topology_file), "--all-edges",
                     "--aisl-base-url", "http://server:8080", "--kcp-base-url", "http://kcp:8000",
                     "--output-dir", str(out)]) == 2
    assert json.loads((out / "preparation.json").read_text())["status"] == "failed"
    for name in ("missing-revisions.json", "resolved-bindings.json",
                 "prepare-missing-bundles.sh"):
        assert not (out / name).exists(), name
