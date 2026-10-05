from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .contracts import RevisionBinding


_DATASET_RECORD_KINDS: dict[str, str] = {
    "types": "types",
    "fields": "fields",
    "effective_fields": "effective_fields",
    "relationships": "relationships",
    "annotations": "annotations",
}

_DATASET_SHAPES: dict[str, frozenset[str]] = {
    "types": frozenset({"type_occurrence_id", "fully_qualified_name", "simple_name"}),
    "fields": frozenset({"field_occurrence_id", "owner_type_occurrence_id", "name"}),
    "effective_fields": frozenset({"effective_field_occurrence_id", "effective_owner_type_occurrence_id", "field_name"}),
    "relationships": frozenset({"relationship_occurrence_id", "source_type_occurrence_id", "target_type_occurrence_id", "field_occurrence_id"}),
    "annotations": frozenset({"annotation_occurrence_id", "target_kind", "target_occurrence_id", "annotation_name"}),
}


class KnowledgeApiGateway:
    """Public AISL access only; no source parsing and no private KLC/DuckDB reads."""

    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        from aisl_sdk import AislClient

        self._client = AislClient(base_url, timeout_sec=timeout_sec)

    def close(self) -> None:
        self._client.close()

    def _revision(self, binding: RevisionBinding):
        return self._client.revision(binding.system_id, binding.revision_id)

    def load_ucp_dataset(self, binding: RevisionBinding) -> dict[str, list[dict[str, Any]]]:
        system_id = quote(binding.system_id, safe="")
        base = f"/api/knowledge/v1/systems/{system_id}/data-model/declared-dataset"
        description = self._client.get_json(base, params={"revision_id": binding.revision_id})
        descriptors = description.get("record_kinds")
        if not isinstance(descriptors, list):
            raise RuntimeError("declared dataset description has no record_kinds")

        available_by_kind: dict[str, Mapping[str, Any]] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping) or not descriptor.get("available"):
                continue
            record_kind = str(descriptor.get("record_kind") or "").strip()
            if record_kind:
                available_by_kind[record_kind] = descriptor

        resolved: dict[str, str] = {}
        for logical_name, required_fields in _DATASET_SHAPES.items():
            canonical_kind = _DATASET_RECORD_KINDS[logical_name]
            canonical = available_by_kind.get(canonical_kind)
            if canonical is not None:
                fields = {str(value) for value in canonical.get("fields") or ()}
                if not required_fields.issubset(fields):
                    raise RuntimeError(
                        f"declared dataset record kind {canonical_kind!r} does not satisfy {logical_name} shape"
                    )
                resolved[logical_name] = canonical_kind
                continue

            matches: list[str] = []
            for record_kind, descriptor in available_by_kind.items():
                fields = {str(value) for value in descriptor.get("fields") or ()}
                if required_fields.issubset(fields):
                    matches.append(record_kind)
            if len(matches) != 1:
                raise RuntimeError(
                    f"declared dataset must expose canonical {canonical_kind!r} or exactly one shape match "
                    f"for {logical_name}; got {matches}"
                )
            resolved[logical_name] = matches[0]

        return {
            logical_name: self._list_declared_records(base, binding, record_kind)
            for logical_name, record_kind in resolved.items()
        }

    def _list_declared_records(
        self, base: str, binding: RevisionBinding, record_kind: str
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        limit = 500
        while True:
            payload = self._client.get_json(
                f"{base}/{quote(record_kind, safe='')}",
                params={"revision_id": binding.revision_id, "offset": offset, "limit": limit},
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise RuntimeError(f"declared dataset {record_kind} response has no items array")
            page = [dict(item) for item in items if isinstance(item, Mapping)]
            result.extend(page)
            if len(page) < limit:
                break
            offset += len(page)
        return result

    def load_tsa_mappings(self, binding: RevisionBinding) -> dict[str, list[dict[str, Any]]]:
        revision = self._revision(binding)
        products = [
            product
            for product in revision.list_products(capability="common.observed-record-set")
            if product.model_kind == "logical-physical-mapping-evidence"
        ]
        if len(products) != 1:
            raise RuntimeError(
                "TSA revision must expose exactly one logical-physical-mapping-evidence observed product; "
                f"got {len(products)}"
            )
        system_id = quote(binding.system_id, safe="")
        artifact_id = quote(products[0].artifact_id, safe="")
        path = f"/api/knowledge/v1/systems/{system_id}/observed-records/{artifact_id}"
        return {
            "entity_mappings": self._list_observed_records(path, binding, "entity_mapping"),
            "field_mappings": self._list_observed_records(path, binding, "field_mapping"),
        }

    def _list_observed_records(
        self, path: str, binding: RevisionBinding, item_kind: str
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        limit = 500
        while True:
            payload = self._client.get_json(
                path,
                params={
                    "revision_id": binding.revision_id,
                    "item_kind": item_kind,
                    "offset": offset,
                    "limit": limit,
                },
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise RuntimeError(f"observed-record {item_kind} response has no items array")
            page = [dict(item) for item in items if isinstance(item, Mapping)]
            result.extend(page)
            if len(page) < limit:
                break
            offset += len(page)
        return result
