"""Command-scoped reuse of reads from immutable, pinned AISL revisions.

Only used by read-only batch commands. `prepare` can publish revisions while
running and therefore intentionally bypasses this cache.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .aisl import AislReadinessGateway
from .contracts import AislBinding


_NON_CACHEABLE = frozenset({
    "unavailable", "server_unavailable", "api_error", "contract_error",
    "revision_unavailable", "service_unavailable", "timeout", "failed", "error",
})


class BatchCachingGateway:
    """Reuse identical queries within *one* read-only CLI batch, not across runs."""

    def __init__(self, delegate: AislReadinessGateway) -> None:
        self._delegate = delegate
        self._cached: dict[tuple[Any, ...], Mapping[str, Any]] = {}
        self._hits: Counter[str] = Counter()
        self._backend_calls: Counter[str] = Counter()

    @staticmethod
    def _safe_result(value: Mapping[str, Any]) -> bool:
        nested = value.get("result")
        result = nested if isinstance(nested, Mapping) else value
        status = str(result.get("status") or "").lower()
        return bool(status) and status not in _NON_CACHEABLE and "error" not in result and "error" not in value

    def _read(self, kind: str, key: tuple[Any, ...], get_response, *, cacheable=None) -> Mapping[str, Any]:
        full_key = (kind, *key)
        if full_key in self._cached:
            self._hits[kind] += 1
            return deepcopy(self._cached[full_key])
        self._backend_calls[kind] += 1
        value = get_response()
        if isinstance(value, Mapping) and (cacheable(value) if cacheable is not None else self._safe_result(value)):
            self._cached[full_key] = deepcopy(value)
        return value

    def revision_status(self, binding: AislBinding) -> Mapping[str, Any]:
        return self._read(
            "revision_status", (binding.system_id, binding.revision_id),
            lambda: self._delegate.revision_status(binding),
            cacheable=lambda response: response.get("status") == "ready",
        )

    def resolve_attribute_paths(
        self, binding: AislBinding, *, source: str,
        selected_repo_ids: Sequence[str], direction: str,
    ) -> Mapping[str, Any]:
        return self._read(
            "resolve_attribute_paths",
            (binding.system_id, binding.revision_id, binding.repository_id,
             source, tuple(selected_repo_ids), direction),
            lambda: self._delegate.resolve_attribute_paths(
                binding, source=source, selected_repo_ids=selected_repo_ids, direction=direction,
            ),
        )

    def list_repository_value_nodes(
        self, binding: AislBinding, *, repository_id: str,
        node_kind: str | None = None, operation: str | None = None,
        max_results: int = 500, page_token: str = "",
    ) -> Mapping[str, Any]:
        def complete_page(response: Mapping[str, Any]) -> bool:
            nested = response.get("result")
            result = nested if isinstance(nested, Mapping) else response
            return (isinstance(result.get("items"), list)
                    and "error" not in response and "error" not in result
                    and str(result.get("status") or "").lower() not in _NON_CACHEABLE)

        return self._read(
            "list_repository_value_nodes",
            (binding.system_id, binding.revision_id, repository_id,
             node_kind, operation, max_results, page_token),
            lambda: self._delegate.list_repository_value_nodes(
                binding, repository_id=repository_id, node_kind=node_kind,
                operation=operation, max_results=max_results, page_token=page_token,
            ),
            cacheable=complete_page,
        )

    def statistics(self) -> dict[str, Any]:
        kinds = ("revision_status", "resolve_attribute_paths", "list_repository_value_nodes")
        return {
            "backend_call_count": sum(self._backend_calls.values()),
            "cache_hit_count": sum(self._hits.values()),
            "cache_entry_count": len(self._cached),
            "by_operation": {
                k: {"backend_calls": self._backend_calls[k], "cache_hits": self._hits[k]}
                for k in kinds
            },
        }
