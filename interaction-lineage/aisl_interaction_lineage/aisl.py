from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import quote

from .contracts import AislBinding


class AislPathGateway(Protocol):
    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]: ...


class KnowledgeApiGateway:
    """Thin caller of the public revision-pinned Knowledge API."""

    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        from aisl_sdk import AislClient

        self._client = AislClient(base_url, timeout_sec=timeout_sec)

    def close(self) -> None:
        self._client.close()

    def resolve_attribute_paths(
        self,
        binding: AislBinding,
        *,
        source: str,
        selected_repo_ids: Sequence[str],
        direction: str,
    ) -> Mapping[str, Any]:
        system_id = quote(binding.system_id, safe="")
        path = f"/api/knowledge/v1/systems/{system_id}/attribute-paths/resolve"
        payload = {
            "source": source,
            "selected_repo_ids": list(selected_repo_ids),
            "max_hops": 30,
            "max_paths": 50,
            "max_branching": 50,
            "minimum_confidence": "probable",
            "knowledge_view": "working",
        }
        if direction != "forward":
            payload["direction"] = direction
        return self._client.post_json(path, payload, params={"revision_id": binding.revision_id})
