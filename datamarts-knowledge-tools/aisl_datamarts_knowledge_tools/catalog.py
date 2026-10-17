"""Tool descriptions for a model-facing function/tool adapter."""
from __future__ import annotations


DEFINITIONS = [
    ('search_objects', 'Search published SQL relations/fields and optional declared data models / TSA replicas by name. Exact, FTS5 substring, RapidFuzz candidate results; fuzzy suggestions are not identity proofs.', {'query': 'string', 'limit': 'integer', 'include_fuzzy': 'boolean'}, ['query']),
    ('get_object_details', 'Get all observed SQL relation occurrences and their published fields/evidence; do not assume physical identity.', {'relation': 'string', 'object_id': 'string'}, ['relation']),
    ('find_change_locations', 'Find source SQL FILE CANDIDATES observed in target column lineage, not a definitive list of required edits.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation']),
    ('get_dependencies', 'Get all upstream dependency branches published by target-column-lineage with paths and explicit gaps. Does not claim downstream completeness.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation']),
    ('get_attribute_lineage', 'Get complete paginated published attribute lineage and transformation/evidence segments.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation', 'column']),
    ('get_calculation_logic', 'Get publisher-authored SQL query/scope context: SELECT expressions, JOINs, filters, windows, dependencies.', {'query_id': 'string', 'repo_id': 'string', 'scope_id': 'string'}, ['query_id', 'repo_id']),
    ('get_evidence', 'Obtain provenance and diagnostic gaps for target relations/columns; no invented source facts.', {'relation': 'string', 'column': 'string', 'repo_id': 'string'}, ['relation']),
]


def tool_definitions() -> list[dict]:
    return [{'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': {'type': 'object',
                       'properties': {k: {'type': v} for k, v in properties.items()},
                       'required': required, 'additionalProperties': False},
    }} for name, description, properties, required in DEFINITIONS]
