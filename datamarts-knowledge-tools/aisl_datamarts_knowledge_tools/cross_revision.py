"""Task 46 consumer composition via its accepted API; no lineage logic copied here."""
from __future__ import annotations

from typing import Any

from aisl_data_model_datamart_lineage import RevisionBinding, build_lineage
from aisl_data_model_datamart_lineage.gateway import KnowledgeApiGateway


class CrossRevisionLineage:
    def __init__(self, base_url: str, *, model_system: str, model_revision: str,
                 replica_system: str, replica_revision: str, profile_system: str, profile_revision: str,
                 gateway_factory=KnowledgeApiGateway):
        self.base_url = base_url
        self.ucp = RevisionBinding(model_system, model_revision)
        self.tsa = RevisionBinding(replica_system, replica_revision)
        self.profile = RevisionBinding(profile_system, profile_revision)
        self.gateway_factory = gateway_factory
        self._cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    def for_field(self, *, relation: str, column: str, mapped_fields: list[dict[str, Any]]) -> dict[str, Any]:
        """Only *exact* Task49 mappings may select a Task46 source field."""
        selected = [row for row in mapped_fields
                    if str(row.get('replica_column') or '').casefold() == column.casefold()
                    and str(row.get('mapping_status') or '') == 'observed_exact']
        identities = {(str(x.get('ucp_type_fqcn') or ''), str(x.get('ucp_field') or '')) for x in selected}
        if len(identities) != 1 or not all(next(iter(identities), ('', ''))):
            return {'status': 'ambiguous_mapping' if len(identities)>1 else 'not_mapped',
                    'rows': [], 'total_count': 0, 'gap': 'exact_unique_ucp_tsa_field_mapping_required',
                    'complete': False}
        logical_type, logical_field = next(iter(identities))
        cache_key=(relation.casefold(), logical_type, logical_field)
        if cache_key not in self._cache:
            loader=self.gateway_factory(self.base_url)
            try:
                rows=build_lineage(gateway=loader, source=self.ucp, tsa=self.tsa,
                                   profile=self.profile, source_object=logical_type, source_field=logical_field)
                self._cache[cache_key]=[dict(row) for row in rows]
            finally:
                loader.close()
        rows=self._cache[cache_key]
        confirmed=[row for row in rows if str(row.get('status') or '').startswith('confirmed')]
        return {'status': 'available', 'source_type':logical_type,'source_field':logical_field,
                'rows': rows,'total_count':len(rows),'confirmed_branch_count':len(confirmed),
                'complete':True,'semantics':'Published Task46 composition; physical target ambiguity remains explicit',
                'bindings':[self.ucp.__dict__ if hasattr(self.ucp,'__dict__') else {'system_id':self.ucp.system_id,'revision_id':self.ucp.revision_id},
                            {'system_id':self.tsa.system_id,'revision_id':self.tsa.revision_id},
                            {'system_id':self.profile.system_id,'revision_id':self.profile.revision_id}]}
