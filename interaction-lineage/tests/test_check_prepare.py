from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from aisl_interaction_lineage.checker import check_interaction_lineage
from aisl_interaction_lineage.contracts import AislBinding, BindingIndex
from aisl_interaction_lineage.prepare import prepare_interaction_lineage

from test_builder import EDGE_ID, topology


class ReadinessGateway:
    def __init__(
        self,
        *,
        revision_status: Mapping[str, Mapping[str, Any]] | None = None,
        missing_anchors: set[tuple[str, str]] | None = None,
    ) -> None:
        self._revision_status = dict(revision_status or {})
        self.missing_anchors = missing_anchors or set()

    def revision_status(self, binding: AislBinding) -> Mapping[str, Any]:
        return self._revision_status.get(
            binding.repository_id,
            {
                "status": "ready",
                "capabilities": ["workspace.attribute-path-resolver"],
                "system_id": binding.system_id,
                "revision_id": binding.revision_id,
            },
        )

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        repo = selected_repo_ids[0]
        if (repo, source) in self.missing_anchors:
            return {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        node = {
            "repo_id": repo,
            "owner_ref": "service-if" if repo == "service" else "caller-if",
            "value_node_id": f"{repo}:{source}",
            "display_ref": source,
        }
        return {"result": {"status": "confirmed_complete", "source": node, "paths": []}}


def bindings() -> BindingIndex:
    return BindingIndex([
        AislBinding("caller", "caller-system", "caller-rev"),
        AislBinding("service", "service-system", "service-rev"),
    ])


def test_check_ready_requires_revision_capability_and_boundary_anchors() -> None:
    result = check_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=ReadinessGateway())
    assert result["status"] == "ready"
    assert result["summary"] == {
        "repository_count": 2,
        "ready_repository_count": 2,
        "not_ready_repository_count": 0,
    }
    assert all(item["boundary_anchor_missing_count"] == 0 for item in result["repositories"])


def test_check_missing_binding_is_machine_readable() -> None:
    result = check_interaction_lineage(
        topology(),
        edge_id=EDGE_ID,
        bindings=BindingIndex([AislBinding("caller", "caller-system", "caller-rev")]),
        gateway=ReadinessGateway(),
    )
    assert result["status"] == "not_ready"
    service = next(item for item in result["repositories"] if item["repository_id"] == "service")
    assert service["status"] == "missing_binding"
    assert any(item["code"] == "repository_resolution_failed" for item in result["diagnostics"])


def test_check_missing_capability_is_not_ready() -> None:
    result = check_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        gateway=ReadinessGateway(revision_status={"service": {"status": "ready", "capabilities": []}}),
    )
    service = next(item for item in result["repositories"] if item["repository_id"] == "service")
    assert service["status"] == "missing_required_capability"
    assert result["status"] == "not_ready"


def test_check_server_unavailable_is_not_ready_without_fallback() -> None:
    result = check_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(),
        gateway=ReadinessGateway(revision_status={"caller": {"status": "server_unavailable", "diagnostic": "offline"}}),
    )
    caller = next(item for item in result["repositories"] if item["repository_id"] == "caller")
    assert caller["status"] == "server_unavailable"
    assert any(item["code"] == "server_unavailable" for item in result["diagnostics"])


def test_check_missing_boundary_anchor_blocks_ready_state() -> None:
    gateway = ReadinessGateway(missing_anchors={("caller", "HTTP response profile.id")})
    result = check_interaction_lineage(topology(), edge_id=EDGE_ID, bindings=bindings(), gateway=gateway)
    caller = next(item for item in result["repositories"] if item["repository_id"] == "caller")
    assert caller["status"] == "boundary_anchor_not_published"
    assert result["status"] == "not_ready"


class FakePreparationGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def resolve_repository(self, repository_id: str) -> Mapping[str, Any]:
        self.calls.append(("resolve_repository", repository_id))
        return {
            "repository_id": f"runtime-{repository_id}",
            "source_kind": "bitbucket",
            "metadata": {"analysis_repository_id": repository_id},
        }

    def ensure_attribute_lineage_profile(self) -> Mapping[str, Any]:
        self.calls.append(("ensure_profile", None))
        return {"profile_id": "interaction-lineage-attribute-lineage-v1"}

    def ensure_production(self, *, production_id: str, system_id: str, repository_runtime_id: str) -> Mapping[str, Any]:
        self.calls.append(("ensure_production", (production_id, system_id, repository_runtime_id)))
        return {"production_id": production_id}

    def force_refresh(self, production_id: str) -> Mapping[str, Any]:
        self.calls.append(("force_refresh", production_id))
        return {"enqueued_job_id": f"job-{production_id}"}

    def wait_job(self, job_id: str) -> Mapping[str, Any]:
        self.calls.append(("wait_job", job_id))
        return {"job_id": job_id, "status": "succeeded"}

    def download_publication_bundle(self, job_id: str, target: Path) -> Mapping[str, Any]:
        self.calls.append(("download_bundle", job_id))
        target.write_bytes(job_id.encode("utf-8"))
        return {"downloaded_sha256": "0" * 64}


class FakeImporter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def import_bundle(self, bundle_path: Path) -> Mapping[str, Any]:
        repo = bundle_path.name.removesuffix(".aisl.zip")
        self.calls.append(repo)
        return {"revision": {"system_id": repo, "revision_id": f"rev-{repo}"}}


class MutableReadinessGateway(ReadinessGateway):
    def __init__(self) -> None:
        super().__init__()
        self.imported: set[str] = set()

    def revision_status(self, binding: AislBinding) -> Mapping[str, Any]:
        if binding.repository_id not in self.imported:
            return {"status": "missing_revision", "capabilities": []}
        return {
            "status": "ready",
            "capabilities": ["workspace.attribute-path-resolver"],
            "system_id": binding.system_id,
            "revision_id": binding.revision_id,
        }


class ImporterWithReadiness(FakeImporter):
    def __init__(self, readiness: MutableReadinessGateway) -> None:
        super().__init__()
        self.readiness = readiness

    def import_bundle(self, bundle_path: Path) -> Mapping[str, Any]:
        result = super().import_bundle(bundle_path)
        repo = bundle_path.name.removesuffix(".aisl.zip")
        self.readiness.imported.add(repo)
        return result


def test_prepare_is_noop_when_all_repositories_are_ready() -> None:
    prep = FakePreparationGateway()
    importer = FakeImporter()
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=bindings(), readiness_gateway=ReadinessGateway(),
        preparation_gateway=prep, importer=importer,
    )
    assert result["status"] == "already_prepared"
    assert prep.calls == []
    assert importer.calls == []


def test_prepare_fills_missing_bindings_through_kcp_and_importer() -> None:
    readiness = MutableReadinessGateway()
    prep = FakePreparationGateway()
    importer = ImporterWithReadiness(readiness)
    result = prepare_interaction_lineage(
        topology(), edge_id=EDGE_ID, bindings=BindingIndex([]), readiness_gateway=readiness,
        preparation_gateway=prep, importer=importer,
    )
    assert result["status"] == "prepared"
    assert result["summary"]["prepared_repository_count"] == 2
    assert [item["repository_id"] for item in result["bindings"]["repositories"]] == ["caller", "service"]
    assert importer.calls == ["caller", "service"]
    assert sum(1 for name, _ in prep.calls if name == "force_refresh") == 2
