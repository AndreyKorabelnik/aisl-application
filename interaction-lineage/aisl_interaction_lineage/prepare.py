from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .aisl import AislReadinessGateway
from .checker import check_interaction_lineage
from .contracts import AislBinding, BINDINGS_SCHEMA_VERSION, BindingIndex
from .topology import boundary_fields, select_edge

PREPARATION_FORMAT = "interaction-lineage-preparation/v1"
_PROFILE_ID = "interaction-lineage-attribute-lineage-v1"
_PROFILE_KNOWLEDGE_IDS = ["attribute-lineage"]


def _repo_ids(edge: Mapping[str, Any], roles: Sequence[str]) -> list[str]:
    values: set[str] = set()
    for role in roles:
        for field in boundary_fields(edge, transport_role=role):
            values.add(field.source_repository_id)
            values.add(field.target_repository_id)
    return sorted(values)


def _production_id(repository_id: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in repository_id).strip("-")
    safe = "-".join(part for part in safe.split("-") if part)
    digest = hashlib.sha256(repository_id.encode("utf-8")).hexdigest()[:12]
    return f"interaction-lineage-{safe[:70]}-{digest}"


class PreparationGateway(Protocol):
    def resolve_repository(self, repository_id: str) -> Mapping[str, Any]: ...
    def ensure_attribute_lineage_profile(self) -> Mapping[str, Any]: ...
    def ensure_production(
        self,
        *,
        production_id: str,
        system_id: str,
        repository_runtime_id: str,
    ) -> Mapping[str, Any]: ...
    def force_refresh(self, production_id: str) -> Mapping[str, Any]: ...
    def wait_job(self, job_id: str) -> Mapping[str, Any]: ...
    def download_publication_bundle(self, job_id: str, target: Path) -> Mapping[str, Any]: ...


class PublicationImporter(Protocol):
    def import_bundle(self, bundle_path: Path) -> Mapping[str, Any]: ...


