"""Thin public Knowledge API transport. No source parsing or semantic reconstruction."""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote

import httpx


class KnowledgeError(RuntimeError):
    pass


class Gateway:
    def __init__(self, base_url: str, system_id: str, revision_id: str, *, client: httpx.Client | None = None):
        if not system_id.strip() or not revision_id.strip() or revision_id in {'latest', 'active'}:
            raise ValueError('Exact nonempty system_id and immutable revision_id are mandatory')
        self.system_id = system_id
        self.revision_id = revision_id
        self._owned = client is None
        self.client = client or httpx.Client(base_url=base_url.rstrip('/'), timeout=60)
        self.path = f'/api/knowledge/v1/systems/{quote(system_id, safe="")}'

    def close(self) -> None:
        if self._owned:
            self.client.close()

    def get(self, suffix: str, **params: Any) -> dict[str, Any]:
        response = self.client.get(f'{self.path}{suffix}', params={'revision_id': self.revision_id, **params})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KnowledgeError(f'Knowledge API {suffix}: HTTP {response.status_code}: {response.text[:320]}') from exc
        data = response.json()
        if not isinstance(data, dict):
            raise KnowledgeError(f'Knowledge API {suffix} returned non-object')
        return data

    def all_items(self, suffix: str, *, limit: int = 500, **params: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fail closed rather than silently truncating a paginated search/graph."""
        items: list[dict[str, Any]] = []
        first: dict[str, Any] = {}
        offset = 0
        for _ in range(100_000):
            payload = self.get(suffix, offset=offset, limit=limit, **params)
            page_items = payload.get('items')
            if not isinstance(page_items, list) or not all(isinstance(i, dict) for i in page_items):
                raise KnowledgeError(f'Knowledge API {suffix}: malformed items')
            if not first:
                first = {key: value for key, value in payload.items() if key not in {'items', 'page'}}
            items.extend(page_items)
            page = payload.get('page')
            if not isinstance(page, Mapping) or 'total' not in page:
                raise KnowledgeError(f'Knowledge API {suffix}: missing pagination total')
            total = int(page['total'])
            if len(items) >= total:
                if len(items) != total:
                    raise KnowledgeError(f'Knowledge API {suffix}: total differs from received items')
                return items, first
            if not page_items:
                raise KnowledgeError(f'Knowledge API {suffix}: truncated page at offset {offset}/{total}')
            offset += len(page_items)
        raise KnowledgeError('Excessive number of pages; refused incomplete retrieval')

    def relations(self) -> list[dict[str, Any]]:
        return self.all_items('/sql/relations', view='all', include_fields='true', max_evidence_per_role=20)[0]

    def materializations(self) -> list[dict[str, Any]]:
        return self.all_items('/sql/relation-materializations')[0]

    def downstream_candidates(self, source_relation: str, *, source_column: str | None = None) -> dict[str, Any]:
        """Page all public target candidates, without promoting them to edges."""
        params: dict[str, Any] = {'source_relation': [source_relation], 'surface': 'all'}
        if source_column:
            params['source_column'] = [source_column]
        accumulated: list[dict[str, Any]] = []
        first: dict[str, Any] = {}
        offset = 0
        for _ in range(100_000):
            page = self.get('/sql/target-candidates', **params, offset=offset, limit=100)
            rows = page.get('candidates')
            if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
                raise KnowledgeError('Target discovery API response has malformed candidates')
            if not first:
                first = {k: v for k, v in page.items() if k != 'candidates'}
            accumulated.extend(rows)
            count = int(page.get('candidate_count', len(rows)))
            if int(first.get('candidate_count', count)) != count:
                raise KnowledgeError('Target discovery count changed between pages')
            if len(accumulated) == count:
                first['candidates'] = accumulated
                first['returned_count'] = len(accumulated)
                return first
            if not rows or len(accumulated) > count:
                raise KnowledgeError(f'Target discovery truncated: {len(accumulated)} of {count}')
            offset += len(rows)
        raise KnowledgeError('Excessive candidate pages; refused incomplete retrieval')

    def target_lineage(self, relation: str, *, column: str | None = None, repo_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {'target_relation': relation, 'include_gaps': True, 'max_gaps': 500}
        if column:
            params['target_column'] = column
        if repo_id:
            params['repo_id'] = repo_id
        items, envelope = self.all_items('/sql/target-column-lineage', **params)
        # First-page metadata (e.g. limited gaps) is not full evidence if server says truncated.
        envelope['items'] = items
        envelope['item_count'] = len(items)
        if envelope.get('gaps_truncated'):
            envelope.setdefault('limitations', []).append('server_gaps_truncated')
        return envelope

    def query_context(self, query_id: str, *, repo_id: str, scope_id: str | None = None) -> dict[str, Any]:
        if not query_id or not repo_id:
            raise ValueError('query_id and repo_id required for exact context selection')
        params = {'query_id': query_id, 'repo_id': repo_id}
        if scope_id:
            params['scope_id'] = scope_id
        return self.get('/sql/query-context', **params)

    def declared_records(self, kind: str) -> list[dict[str, Any]]:
        """Read published declared model dataset with full server pagination."""
        if kind not in {'types', 'fields'}:
            raise ValueError('Unsupported declared record kind')
        return self.all_items(f'/data-model/declared-dataset/{kind}')[0]

    def tsa_mapping_records(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read exact TSA mapping observations, never infer bindings from names."""
        import urllib.parse
        snapshot = self.get(f'/revisions/{urllib.parse.quote(self.revision_id, safe="")}')
        products = [p for p in snapshot.get('knowledge_artifacts', [])
                    if p.get('model_kind') == 'logical-physical-mapping-evidence'
                    and 'common.observed-record-set' in p.get('capabilities', [])]
        if len(products) != 1:
            raise KnowledgeError(f'TSA mapping record product must be unique, got {len(products)}')
        artifact = urllib.parse.quote(products[0]['artifact_id'], safe='')
        suffix = f'/observed-records/{artifact}'
        fields = self.all_items(suffix, item_kind='field_mapping')[0]
        entities = self.all_items(suffix, item_kind='entity_mapping')[0]
        return fields, entities
