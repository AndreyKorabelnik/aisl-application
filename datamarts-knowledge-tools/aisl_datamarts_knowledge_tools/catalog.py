"""Tool descriptions for a model-facing function/tool adapter."""
from __future__ import annotations


DEFINITIONS = [
    ('search_objects', 'Search published SQL relations/fields and optional declared data models / TSA replicas by name. Exact, FTS5 substring, RapidFuzz candidate results; fuzzy suggestions are not identity proofs.', {'query': 'string', 'limit': 'integer', 'include_fuzzy': 'boolean'}, ['query']),
    ('get_object_details', 'Select one published record using the selection_ref_id returned by search_objects, or list same-name occurrences; selection refs are consumer-only record keys.', {'relation': 'string', 'object_id': 'string', 'selection_ref_id': 'string'}, []),
    ('find_change_locations', 'Find source SQL FILE CANDIDATES observed in target column lineage, not a definitive list of required edits.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation']),
    ('get_dependencies', 'Get published SQL lineage and exact source-matched downstream candidates; when pinned UCP and TSA revisions are supplied, also return separate incoming/outgoing Task 49 projected logical replica relationships (NOT SQL joins, data flow or physical FKs).', {'relation': 'string', 'column': 'string', 'repo_id': 'string', 'include_candidate_details': 'boolean', 'include_edge_details':'boolean','include_cross_revision_details':'boolean', 'edge_offset':'integer','edge_limit':'integer', 'include_execution_context':'boolean','ctl_entity_id':'string'}, ['relation']),
    ('get_attribute_lineage', 'Get complete paginated published attribute lineage and transformation/evidence segments.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation', 'column']),
    ('get_calculation_logic', 'Get publisher-authored SQL query/scope context: SELECT expressions, JOINs, filters, windows, dependencies.', {'query_id': 'string', 'repo_id': 'string', 'scope_id': 'string', 'output_name': 'string'}, ['query_id', 'repo_id']),
    ('get_evidence', 'Obtain provenance and diagnostic gaps for target relations/columns; no invented source facts.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation']),
]


def tool_definitions() -> list[dict]:
    return [{'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': {'type': 'object',
                       'properties': {k: {'type': v} for k, v in properties.items()},
                       'required': required, 'additionalProperties': False},
    }} for name, description, properties, required in DEFINITIONS]
