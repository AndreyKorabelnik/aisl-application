from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import quote

from .contracts import RevisionBinding


class LineageGateway(Protocol):
    def search_declared_objects(
        self, binding: RevisionBinding, *, search: str, include_fields: bool = True
    ) -> Sequence[Mapping[str, Any]]: ...

    def get_data_model_object_context(
        self, binding: RevisionBinding, *, object_id: str
    ) -> Mapping[str, Any]: ...

    def find_tsa_field_mappings(
        self, binding: RevisionBinding, *, logical_type_name: str, logical_field_name: str
    ) -> Sequence[Mapping[str, Any]]: ...

    def find_sql_target_candidates(
        self,
        binding: RevisionBinding,
        *,
        source_relations: Sequence[str],
        source_column: str,
        limit: int = 100,
    ) -> Mapping[str, Any]: ...

    def get_sql_target_column_lineage(
        self,
        binding: RevisionBinding,
        *,
        target_relation: str,
        repo_id: str | None,
        limit: int = 500,
    ) -> Mapping[str, Any]: ...

    def list_sql_relation_materializations(
        self, binding: RevisionBinding
    ) -> Sequence[Mapping[str, Any]]: ...


class KnowledgeApiGateway:
    """Thin public-AISL gateway. It adds no source parsing or lineage semantics."""

    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        from aisl_sdk import AislClient

        self._client = AislClient(base_url, timeout_sec=timeout_sec)

    def close(self) -> None:
        self._client.close()

    def _revision(self, binding: RevisionBinding):
        return self._client.revision(binding.system_id, binding.revision_id)

    def search_declared_objects(
        self, binding: RevisionBinding, *, search: str, include_fields: bool = True
    ) -> Sequence[Mapping[str, Any]]:
        cache = getattr(self, "_declared_object_search_cache", None)
        if cache is None:
            cache = {}
            self._declared_object_search_cache = cache
        key = (binding.system_id, binding.revision_id, search, bool(include_fields))
        if key not in cache:
            cache[key] = list(self._revision(binding).search_declared_data_objects(
                search=search,
                include_fields=include_fields,
                page_size=100,
                max_results=1000,
            ))
        return cache[key]

    def get_data_model_object_context(
        self, binding: RevisionBinding, *, object_id: str
    ) -> Mapping[str, Any]:
        cache = getattr(self, "_data_model_context_cache", None)
        if cache is None:
            cache = {}
            self._data_model_context_cache = cache
        key = (binding.system_id, binding.revision_id, object_id)
        if key not in cache:
            cache[key] = self._revision(binding).get_data_model_object_context(object_id)
        return cache[key]

    def find_tsa_field_mappings(
        self, binding: RevisionBinding, *, logical_type_name: str, logical_field_name: str
    ) -> Sequence[Mapping[str, Any]]:
        revision = self._revision(binding)
        products = [
            product
            for product in revision.list_products(capability="common.observed-record-set")
            if product.model_kind == "logical-physical-mapping-evidence"
        ]
        if len(products) != 1:
            raise RuntimeError(
                "TSA revision must expose exactly one logical-physical-mapping-evidence "
                f"observed product; got {len(products)}"
            )
        artifact_id = products[0].artifact_id
        system_id = quote(binding.system_id, safe="")
        artifact = quote(artifact_id, safe="")
        path = f"/api/knowledge/v1/systems/{system_id}/observed-records/{artifact}"
        payload = self._client.get_json(
            path,
            params={
                "revision_id": binding.revision_id,
                "item_kind": "field_mapping",
                "filter_path": ["/logical_type_name", "/logical_field_name"],
                "filter_value": [logical_type_name, logical_field_name],
                "offset": 0,
                "limit": 100,
            },
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeError("observed-record response has no items array")

        # A field_mapping deliberately references its owning entity_mapping by ID
        # instead of duplicating the physical table identity. Resolve that explicit
        # revision-local reference through the same public observed-record API.
        result: list[dict[str, Any]] = []
        for raw_item in items:
            if not isinstance(raw_item, Mapping):
                continue
            item = dict(raw_item)
            field_payload = item.get("payload")
            if not isinstance(field_payload, Mapping):
                result.append(item)
                continue
            normalized_payload = dict(field_payload)
            entity_mapping_id = str(normalized_payload.get("entity_mapping_id") or "").strip()
            if entity_mapping_id and not normalized_payload.get("physical_table_name"):
                entity_response = self._client.get_json(
                    path,
                    params={
                        "revision_id": binding.revision_id,
                        "item_kind": "entity_mapping",
                        "filter_path": ["/mapping_id"],
                        "filter_value": [entity_mapping_id],
                        "offset": 0,
                        "limit": 2,
                    },
                )
                entity_items = entity_response.get("items")
                exact_entities = [
                    dict(entity)
                    for entity in entity_items or ()
                    if isinstance(entity, Mapping)
                ]
                if len(exact_entities) == 1:
                    entity_payload = exact_entities[0].get("payload")
                    if isinstance(entity_payload, Mapping):
                        physical_table_name = str(entity_payload.get("physical_table_name") or "").strip()
                        if physical_table_name:
                            normalized_payload["physical_table_name"] = physical_table_name
                        item["entity_mapping_record"] = exact_entities[0]
            item["payload"] = normalized_payload
            result.append(item)
        return result

    def find_sql_target_candidates(
        self,
        binding: RevisionBinding,
        *,
        source_relations: Sequence[str],
        source_column: str,
        limit: int = 100,
    ) -> Mapping[str, Any]:
        cache = getattr(self, "_target_candidate_cache", None)
        if cache is None:
            cache = {}
            self._target_candidate_cache = cache
        key = (binding.system_id, binding.revision_id, tuple(source_relations), source_column, int(limit))
        if key not in cache:
            system_id = quote(binding.system_id, safe="")
            path = f"/api/knowledge/v1/systems/{system_id}/sql/target-candidates"
            cache[key] = self._client.get_json(
                path,
                params={
                    "revision_id": binding.revision_id,
                    "source_relation": list(source_relations),
                    "source_column": [source_column],
                    # A logically published consumer target can remain outside the
                    # strict published surface when its physical relation is ambiguous.
                    # Discovery may therefore inspect all public candidates; the builder
                    # still requires exact source evidence plus confirmed lineage.
                    "surface": "all",
                    "offset": 0,
                    "limit": limit,
                },
            )
        return cache[key]

    def get_sql_target_column_lineage(
        self,
        binding: RevisionBinding,
        *,
        target_relation: str,
        repo_id: str | None,
        limit: int = 500,
    ) -> Mapping[str, Any]:
        cache = getattr(self, "_target_column_lineage_cache", None)
        if cache is None:
            cache = {}
            self._target_column_lineage_cache = cache
        key = (binding.system_id, binding.revision_id, target_relation, repo_id or "")
        if key in cache:
            return cache[key]

        system_id = quote(binding.system_id, safe="")
        path = f"/api/knowledge/v1/systems/{system_id}/sql/target-column-lineage"
        base_params: dict[str, Any] = {
            "revision_id": binding.revision_id,
            "target_relation": target_relation,
            "lineage_status": "confirmed",
            "include_gaps": True,
            "max_gaps": 500,
            "limit": min(int(limit), 500),
        }
        if repo_id:
            base_params["repo_id"] = repo_id

        offset = 0
        combined: dict[str, Any] | None = None
        items: list[dict[str, Any]] = []
        while True:
            params = dict(base_params)
            params["offset"] = offset
            payload = self._client.get_json(path, params=params)
            page_items = payload.get("items")
            if not isinstance(page_items, list):
                raise RuntimeError("target-column-lineage response has no items array")
            batch = [dict(item) for item in page_items if isinstance(item, Mapping)]
            if combined is None:
                combined = dict(payload)
            items.extend(batch)
            page = payload.get("page") if isinstance(payload.get("page"), Mapping) else {}
            total = int(page.get("total") or len(items))
            if not batch or len(items) >= total:
                break
            offset += len(batch)
        if combined is None:
            combined = {"items": []}
        combined["items"] = items
        page = dict(combined.get("page") or {})
        page.update({"offset": 0, "limit": len(items), "total": len(items), "has_more": False})
        combined["page"] = page
        cache[key] = combined
        return combined

    def list_sql_relation_materializations(
        self, binding: RevisionBinding
    ) -> Sequence[Mapping[str, Any]]:
        cache = getattr(self, "_relation_materialization_cache", None)
        if cache is None:
            cache = {}
            self._relation_materialization_cache = cache
        key = (binding.system_id, binding.revision_id)
        if key in cache:
            return cache[key]

        system_id = quote(binding.system_id, safe="")
        path = f"/api/knowledge/v1/systems/{system_id}/sql/relation-materializations"
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._client.get_json(
                path,
                params={
                    "revision_id": binding.revision_id,
                    "offset": offset,
                    "limit": 500,
                },
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise RuntimeError("relation-materializations response has no items array")
            batch = [dict(item) for item in items if isinstance(item, Mapping)]
            rows.extend(batch)
            page = payload.get("page") if isinstance(payload.get("page"), Mapping) else {}
            total = int(page.get("total") or len(rows))
            if not batch or len(rows) >= total:
                break
            offset += len(batch)
        cache[key] = rows
        return rows
