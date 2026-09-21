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

    def list_repository_value_nodes(
        self,
        binding: AislBinding,
        *,
        repository_id: str,
        node_kind: str | None = None,
        operation: str | None = None,
        max_results: int = 500,
        page_token: str = "",
    ) -> Mapping[str, Any]: ...


class AislReadinessGateway(AislPathGateway, Protocol):
    def revision_status(self, binding: AislBinding) -> Mapping[str, Any]: ...


class KnowledgeApiGateway:
    """Thin caller of the public revision-pinned Knowledge API."""

    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        from aisl_sdk import AislClient

        self._client = AislClient(base_url, timeout_sec=timeout_sec)

    def close(self) -> None:
        self._client.close()

    def revision_status(self, binding: AislBinding) -> Mapping[str, Any]:
        from aisl_sdk import AislApiError, AislContractError, AislTransportError

        try:
            pinned = self._client.revision(binding.system_id, binding.revision_id)
        except AislTransportError as exc:
            return {"status": "server_unavailable", "capabilities": [], "diagnostic": str(exc)}
        except AislApiError as exc:
            status = "missing_revision" if exc.status_code == 404 else "api_error"
            return {"status": status, "capabilities": [], "diagnostic": str(exc)}
        except AislContractError as exc:
            return {"status": "contract_error", "capabilities": [], "diagnostic": str(exc)}
        return {
            "status": "ready",
            "system_id": pinned.system_id,
            "revision_id": pinned.revision_id,
            "capabilities": list(pinned.capabilities),
        }

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

    def list_repository_value_nodes(
        self,
        binding: AislBinding,
        *,
        repository_id: str,
        node_kind: str | None = None,
        operation: str | None = None,
        max_results: int = 500,
        page_token: str = "",
    ) -> Mapping[str, Any]:
        system_id = quote(binding.system_id, safe="")
        path = f"/api/knowledge/v1/systems/{system_id}/repository-value-nodes"
        params: dict[str, Any] = {
            "revision_id": binding.revision_id,
            "repo_id": repository_id,
            "max_results": max_results,
        }
        if node_kind:
            params["node_kind"] = node_kind
        if operation:
            params["operation"] = operation
        if page_token:
            params["page_token"] = page_token
        return self._client.get_json(path, params=params)