class KnowledgeControlPlaneGateway:
    """Public KCP orchestration adapter. Git/source acquisition remains KCP-owned."""

    def __init__(self, base_url: str, *, timeout_sec: float = 30.0, poll_sec: float = 1.0, job_timeout_sec: float = 3600.0) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        if not self.base_url:
            raise ValueError("KCP base URL must not be empty")
        self.timeout_sec = float(timeout_sec)
        self.poll_sec = max(0.1, float(poll_sec))
        self.job_timeout_sec = float(job_timeout_sec)

    def _json(self, method: str, path: str, *, payload: Mapping[str, Any] | None = None, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urlencode({key: value for key, value in params.items() if value is not None})
        body = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, method=method.upper(), headers={"Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})})
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            error = RuntimeError(f"KCP {method.upper()} {path} failed: HTTP {exc.code}: {detail[:1000]}")
            setattr(error, "status_code", exc.code)
            raise error from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(f"KCP {method.upper()} {path} unavailable: {type(exc).__name__}: {exc}") from exc
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"KCP {method.upper()} {path} returned non-object JSON")
        return value

    def resolve_repository(self, repository_id: str) -> Mapping[str, Any]:
        payload = self._json("GET", "/api/v1/repositories", params={"search": repository_id, "limit": 500, "offset": 0})
        items = [item for item in payload.get("items") or () if isinstance(item, Mapping)]
        matches = [item for item in items if str((item.get("metadata") or {}).get("analysis_repository_id") or "") == repository_id]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one KCP source registration for analysis_repository_id={repository_id!r}, found {len(matches)}")
        source = matches[0]
        if str(source.get("source_kind") or "") != "bitbucket":
            raise RuntimeError(f"repository {repository_id!r} is not registered as remote Git/Bitbucket source")
        return dict(source)

    def ensure_attribute_lineage_profile(self) -> Mapping[str, Any]:
        path = f"/api/v1/knowledge-profiles/{quote(_PROFILE_ID, safe='')}"
        try:
            profile = self._json("GET", path)
        except RuntimeError as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            profile = self._json("POST", "/api/v1/knowledge-profiles", payload={
                "profile_id": _PROFILE_ID,
                "name": "Interaction lineage local attribute flow",
                "execution_scope": "workspace",
                "description": "Task 26 preparation profile over the existing attribute-lineage Knowledge Product.",
                "knowledge_ids": list(_PROFILE_KNOWLEDGE_IDS),
            })
        if str(profile.get("execution_scope") or "") != "workspace" or list(profile.get("knowledge_ids") or []) != _PROFILE_KNOWLEDGE_IDS:
            raise RuntimeError(f"KCP profile {_PROFILE_ID!r} exists with incompatible definition")
        return dict(profile)

    def ensure_production(self, *, production_id: str, system_id: str, repository_runtime_id: str) -> Mapping[str, Any]:
        path = f"/api/v1/productions/{quote(production_id, safe='')}"
        try:
            production = self._json("GET", path)
        except RuntimeError as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            production = self._json("POST", "/api/v1/productions", payload={
                "production_id": production_id,
                "system_id": system_id,
                "knowledge_profile_id": _PROFILE_ID,
                "repository_ids": [repository_runtime_id],
                "display_name": system_id,
                "refresh_policy": {"mode": "manual"},
                "enabled": True,
            })
        expected = (system_id, _PROFILE_ID, [repository_runtime_id])
        actual = (
            str(production.get("system_id") or ""),
            str(production.get("knowledge_profile_id") or ""),
            list(production.get("repository_ids") or []),
        )
        if actual != expected:
            raise RuntimeError(f"KCP production {production_id!r} exists with incompatible binding")
        return dict(production)

    def force_refresh(self, production_id: str) -> Mapping[str, Any]:
        return self._json(
            "POST",
            f"/api/v1/productions/{quote(production_id, safe='')}/refresh-check",
            params={"enqueue": "true", "force": "true"},
        )

    def wait_job(self, job_id: str) -> Mapping[str, Any]:
        deadline = time.monotonic() + self.job_timeout_sec
        while True:
            job = self._json("GET", f"/api/v1/jobs/{quote(job_id, safe='')}")
            status = str(job.get("status") or "")
            if status in {"succeeded", "failed", "cancelled"}:
                return job
            if time.monotonic() >= deadline:
                raise RuntimeError(f"KCP job did not finish before timeout: {job_id}")
            time.sleep(self.poll_sec)

    def download_publication_bundle(self, job_id: str, target: Path) -> Mapping[str, Any]:
        artifacts = self._json("GET", f"/api/v1/jobs/{quote(job_id, safe='')}/artifacts")
        matches = [item for item in artifacts.get("items") or () if isinstance(item, Mapping) and str(item.get("kind") or "") == "publication_bundle"]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one KCP publication bundle for job {job_id!r}, found {len(matches)}")
        artifact = dict(matches[0])
        artifact_id = str(artifact.get("artifact_id") or "")
        request = Request(self.base_url + f"/api/v1/artifacts/{quote(artifact_id, safe='')}/download", method="GET")
        try:
            with urlopen(request, timeout=max(self.timeout_sec, 120.0)) as response:
                target.write_bytes(response.read())
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError(f"cannot download KCP publication bundle {artifact_id!r}: {type(exc).__name__}: {exc}") from exc
        expected_sha = str(artifact.get("sha256") or "")
        actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        if expected_sha and actual_sha != expected_sha:
            raise RuntimeError(f"KCP publication bundle SHA-256 mismatch for {artifact_id!r}")
        return {**artifact, "downloaded_sha256": actual_sha, "path": str(target)}


class KnowledgeApiCliImporter:
    """Use the existing canonical AISL Server bundle importer; no second publication engine."""

    def __init__(self, command: Sequence[str] = ("knowledge-api",)) -> None:
        self.command = tuple(command)
        if not self.command:
            raise ValueError("knowledge-api import command must not be empty")

    def import_bundle(self, bundle_path: Path) -> Mapping[str, Any]:
        completed = subprocess.run(
            [*self.command, "import", "--bundle", str(bundle_path), "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "knowledge-api import failed").strip()
            raise RuntimeError(f"knowledge-api import failed: {detail[:2000]}")
        payload = json.loads(completed.stdout)
        if not isinstance(payload, Mapping):
            raise RuntimeError("knowledge-api import returned non-object JSON")
        return dict(payload)


def _bindings_payload(bindings: BindingIndex, repository_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": BINDINGS_SCHEMA_VERSION,
        "repositories": [bindings.require(repository_id).to_dict() for repository_id in sorted(repository_ids)],
    }


def prepare_interaction_lineage(
    topology: Mapping[str, Any],
    *,
    edge_id: str,
    bindings: BindingIndex,
    readiness_gateway: AislReadinessGateway,
    preparation_gateway: PreparationGateway,
    importer: PublicationImporter,
    transport_roles: Sequence[str] = ("request", "response"),
) -> dict[str, Any]:
    edge = select_edge(topology, edge_id)
    repository_ids = _repo_ids(edge, transport_roles)
    before = check_interaction_lineage(
        topology,
        edge_id=edge_id,
        bindings=bindings,
        gateway=readiness_gateway,
        transport_roles=transport_roles,
    )
    if before.get("status") == "ready":
        return {
            "format": PREPARATION_FORMAT,
            "status": "already_prepared",
            "topology_id": str(topology.get("topology_id") or ""),
            "edge_id": edge_id,
            "repositories": [
                {"repository_id": repository_id, "status": "already_prepared"}
                for repository_id in repository_ids
            ],
            "bindings": _bindings_payload(bindings, repository_ids),
            "readiness_before": before,
            "readiness_after": before,
            "summary": {"prepared_repository_count": 0, "reused_repository_count": len(repository_ids)},
        }

    preparation_gateway.ensure_attribute_lineage_profile()
    current: dict[str, AislBinding] = {
        repository_id: bindings.find(repository_id)
        for repository_id in repository_ids
        if bindings.find(repository_id) is not None
    }
    actions: list[dict[str, Any]] = []

    before_by_repo = {str(item.get("repository_id") or ""): item for item in before.get("repositories") or () if isinstance(item, Mapping)}
    with tempfile.TemporaryDirectory(prefix="interaction-lineage-prepare-") as tmp:
        tmp_path = Path(tmp)
        for repository_id in repository_ids:
            row = before_by_repo.get(repository_id) or {}
            if row.get("status") == "ready":
                actions.append({"repository_id": repository_id, "status": "already_prepared"})
                continue

            source = preparation_gateway.resolve_repository(repository_id)
            repository_runtime_id = str(source.get("repository_id") or "")
            if not repository_runtime_id:
                raise RuntimeError(f"KCP repository registration has no repository_id: {repository_id}")
            existing = current.get(repository_id)
            system_id = existing.system_id if existing is not None else repository_id
            production_id = _production_id(repository_id)
            preparation_gateway.ensure_production(
                production_id=production_id,
                system_id=system_id,
                repository_runtime_id=repository_runtime_id,
            )
            refresh = preparation_gateway.force_refresh(production_id)
            job_id = str(refresh.get("enqueued_job_id") or "")
            if not job_id:
                raise RuntimeError(f"KCP forced refresh did not enqueue a job for repository {repository_id!r}")
            job = preparation_gateway.wait_job(job_id)
            if str(job.get("status") or "") != "succeeded":
                raise RuntimeError(f"KCP preparation job failed for {repository_id!r}: {job.get('failure') or job.get('status')}")
            bundle_path = tmp_path / f"{repository_id}.aisl.zip"
            bundle = preparation_gateway.download_publication_bundle(job_id, bundle_path)
            imported = importer.import_bundle(bundle_path)
            revision = imported.get("revision") if isinstance(imported.get("revision"), Mapping) else imported
            revision_id = str(revision.get("revision_id") or "") if isinstance(revision, Mapping) else ""
            imported_system_id = str(revision.get("system_id") or system_id) if isinstance(revision, Mapping) else system_id
            if not revision_id:
                raise RuntimeError(f"AISL publication import returned no revision_id for {repository_id!r}")
            current[repository_id] = AislBinding(repository_id, imported_system_id, revision_id)
            actions.append({
                "repository_id": repository_id,
                "status": "prepared",
                "system_id": imported_system_id,
                "revision_id": revision_id,
                "kcp_repository_id": repository_runtime_id,
                "kcp_job_id": job_id,
                "publication_bundle_sha256": bundle.get("downloaded_sha256") or bundle.get("sha256"),
            })

    final_bindings = BindingIndex([current[repository_id] for repository_id in repository_ids])
    after = check_interaction_lineage(
        topology,
        edge_id=edge_id,
        bindings=final_bindings,
        gateway=readiness_gateway,
        transport_roles=transport_roles,
    )
    status = "prepared" if after.get("status") == "ready" else "failed"
    return {
        "format": PREPARATION_FORMAT,
        "status": status,
        "topology_id": str(topology.get("topology_id") or ""),
        "edge_id": edge_id,
        "repositories": sorted(actions, key=lambda item: str(item.get("repository_id") or "")),
        "bindings": _bindings_payload(final_bindings, repository_ids),
        "readiness_before": before,
        "readiness_after": after,
        "summary": {
            "prepared_repository_count": sum(1 for item in actions if item.get("status") == "prepared"),
            "reused_repository_count": sum(1 for item in actions if item.get("status") == "already_prepared"),
        },
    }
