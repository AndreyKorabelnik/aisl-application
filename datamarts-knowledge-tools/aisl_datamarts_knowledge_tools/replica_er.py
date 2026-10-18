"""Consumer-side, revision-pinned reuse of the accepted Task 49 UCP/TSA ER model.

This is an index of an existing projection, not a new relationship resolver.
Relations here are declared UCP associations mapped exactly to TSA replicas;
they are NOT physical joins, FKs, attribute lineage or data-transfer edges.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Mapping

from aisl_ucp_tsa_replica_er import RevisionBinding, build_replica_model


class ReplicaERIndex:
    def __init__(self, base_url: str, *, model_system: str, model_revision: str,
                 replica_system: str, replica_revision: str,
                 load: Callable[[], Mapping[str, Any]] | None = None):
        self._base_url = base_url
        self._ucp = RevisionBinding(model_system, model_revision)
        self._tsa = RevisionBinding(replica_system, replica_revision)
        self._load = load
        self._model: dict[str, Any] | None = None
        self._relations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._tables: dict[str, dict[str, Any]] = {}
        self._fields: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def _build(self) -> dict[str, Any]:
        if self._load is not None:
            return dict(self._load())
        from aisl_ucp_tsa_replica_er.gateway import KnowledgeApiGateway
        loader = KnowledgeApiGateway(self._base_url)
        try:
            return build_replica_model(
                ucp=self._ucp, tsa=self._tsa,
                ucp_dataset=loader.load_ucp_dataset(self._ucp),
                tsa_mappings=loader.load_tsa_mappings(self._tsa),
                # Full published model, not root-only outgoing closure.
                root_objects=(),
            )
        finally:
            loader.close()

    def _ensure(self) -> None:
        if self._model is not None:
            return
        model = self._build()
        if model.get('schema_version') != 'ucp-tsa-replica-er/v1':
            raise ValueError('Task 49 replica ER schema mismatch')
        if model.get('ucp_binding') != {'system_id': self._ucp.system_id, 'revision_id': self._ucp.revision_id}:
            raise ValueError('Task 49 model binding mismatch')
        if model.get('tsa_binding') != {'system_id': self._tsa.system_id, 'revision_id': self._tsa.revision_id}:
            raise ValueError('Task 49 replica binding mismatch')
        # Construct indexes only after the full model and bindings have passed validation.
        relations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        tables: dict[str, dict[str, Any]] = {}
        fields: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in model.get('relationships') or []:
            if not isinstance(item, dict):
                continue
            src = str(item.get('source_replica_relation') or '').casefold()
            dst = str(item.get('target_replica_relation') or '').casefold()
            if src and dst:
                relations[src].append(item)
                if dst != src:
                    relations[dst].append(item)
        for item in model.get('tables') or []:
            if isinstance(item, dict) and item.get('replica_relation'):
                tables[str(item['replica_relation']).casefold()] = item
        for item in model.get('replica_fields') or []:
            if isinstance(item, dict) and item.get('replica_relation'):
                fields[str(item['replica_relation']).casefold()].append(item)
        self._relations, self._tables, self._fields, self._model = relations, tables, fields, model

    def relationships(self, relation: str, *, column: str | None = None) -> dict[str, Any]:
        self._ensure()
        key = relation.casefold()
        matches = []
        for item in self._relations.get(key, ()):
            src = str(item.get('source_replica_relation') or '').casefold()
            dst = str(item.get('target_replica_relation') or '').casefold()
            direction = 'outgoing_declared_reference' if src == key else 'incoming_declared_reference'
            matches.append({**item, 'relative_direction': direction,
                            'semantic_category': 'declared_logical_relationship_projected_to_replicas',
                            'attribute_lineage_status': 'not_proven',
                            'data_transfer_status': 'not_proven'})
        return {
            'status': 'available',
            'ucp_binding': self._model['ucp_binding'],
            'tsa_binding': self._model['tsa_binding'],
            'relation': relation,
            'relationships': matches,
            'relationship_count': len(matches),
            'incoming_count': sum(r['relative_direction'] == 'incoming_declared_reference' for r in matches),
            'outgoing_count': sum(r['relative_direction'] == 'outgoing_declared_reference' for r in matches),
            'relation_level_only': column is not None,
            'column_evidence_status': 'not_proven_by_logical_relationship' if column else 'not_requested',
            'total_published_projection_relationships': self._model['counts']['relationships'],
            'model_gap_count': self._model['counts'].get('mapping_gaps', 0),
            'model_table_key_gap_count': self._model['counts'].get('table_key_gaps', 0),
            'semantics': 'UCP declared relationships projected through exact TSA mappings; not physical FK/JOIN or data flow',
            'complete_projected_model': True,
        }

    def table_details(self, relation: str) -> dict[str, Any]:
        self._ensure()
        key = relation.casefold()
        return {'table': self._tables.get(key), 'replica_fields': list(self._fields.get(key, ())),
                'ucp_binding': self._model['ucp_binding'], 'tsa_binding': self._model['tsa_binding'],
                'physical_key_status': 'not_observed',
                'description': 'Task 49 exact UCP/TSA mapping projection; no physical PK/FK assertion'}
