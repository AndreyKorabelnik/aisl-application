from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

BINDINGS_SCHEMA_VERSION = "interaction-lineage-aisl-bindings/v1"
OUTPUT_FORMAT = "interaction-attribute-lineage/v1"


def _text(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


@dataclass(frozen=True, slots=True)
class AislBinding:
    repository_id: str
    system_id: str
    revision_id: str
    selected_repo_ids: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AislBinding":
        repository_id = _text(payload.get("repository_id"), "repository_id")
        system_id = _text(payload.get("system_id"), "system_id")
        revision_id = _text(payload.get("revision_id"), "revision_id")
        if revision_id.casefold() in {"active", "latest"}:
            raise ValueError("revision_id must be an exact immutable revision, not active/latest")
        raw_selected = payload.get("selected_repo_ids")
        selected_repo_ids = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (raw_selected if isinstance(raw_selected, list) else ())
                if str(value).strip()
            )
        )
        return cls(
            repository_id=repository_id,
            system_id=system_id,
            revision_id=revision_id,
            selected_repo_ids=selected_repo_ids,
        )

    def query_repo_ids(self, fallback_repository_id: str | None = None) -> tuple[str, ...]:
        fallback = str(fallback_repository_id or self.repository_id).strip()
        values = list(self.selected_repo_ids)
        if fallback and fallback not in values:
            values.insert(0, fallback)
        return tuple(values)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "repository_id": self.repository_id,
            "system_id": self.system_id,
            "revision_id": self.revision_id,
        }
        if self.selected_repo_ids:
            payload["selected_repo_ids"] = list(self.selected_repo_ids)
        return payload


class BindingIndex:
    def __init__(self, bindings: list[AislBinding]) -> None:
        by_repo: dict[str, AislBinding] = {}
        for binding in bindings:
            if binding.repository_id in by_repo:
                raise ValueError(f"duplicate AISL binding for repository: {binding.repository_id}")
            by_repo[binding.repository_id] = binding
        self._by_repo = by_repo

    def find(self, repository_id: str) -> AislBinding | None:
        return self._by_repo.get(repository_id)

    def require(self, repository_id: str) -> AislBinding:
        try:
            return self._by_repo[repository_id]
        except KeyError as exc:
            raise ValueError(f"missing AISL binding for repository: {repository_id}") from exc


def load_bindings(path: str | Path) -> BindingIndex:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("bindings root must be an object")
    if payload.get("schema_version") != BINDINGS_SCHEMA_VERSION:
        nested = payload.get("bindings")
        if isinstance(nested, Mapping) and nested.get("schema_version") == BINDINGS_SCHEMA_VERSION:
            payload = nested
        else:
            raise ValueError(f"unsupported bindings schema_version: {payload.get('schema_version')!r}")
    rows = payload.get("repositories")
    if not isinstance(rows, list):
        raise ValueError("bindings.repositories must be an array")
    return BindingIndex([AislBinding.from_payload(item) for item in rows if isinstance(item, Mapping)])
