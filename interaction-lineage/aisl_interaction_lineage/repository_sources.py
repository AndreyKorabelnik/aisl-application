"""Bounded source registration bridge: Topology Git facts -> existing KCP registry.

No Git discovery, clones, Framework analysis, or semantic source selection here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

MANIFEST_FORMAT = "repository-inventory-remote-batch-manifest/v7"
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_GOOD = {"completed", "reused"}


@dataclass(frozen=True)
class InventoryRemoteSource:
    repository_id: str
    repository_url: str
    resolved_commit: str
    requested_ref: str | None
    manifest_path: str


def _safe_git_url(value: str) -> bool:
    if not value or any(ord(ch) < 33 for ch in value):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme in {"https", "http", "ssh"} and bool(parsed.hostname)
            and not parsed.username and not parsed.password and not parsed.fragment
            and not parsed.query and all(part not in {".", ".."} for part in parsed.path.split("/")))


def load_inventory_remote_sources(
    paths: Sequence[str], *, selected_ids: set[str] | None = None
) -> dict[str, InventoryRemoteSource]:
    """Use exact Inventory batch records, never guess remote URLs from names."""
    sources: dict[str, InventoryRemoteSource] = {}
    for entry in paths:
        path = Path(entry).expanduser().resolve()
        if path.is_dir():
            path /= "remote_batch_manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping) or payload.get("format") != MANIFEST_FORMAT:
            raise ValueError(f"expected {MANIFEST_FORMAT}: {path}")
        for row in payload.get("repository_results") or ():
            if not isinstance(row, Mapping):
                raise ValueError(f"invalid Inventory repository row: {path}")
            if str(row.get("status") or "") not in _GOOD:
                continue
            repo = str(row.get("repository_id") or "").strip()
            if selected_ids is not None and repo not in selected_ids:
                continue
            url = str(row.get("repository_url") or "").strip()
            sha = str(row.get("resolved_commit") or "").strip().lower()
            ref = str(row.get("requested_ref") or "").strip() or None
            if not repo or not re.fullmatch(r"[a-z0-9_]+", repo) or not _safe_git_url(url) or not _SHA.fullmatch(sha):
                raise ValueError(f"incomplete/unsafe successful Inventory source: {repo!r} in {path}")
            source = InventoryRemoteSource(repo, url, sha, ref, str(path))
            if repo in sources and sources[repo] != source:
                raise ValueError(f"ambiguous Inventory repository_id across manifests: {repo}")
            sources[repo] = source
    return sources


def load_topology_remote_sources(
    topology: Mapping[str, Any], *, selected_ids: set[str]
) -> dict[str, InventoryRemoteSource]:
    """Use only observed URL/commit from selected Topology v5 repositories.

    Missing commit permits analysis of HEAD, never snapshot-parity claims. Missing
    URLs, unsafe URLs or duplicate repository IDs fail closed.
    Git-host authorization belongs exclusively to the KCP source-acquisition policy.
    """
    repositories: dict[str, InventoryRemoteSource] = {}
    for row in topology.get("repositories") or []:
        if not isinstance(row, Mapping):
            raise ValueError("topology repositories must be objects")
        repo = str(row.get("repository_id") or "").strip()
        if repo not in selected_ids:
            continue
        if repo in repositories:
            raise ValueError(f"duplicate selected topology repository: {repo}")
        url = str(row.get("repository_url") or "").strip()
        commit = str(row.get("resolved_commit") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_]+", repo):
            raise ValueError(f"invalid selected topology repository identity: {repo}")
        if not url:
            # Already published AISL knowledge might make registration unnecessary.
            # If preparation later needs this source, registrar.ensure fails closed.
            continue
        if not _safe_git_url(url):
            raise ValueError(f"unsafe Git URL for selected topology repository: {repo}")
        if urlsplit(url).scheme != "https":
            raise ValueError(f"Git source requires HTTPS topology repository_url: {repo}")
        if commit and not _SHA.fullmatch(commit):
            raise ValueError(f"invalid topology Git commit for repository: {repo}")
        repositories[repo] = InventoryRemoteSource(repo, url, commit, None, "topology-v5")
    return repositories


class KcpRepositoryRegistrar:
    """Register only selected source ids. Never trigger a checkout during discovery."""

    def __init__(self, base_url: str, sources: Mapping[str, InventoryRemoteSource], *, timeout_sec: float = 30.0):
        self.base_url = base_url.strip().rstrip("/")
        if not self.base_url:
            raise ValueError("KCP base URL must not be empty")
        self.sources = sources
        self.timeout_sec = timeout_sec
        self._registered: dict[str, dict[str, Any]] = {}

    def _api(self, path: str, *, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + path, data=data, method="POST" if data is not None else "GET",
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"KCP repository API HTTP {exc.code} at {path}") from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(f"KCP repository API unavailable: {type(exc).__name__}") from exc
        if not isinstance(result, Mapping):
            raise RuntimeError("KCP repository API returned non-object response")
        return result

    def _matches(self, analysis_id: str, expected_url: str) -> list[Mapping[str, Any]]:
        offset = 0
        matches: list[Mapping[str, Any]] = []
        while True:
            result = self._api(f"/api/v1/repositories?offset={offset}&limit=500")
            items = result.get("items")
            page = result.get("page")
            if not isinstance(items, list) or not isinstance(page, Mapping):
                raise RuntimeError("KCP repository listing has unsupported shape")
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
                recorded_id = str(metadata.get("analysis_repository_id") or "").strip()
                if not recorded_id:
                    recorded_id = re.sub(r"[^A-Za-z0-9]+", "_", str(item.get("name") or "")).strip("_").lower()[:120]
                if recorded_id == analysis_id:
                    matches.append(item)
                elif str(item.get("location") or "") == expected_url:
                    raise ValueError(f"same Git URL registered with conflicting analysis_repository_id: {analysis_id}")
            offset += len(items)
            total = page.get("total")
            if not isinstance(total, int) or total < 0 or (offset < total and not items):
                raise RuntimeError("KCP repository pagination is invalid")
            if offset >= total:
                break
        return matches

    def ensure(self, repository_id: str) -> dict[str, Any]:
        if repository_id in self._registered:
            return self._registered[repository_id]
        source = self.sources.get(repository_id)
        if source is None:
            raise ValueError(f"selected repository lacks verified Inventory remote source: {repository_id}")
        matches = self._matches(repository_id, source.repository_url)
        if not matches:
            remote: dict[str, Any] = {"location": source.repository_url, "name": repository_id}
            if source.requested_ref:
                remote["tracked_ref"] = {"kind": "branch", "name": source.requested_ref}
            result = self._api("/api/v1/repositories/discover", payload={
                "remotes": [remote], "defer_checkout": True, "refresh": False,
            })
            rows = result.get("repositories")
            if not isinstance(rows, list) or len(rows) != 1 or result.get("discovered_count") != 1 or result.get("warnings"):
                raise RuntimeError(f"KCP registration did not confirm exactly one repository: {repository_id}")
            matches = self._matches(repository_id, source.repository_url)
        if len(matches) != 1:
            raise ValueError(f"KCP analysis_repository_id ambiguous: {repository_id}, count={len(matches)}")
        item = matches[0]
        if str(item.get("location") or "") != source.repository_url:
            raise ValueError(f"KCP repository URL conflicts with Inventory source: {repository_id}")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        tracked = metadata.get("tracked_ref") if isinstance(metadata.get("tracked_ref"), Mapping) else {}
        expected = {"kind": "branch", "name": source.requested_ref} if source.requested_ref else {"kind": "head", "name": None}
        if source.requested_ref and (str(tracked.get("kind") or "") != expected["kind"]
                                     or (tracked.get("name") or None) != expected["name"]):
            raise ValueError(f"KCP tracked Git ref conflicts with observed source: {repository_id}")
        revision = str(item.get("revision") or "").strip().lower()
        if source.resolved_commit and revision and revision != source.resolved_commit:
            raise ValueError(f"KCP materialized revision conflicts with Inventory commit: {repository_id}")
        evidence = {
            "repository_id": repository_id,
            "kcp_repository_id": str(item.get("repository_id") or ""),
            "inventory_resolved_commit": source.resolved_commit,
            "kcp_materialized_commit": revision or None,
            "revision_verified": bool(source.resolved_commit and revision == source.resolved_commit),
            "kcp_tracked_ref": dict(tracked),
            "status": ("registered_exact_snapshot" if source.resolved_commit and revision
                       else "registered_ref_unverified" if source.resolved_commit
                       else "registered_git_revision_unverified_against_topology" if revision
                       else "registered_ref_unverified_against_topology"),
        }
        if not evidence["kcp_repository_id"]:
            raise RuntimeError("KCP registered repository has no repository_id")
        self._registered[repository_id] = evidence
        return evidence
