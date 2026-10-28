"""Explicit, fail-closed transfer of KCP bundles to the canonical AISL Server importer.

The consumer orchestrates; KCP owns only artifacts, Server owns all publication
semantics.  No local knowledge-api CLI, local database or second importer.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from .contracts import AislBinding

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_ARTIFACT = re.compile(r"/api/v1/artifacts/(artifact-[A-Za-z0-9-]+)/download\Z")
_MAX_BYTES = 256 * 1024 * 1024


class HttpPublicationGateway:
    """Bounded HTTP adapter; token only travels to the configured AISL Server."""

    def __init__(self, *, kcp_base_url: str, aisl_base_url: str, token: str,
                 timeout_sec: float = 180.0):
        self.kcp_url = kcp_base_url.rstrip("/")
        self.aisl_url = aisl_base_url.rstrip("/")
        self.token = token
        self.timeout_sec = timeout_sec
        kcp = urlsplit(self.kcp_url)
        server = urlsplit(self.aisl_url)
        if (kcp.scheme not in {"http", "https"} or server.scheme not in {"http", "https"}
                or not kcp.hostname or not server.hostname or kcp.username or kcp.password
                or server.username or server.password or kcp.query or server.query
                or kcp.fragment or server.fragment):
            raise ValueError("KCP and AISL base URLs must be safe HTTP(S) origins")
        if server.scheme == "http" and server.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote AISL publication requires HTTPS to protect the token")

    def _download(self, item: Mapping[str, Any]) -> bytes:
        path = str(item.get("download_path") or "")
        artifact_id = str(item.get("artifact_id") or "")
        if not _ARTIFACT.fullmatch(path) or _ARTIFACT.fullmatch(path).group(1) != artifact_id:
            raise RuntimeError("KCP publication reference has unsafe artifact path")
        digest = str(item.get("sha256") or "").lower()
        if not _SHA.fullmatch(digest):
            raise RuntimeError("KCP publication reference lacks a valid SHA-256")
        request = Request(self.kcp_url + path, headers={"Accept": "application/zip"})
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                blob = response.read(_MAX_BYTES + 1)
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError(f"KCP artifact download unavailable: {type(exc).__name__}") from exc
        if not blob or len(blob) > _MAX_BYTES or hashlib.sha256(blob).hexdigest() != digest:
            raise RuntimeError("KCP artifact size/digest verification failed")
        return blob

    def _import(self, path: str, body: bytes) -> Mapping[str, Any]:
        if not self.token:
            raise RuntimeError("AISL publication token is not configured")
        request = Request(self.aisl_url + path, data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/zip",
            "Authorization": "Bearer " + self.token,
            "X-Bundle-SHA256": hashlib.sha256(body).hexdigest(),
        })
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                raw = response.read(1_000_001)
        except HTTPError as exc:
            raise RuntimeError(f"AISL publication endpoint rejected request: HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(f"AISL publication endpoint unavailable: {type(exc).__name__}") from exc
        if len(raw) > 1_000_000:
            raise RuntimeError("AISL publication response exceeds limit")
        result = json.loads(raw)
        if not isinstance(result, Mapping):
            raise RuntimeError("AISL publication response is not a JSON object")
        return result

    def publish(self, *, repository_id: str, result: Mapping[str, Any],
                expected_commit: str = "") -> AislBinding:
        """Explicitly publish both bundles, returning only Server-issued pin IDs."""
        if result.get("outcome") != "awaiting_publication":
            raise RuntimeError("KCP result is not awaiting publication")
        final = result.get("final_readiness")
        if not isinstance(final, Mapping) or final.get("state") != "awaiting_publication":
            raise RuntimeError("KCP result has no publication-ready state")
        context = final.get("preparation_context")
        if not isinstance(context, Mapping):
            raise RuntimeError("KCP did not provide a publication context")
        steps = [row for row in result.get("steps") or () if isinstance(row, Mapping)
                 and row.get("status") == "awaiting_publication"]
        if len(steps) != 1:
            raise RuntimeError("KCP must provide exactly one publication-ready step")
        refs = steps[0].get("publication_refs")
        if not isinstance(refs, list) or len(refs) != 2:
            raise RuntimeError("KCP must provide exactly two publication artifacts")
        by_kind = {str(item.get("kind") or ""): item for item in refs if isinstance(item, Mapping)}
        if set(by_kind) != {"publication_bundle", "attribute_catalogue_bundle"}:
            raise RuntimeError("KCP publication artifact types are unsupported")
        if str(context.get("publication_bundle_sha256") or "") != by_kind["publication_bundle"]["sha256"]:
            raise RuntimeError("KCP publication bundle identity differs across response")
        source = context.get("source_provenance_refs") or steps[0].get("source_provenance_refs") or ()
        source = [x for x in source if isinstance(x, Mapping) and x.get("source_kind") == "repository"
                  and x.get("repository_id") == repository_id]
        if expected_commit:
            sha = expected_commit.lower()
            if not _COMMIT.fullmatch(sha) or len(source) != 1 or str(source[0].get("revision") or "").lower() != sha:
                raise RuntimeError("KCP source does not match exact Inventory/Topology Git commit")
        elif source and (len(source) != 1 or not _COMMIT.fullmatch(str(source[0].get("revision") or "").lower())):
            raise RuntimeError("KCP returned an unverified Git source commit")
        # Do not hand out a fake revision if the second import fails.  Both imports
        # are idempotent, so a retry can safely complete an interrupted publication.
        main = self._import("/api/knowledge/v1/publications/import", self._download(by_kind["publication_bundle"]))
        if main.get("status") not in {"published", "already_published"}:
            raise RuntimeError("AISL did not confirm publication")
        system_id = str(main.get("system_id") or "")
        revision_id = str(main.get("revision_id") or "")
        if not system_id or not revision_id or revision_id.lower() in {"active", "latest"}:
            raise RuntimeError("AISL publication did not return immutable identifiers")
        if system_id != str(context.get("target_system_id") or ""):
            raise RuntimeError("AISL published a different target system")
        catalogue = self._import("/api/knowledge/v1/publications/import-catalogue",
                                 self._download(by_kind["attribute_catalogue_bundle"]))
        if catalogue.get("status") not in {"imported", "already_imported"}:
            raise RuntimeError("AISL did not confirm attribute catalogue import")
        if (str(catalogue.get("system_id") or "") != system_id
                or str(catalogue.get("revision_id") or "") != revision_id):
            raise RuntimeError("AISL catalogue identity differs from the published Knowledge revision")
        return AislBinding(repository_id=repository_id, system_id=system_id, revision_id=revision_id,
                           selected_repo_ids=tuple(str(x) for x in context.get("selected_repo_ids") or () if x))
