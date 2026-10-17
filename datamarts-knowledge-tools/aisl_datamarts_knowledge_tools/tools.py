"""Seven externally advertised tools. All claims link back to PUBLIC AISL evidence."""
from __future__ import annotations

from typing import Any

from .gateway import Gateway
from .search import ObjectSearch, relation_records, declared_model_records, replica_mapping_records


class DataMartsTools:
    def __init__(self, gateway: Gateway, *, model_gateway: Gateway | None = None,
                 replica_gateway: Gateway | None = None):
        self.gateway = gateway
        self.model_gateway = model_gateway
        self.replica_gateway = replica_gateway
        self._relations: list[dict[str, Any]] | None = None
        self._search: ObjectSearch | None = None

    def close(self) -> None:
        if self._search:
            self._search.close()
        self.gateway.close()
        if self.model_gateway: self.model_gateway.close()
        if self.replica_gateway: self.replica_gateway.close()

    def _get_relations(self) -> list[dict[str, Any]]:
        if self._relations is None:
            self._relations = self.gateway.relations()
        return self._relations

    def _search_index(self) -> ObjectSearch:
        if self._search is None:
            sql_rows = relation_records(self._get_relations())
            for row in sql_rows:
                row['system_id'] = self.gateway.system_id
                row['revision_id'] = self.gateway.revision_id
            rows = sql_rows
            if self.model_gateway:
                rows += declared_model_records(
                    self.model_gateway.declared_records('types'),
                    self.model_gateway.declared_records('fields'),
                    system_id=self.model_gateway.system_id, revision_id=self.model_gateway.revision_id)
            if self.replica_gateway:
                mappings, entities = self.replica_gateway.tsa_mapping_records()
                rows += replica_mapping_records(
                    mappings, entities, system_id=self.replica_gateway.system_id,
                    revision_id=self.replica_gateway.revision_id)
            self._search = ObjectSearch(rows)
        return self._search

    def search_objects(self, *, query: str, limit: int = 30, include_fuzzy: bool = True) -> dict[str, Any]:
        result = self._search_index().search(query, limit=limit, include_fuzzy=include_fuzzy)
        result['search_coverage'] = sorted({r['source'] for r in self._search.records})
        result['systems_searched'] = sorted({(r['system_id'], r['revision_id']) for r in self._search.records})
        return result

    def get_object_details(self, *, relation: str, object_id: str | None = None) -> dict[str, Any]:
        """Return all exact-name occurrences across configured revisions, or a stable ID."""
        rows = self._search_index().records
        records = [r for r in rows
                   if (str(r.get('object_id') or '') == object_id if object_id
                       else str(r.get('name') or '').casefold() == relation.casefold())]
        enriched: list[dict[str, Any]] = []
        for match in records:
            item = dict(match)
            # These are explicit, published relationship keys. Do not infer a
            # relationship by name similarity or cross-system coincidence.
            if match.get('kind') == 'replica_table':
                item['published_fields'] = [r for r in rows
                    if r.get('kind') == 'replica_field'
                    and r.get('system_id') == match.get('system_id')
                    and r.get('physical_table') == match.get('name')
                    and r.get('name') == r.get('physical_column')]
            if match.get('kind') == 'declared_type':
                item['published_fields'] = [r for r in rows
                    if r.get('kind') == 'declared_field'
                    and r.get('system_id') == match.get('system_id')
                    and r.get('parent_type') == match.get('qualified_name')]
            enriched.append(item)
        return {'requested_relation': relation, 'requested_object_id': object_id,
                'matches': enriched, 'count': len(enriched),
                'resolution': 'not_found' if not enriched else 'ambiguous' if len(enriched) > 1 else 'candidate',
                'warning': 'Matching names and mapping records are not proof of deployment or all edit locations'}

    def get_attribute_lineage(self, *, relation: str, column: str, repo_id: str | None = None) -> dict[str, Any]:
        return self.gateway.target_lineage(relation, column=column, repo_id=repo_id)

    def get_dependencies(self, *, relation: str, column: str | None = None,
                         repo_id: str | None = None) -> dict[str, Any]:
        """All PUBLISHED upstream target lineage, without synthesizing edges."""
        raw = self.gateway.target_lineage(relation, column=column, repo_id=repo_id)
        edges: list[dict[str, Any]] = []
        seen: set[str] = set()
        for x in raw.get('items', []):
            if not isinstance(x, dict):
                continue
            lid = str(x.get('sql_recursive_column_lineage_id') or '')
            if lid and lid in seen:
                continue
            seen.add(lid)
            edges.append({
                'lineage_id': lid, 'target_relation': x.get('workflow_target_logical_name') or x.get('target_relation_name'),
                'target_column': x.get('target_column'), 'source_relation': x.get('terminal_relation_name'),
                'source_column': x.get('terminal_column'), 'depth': x.get('recursion_depth'),
                'branch_path': x.get('branch_path_json'),
                'transformations': x.get('transformation_path_json'),
                'status': x.get('lineage_status'), 'origin_status': x.get('physical_origin_status'),
                'provenance': {'file': x.get('file'), 'line_start': x.get('line_start'), 'query_id': x.get('query_id')},
            })
        outgoing = self.gateway.downstream_candidates(relation, source_column=column)
        return {'relation': relation, 'column': column, 'edges': edges, 'edge_count': len(edges),
                'downstream_target_candidates': outgoing.get('candidates'),
                'downstream_candidate_count': outgoing.get('candidate_count'),
                'target_resolution': raw.get('target_resolution'), 'gaps': raw.get('gaps'),
                'gaps_truncated': raw.get('gaps_truncated', False),
                'direction': 'upstream_confirmed_or_partial_plus_downstream_discovery_candidates',
                'coverage': 'published_sql_target_column_lineage_and_target_candidate_discovery',
                'limitations': ['Downstream candidates require separate lineage confirmation', 'Does not invent edges across revisions'],
                'complete_public_items': raw.get('item_count') == len(raw.get('items', []))}

    def find_change_locations(self, *, relation: str, column: str | None = None,
                              repo_id: str | None = None) -> dict[str, Any]:
        """Evidence-backed file CANDIDATES, never a definitive edit plan."""
        raw = self.gateway.target_lineage(relation, column=column, repo_id=repo_id)
        files: dict[str, dict[str, Any]] = {}
        for x in raw.get('items') or []:
            if not isinstance(x, dict):
                continue
            f = str(x.get('file') or '').strip()
            if not f:
                continue
            entry = files.setdefault(f, {'file': f, 'roles': set(), 'lineage_ids': [], 'queries': set()})
            entry['roles'].add('observed_sql_lineage_file')
            if x.get('sql_recursive_column_lineage_id'):
                entry['lineage_ids'].append(x['sql_recursive_column_lineage_id'])
            if x.get('query_id'):
                entry['queries'].add(x['query_id'])
        result = [{**entry, 'roles': sorted(entry['roles']), 'queries': sorted(entry['queries'])}
                  for _, entry in sorted(files.items())]
        return {'relation': relation, 'column': column, 'files': result,
                'status': 'candidates_only',
                'limitations': ['Other workflow/configuration files may be required',
                                'Absence from these results does not prove a file is unaffected'],
                'lineage_target_resolution': raw.get('target_resolution'),
                'gaps': raw.get('gaps'), 'gaps_truncated': raw.get('gaps_truncated', False)}

    def get_calculation_logic(self, *, query_id: str, repo_id: str,
                              scope_id: str | None = None) -> dict[str, Any]:
        """Exposes publisher's exact AST-derived scope context; no SQL reconstruction here."""
        return self.gateway.query_context(query_id, repo_id=repo_id, scope_id=scope_id)

    def get_evidence(self, *, relation: str, column: str | None = None,
                     repo_id: str | None = None) -> dict[str, Any]:
        raw = self.gateway.target_lineage(relation, column=column, repo_id=repo_id)
        return {'relation': relation, 'column': column, 'items': [
            {'lineage_id': x.get('sql_recursive_column_lineage_id'), 'file': x.get('file'),
             'line_start': x.get('line_start'), 'query_id': x.get('query_id'),
             'evidence': x.get('evidence_json'), 'lineage_status': x.get('lineage_status')}
            for x in raw.get('items') or [] if isinstance(x, dict)],
            'gaps': raw.get('gaps'), 'gaps_truncated': raw.get('gaps_truncated', False),
            'target_resolution': raw.get('target_resolution')}
