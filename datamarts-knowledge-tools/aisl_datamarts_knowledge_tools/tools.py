"""Seven externally advertised tools. All claims link back to PUBLIC AISL evidence."""
from __future__ import annotations

from typing import Any

from .gateway import Gateway
from .search import ObjectSearch, relation_records, declared_model_records, replica_mapping_records, selection_ref
from .replica_er import ReplicaERIndex
from .cross_revision import CrossRevisionLineage


class DataMartsTools:
    def __init__(self, gateway: Gateway, *, model_gateway: Gateway | None = None,
                 replica_gateway: Gateway | None = None):
        self.gateway = gateway
        self.model_gateway = model_gateway
        self.replica_gateway = replica_gateway
        self._relations: list[dict[str, Any]] | None = None
        self._search: ObjectSearch | None = None
        self._replica_er: ReplicaERIndex | None = None
        self._cross_revision: CrossRevisionLineage | None = None

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


    def _replica_er_for(self, relation: str) -> ReplicaERIndex | None:
        """Avoid expensive full-model load for non-TSA names and unknown objects."""
        if not self.model_gateway or not self.replica_gateway:
            return None
        is_replica = any(
            row.get('kind') == 'replica_table'
            and row.get('mapping_status') == 'observed_exact'
            and str(row.get('name') or '').casefold() == relation.casefold()
            for row in self._search_index().records
        )
        if not is_replica:
            return None
        if self._replica_er is None:
            self._replica_er = ReplicaERIndex(
                str(self.gateway.client.base_url),
                model_system=self.model_gateway.system_id,
                model_revision=self.model_gateway.revision_id,
                replica_system=self.replica_gateway.system_id,
                replica_revision=self.replica_gateway.revision_id,
            )
        return self._replica_er

    def get_object_details(self, *, relation: str = '', object_id: str | None = None,
                           selection_ref_id: str | None = None) -> dict[str, Any]:
        """Select the exact published search record or list exact-name candidates.

        The search-result selection_ref_id is a consumer key, NOT an AISL object ID.
        """
        if not relation.strip() and not object_id and not selection_ref_id:
            raise ValueError('Provide relation, object_id or selection_ref_id')
        rows = self._search_index().records
        records = [r for r in rows
                   if (selection_ref(r) == selection_ref_id if selection_ref_id
                       else str(r.get('object_id') or '') == object_id if object_id
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
            if match.get('kind') == 'replica_table' and match.get('mapping_status') == 'observed_exact':
                projection = self._replica_er_for(str(match.get('name') or ''))
                if projection:
                    try:
                        item['ucp_tsa_replica_er'] = projection.table_details(str(match['name']))
                    except (RuntimeError, ValueError, KeyError) as exc:
                        item['ucp_tsa_replica_er'] = {
                            'status': 'unavailable',
                            'gap': f'{type(exc).__name__}: {exc}',
                            'complete_projected_model': False,
                        }
            enriched.append(item)
        return {'requested_relation': relation, 'requested_object_id': object_id,
                'requested_selection_ref': selection_ref_id,
                'matches': enriched, 'count': len(enriched),
                'resolution': 'not_found' if not enriched else 'ambiguous' if len(enriched) > 1 else 'exact_published_record' if (object_id or selection_ref_id) else 'name_candidate',
                'warning': 'Matching names and mapping records are not proof of deployment or all edit locations'}

    def get_attribute_lineage(self, *, relation: str, column: str, repo_id: str | None = None) -> dict[str, Any]:
        return self.gateway.target_lineage(relation, column=column, repo_id=repo_id)

    def get_dependencies(self, *, relation: str, column: str | None = None,
                         repo_id: str | None = None,
                         include_candidate_details: bool = False,
                         edge_offset: int = 0, edge_limit: int = 20,
                         include_edge_details: bool = False,
                         include_cross_revision_details: bool = False,
                         include_execution_context: bool = False,
                         ctl_entity_id: str | None = None) -> dict[str, Any]:
        """All PUBLISHED upstream target lineage, without synthesizing edges."""
        if edge_offset < 0 or not (1 <= edge_limit <= 500):
            raise ValueError('edge_offset >= 0 and 1 <= edge_limit <= 500 required')
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
        # target-candidates is a broad discovery pool, not an already filtered
        # dependency list. The server may return the same pool for unknown names.
        # Retain only candidates carrying an EXPLICIT exact observed source match.
        # This does not elevate candidates to confirmed dependency edges.
        matched_candidates: list[dict[str, Any]] = []
        exact_name = relation.casefold()
        for candidate in outgoing.get('candidates') or []:
            observed = candidate.get('source_relation_matches') or []
            if any(isinstance(m, dict) and exact_name in {
                str(m.get('logical_name') or '').casefold(),
                str(m.get('relation_name') or '').casefold(),
            } for m in observed):
                matched_candidates.append(candidate)
        # Full API candidate evidence can be very large and unrelated to the
        # chosen source. The default is an exact, lossless *candidate identity*
        # projection; the very same tool can return full details on request.
        def compact(candidate: dict[str, Any]) -> dict[str, Any]:
            exact = [m for m in candidate.get('source_relation_matches') or []
                     if isinstance(m, dict) and exact_name in {
                         str(m.get('logical_name') or '').casefold(),
                         str(m.get('relation_name') or '').casefold()}]
            return {
                'logical_target_name': candidate.get('logical_target_name'),
                'recommended_target_relation': candidate.get('recommended_target_relation'),
                'target_relation_candidates': candidate.get('target_relation_candidates'),
                'source_rank': candidate.get('source_rank'),
                'relation_match_status': 'published_source_relation_observation_candidate',
                'source_relation_matches': exact,
                'source_column_matches': candidate.get('source_column_matches') or [],
                'candidate_status': 'unconfirmed_dependency',
            }
        display_candidates = (matched_candidates if include_candidate_details
                              else [compact(c) for c in matched_candidates])
        replica_model = self._replica_er_for(relation)
        replica_links = None
        replica_model_status = 'not_configured' if not (self.model_gateway and self.replica_gateway) else 'not_a_published_exact_replica'
        if replica_model:
            # A genuine provider/access gap is explicit. SQL evidence is not discarded.
            try:
                replica_links = replica_model.relationships(relation, column=column)
                replica_model_status = 'available'
            except (RuntimeError, ValueError, KeyError) as exc:
                replica_model_status = 'unavailable'
                replica_links = {'status': 'unavailable', 'relationship_count': 0,
                                 'gap': f'{type(exc).__name__}: {exc}',
                                 'complete_projected_model': False}
        # Task46 is the sole semantic composer of UCP → TSA → SQL paths.
        cross_revision: dict[str, Any] | None = None
        available_cross_revision_fields: list[dict[str, Any]] = []
        cross_status = 'not_configured' if not (self.model_gateway and self.replica_gateway) else 'not_exact_replica'
        if replica_model:
            if not column:
                try:
                    fields = replica_model.table_details(relation)['replica_fields']
                    available_cross_revision_fields = [
                        {'replica_column':x.get('replica_column'), 'ucp_field':x.get('ucp_field'),
                         'ucp_type_fqcn':x.get('ucp_type_fqcn'), 'mapping_status':x.get('mapping_status')}
                        for x in fields]
                    cross_status = 'requires_exact_replica_column'
                except (RuntimeError,ValueError,KeyError) as exc:
                    cross_status = 'unavailable'
                    cross_revision = {'status':'unavailable','complete':False,'gap':str(exc),'rows':[]}
            else:
                try:
                    mapped_fields = replica_model.table_details(relation)['replica_fields']
                    if self._cross_revision is None:
                        self._cross_revision = CrossRevisionLineage(
                            str(self.gateway.client.base_url),
                            model_system=self.model_gateway.system_id, model_revision=self.model_gateway.revision_id,
                            replica_system=self.replica_gateway.system_id, replica_revision=self.replica_gateway.revision_id,
                            profile_system=self.gateway.system_id, profile_revision=self.gateway.revision_id)
                    cross_revision = self._cross_revision.for_field(
                        relation=relation, column=column, mapped_fields=mapped_fields)
                    if not include_cross_revision_details and cross_revision['status'] == 'available':
                        cross_revision = dict(cross_revision)
                        cross_revision['rows'] = [
                            {k: row.get(k) for k in ('source_type_fqcn','source_field',
                                'replica_relation','replica_column','profile_source_relation',
                                'profile_representation_variant','target_relation','target_column',
                                'lineage_depth','status','gap','relation_path')}
                            for row in cross_revision['rows']]
                        cross_revision['details_included'] = False
                    elif cross_revision['status'] == 'available':
                        cross_revision['details_included'] = True
                    cross_status = cross_revision['status']
                except (RuntimeError, ValueError, KeyError) as exc:
                    cross_status = 'unavailable'
                    cross_revision = {'status': 'unavailable', 'complete': False,
                                      'gap': f'{type(exc).__name__}: {exc}', 'rows': []}
        sql_context = None
        if include_execution_context:
            qids = {str(x.get('query_id')) for x in raw.get('items', []) if x.get('query_id')}
            workflows = set()
            for x in raw.get('items', []):
                for step in x.get('branch_path_json') or []:
                    if isinstance(step, dict) and step.get('workflow_context_file'):
                        workflows.add(str(step['workflow_context_file']))
            try:
                sql_context = self.gateway.sql_execution_context(qids, workflows)
            except (RuntimeError, ValueError, KeyError) as exc:
                sql_context = {'status': 'unavailable', 'complete': False,
                               'gap': f'{type(exc).__name__}: {exc}'}
        ctl_context = None
        if ctl_entity_id is not None:
            if not ctl_entity_id.strip():
                raise ValueError('ctl_entity_id must not be blank')
            try:
                ctl_context = self.gateway.ctl_entity_context(ctl_entity_id)
            except (RuntimeError, ValueError, KeyError) as exc:
                ctl_context = {'status': 'unavailable', 'complete': False,
                               'gap': f'{type(exc).__name__}: {exc}', 'entity_id': ctl_entity_id}
        # The public API data is fully retrieved. Only the *response projection*
        # is paged to avoid pushing megabytes into the weak-LLM context.
        full_page = edges[edge_offset:edge_offset + edge_limit]
        edge_page = (full_page if include_edge_details else [
            {k: row.get(k) for k in ('lineage_id','target_relation','target_column',
                                      'source_relation','source_column','depth','status','origin_status')}
            for row in full_page])
        edge_more = edge_offset + len(edge_page) < len(edges)
        return {'relation': relation, 'column': column, 'edges': edge_page, 'edge_count': len(edges),
                'edge_details_included':include_edge_details,
                'edge_page': {'offset': edge_offset, 'limit': edge_limit, 'returned': len(edge_page),
                              'total':len(edges), 'has_more':edge_more,
                              'next_offset':edge_offset+len(edge_page) if edge_more else None},
                'cross_revision_available_fields':available_cross_revision_fields,
                'cross_revision_lineage': cross_revision,
                'cross_revision_lineage_status': cross_status,
                'sql_execution_context': sql_context,
                'ctl_entity_context': ctl_context,
                'replica_logical_relationships': replica_links,
                'replica_logical_relationship_status': replica_model_status,
                'downstream_target_candidates': display_candidates,
                'candidate_details_included': include_candidate_details,
                'downstream_candidate_count': len(matched_candidates),
                'discovery_pool_count': outgoing.get('candidate_count'),
                'candidate_match_policy': 'exact_observed_source_relation_only',
                'candidate_column_evidence_status': ('not_proven_by_relation_match' if column else 'not_requested'),
                'target_resolution': raw.get('target_resolution'), 'gaps': raw.get('gaps'),
                'gaps_truncated': raw.get('gaps_truncated', False),
                'direction': 'upstream_confirmed_or_partial_plus_downstream_discovery_candidates',
                'coverage': 'published_sql_target_column_lineage_and_target_candidate_discovery_plus_optional_ucp_tsa_replica_er',
                'coverage_by_family': {'sql_lineage': 'available', 'ucp_tsa':replica_model_status,
                                       'task46_lineage':cross_status,
                                       'sql_execution':'not_requested' if sql_context is None else sql_context['status'],
                                       'ctl':'not_requested' if ctl_context is None else ctl_context['status'],
                                       'topology':'not_queried'},
                'limitations': ['Downstream candidates are relation-level only and require separate lineage confirmation', 'Does not invent edges across revisions', 'Projected UCP/TSA replica links are logical relations, not SQL/physical joins or data flows'],
                'complete_public_items': raw.get('item_count') == len(raw.get('items', [])),
                'response_is_paged': True}

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
                              scope_id: str | None = None,
                              output_name: str | None = None) -> dict[str, Any]:
        """Return public query context, optionally projected by exact output name.

        Filtering is purely mechanical. A single projection does NOT represent
        the full upstream business calculation of an attribute.
        """
        raw = self.gateway.query_context(query_id, repo_id=repo_id, scope_id=scope_id)
        if output_name is None:
            return raw
        if not output_name.strip():
            raise ValueError('output_name cannot be blank')
        projections = raw.get('projections') or []
        selected = [p for p in projections if isinstance(p, dict)
                    and str(p.get('output_name') or '').casefold() == output_name.casefold()]
        stmt = raw.get('statement') or {}
        scope = raw.get('scope') or {}
        ctes = stmt.get('cte_definitions') or []
        return {
            'system_id': raw.get('system_id'), 'revision_id': raw.get('revision_id'),
            'repo_id': repo_id, 'query_id': query_id,
            'scope_id': scope.get('sql_select_scope_id') or scope_id,
            'selection_status': raw.get('selection_status'),
            'output_name': output_name, 'projection_match_status': 'selected' if selected else 'not_found_in_selected_scope',
            'projections': selected, 'matched_projection_count': len(selected),
            'total_scope_projection_count': len(projections),
            'source_file': stmt.get('file') or scope.get('file'),
            'statement_id': stmt.get('sql_statement_id'),
            'scope_kind': scope.get('scope_kind'),
            'where_predicate': scope.get('where_predicate'),
            'cte_names': [cte.get('cte_name') for cte in ctes if isinstance(cte, dict)],
            'child_scope_count': len(raw.get('child_scopes') or []),
            'diagnostics': raw.get('diagnostics'),
            'limitations': [
                'This is an exact selected-scope projection, not proof of full upstream calculation',
                'Use get_attribute_lineage and further scope/context inspection for upstream transformations',
            ],
        }

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
