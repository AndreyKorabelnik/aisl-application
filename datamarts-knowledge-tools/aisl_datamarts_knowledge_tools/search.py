"""FTS: SQLite FTS5 trigram. Fuzzy ranking: third-party RapidFuzz.

No handwritten tokenizer, levenshtein metric, SQL parser, or relation inference.
The transient index contains ONLY public names/provenance from the pinned AISL revision.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from rapidfuzz import fuzz, process


class ObjectSearch:
    def __init__(self, records: Iterable[dict[str, Any]]):
        self.records = list(records)
        self.con = sqlite3.connect(':memory:')
        try:
            self.con.execute("CREATE VIRTUAL TABLE index_fts USING fts5(name, file, tokenize='trigram')")
        except sqlite3.OperationalError as exc:
            raise RuntimeError('SQLite build must support FTS5 trigram tokenizer') from exc
        self.con.executemany('INSERT INTO index_fts(rowid,name,file) VALUES (?,?,?)', [
            (i+1, str(r.get('name') or ''), str(r.get('file') or ''))
            for i, r in enumerate(self.records)
        ])

    def close(self) -> None:
        self.con.close()

    def search(self, query: str, *, limit: int = 30, include_fuzzy: bool = True) -> dict[str, Any]:
        if not query.strip():
            raise ValueError('Search query cannot be blank')
        if not 1 <= limit <= 1000:
            raise ValueError('limit must be in [1,1000]')
        term = query.strip()
        matches: dict[int, tuple[str, float]] = {}
        # Exact match and FTS5 indexed substring matches (trigram requires >=3 chars).
        for i, r in enumerate(self.records):
            if str(r.get('name', '')).casefold() == term.casefold():
                matches[i] = ('exact', 100.0)
        if len(term) >= 3:
            # SQLite handles tokenization and trigram indexing, including '_' in SQL identifiers.
            fts_query = '"' + term.replace('"', '""') + '"'
            for (rowid,) in self.con.execute('SELECT rowid FROM index_fts WHERE index_fts MATCH ?', (fts_query,)):
                i = rowid-1
                matches.setdefault(i, ('fts5', 100.0))
        # RapidFuzz is used only to suggest candidates. It must never declare identity.
        if include_fuzzy:
            names = [str(r.get('name') or '') for r in self.records]
            for _, score, i in process.extract(term, names, scorer=fuzz.WRatio, limit=None, score_cutoff=65):
                matches.setdefault(i, ('fuzzy_candidate', round(float(score), 2)))
        order = {'exact': 0, 'fts5': 1, 'fuzzy_candidate': 2}
        hits = [{**self.records[i], 'match_kind': kind, 'match_score': score}
                for i, (kind, score) in sorted(matches.items(), key=lambda kv: (order[kv[1][0]], -kv[1][1], str(self.records[kv[0]].get('name')), kv[0]))]
        return {'query': query, 'total_matches': len(hits), 'items': hits[:limit],
                'truncated': len(hits) > limit,
                'search_coverage': 'published_sql_relations_and_fields',
                'identity_policy': 'exact is identity candidate; FTS/fuzzy are discovery candidates only'}


def _file_refs(obj: dict[str, Any]) -> list[str]:
    refs = obj.get('evidence_refs') or []
    return sorted({str(x['file']) for x in refs if isinstance(x, dict) and x.get('file')})


def relation_records(relations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for r in relations:
        name = str(r.get('relation_name') or r.get('logical_name') or '').strip()
        rid = str(r.get('sql_relation_id') or '')
        refs = _file_refs(r)
        if name:
            results.append({'object_id': rid, 'name': name, 'kind': 'relation',
                            'relation_kind': r.get('relation_kind'), 'file': refs[0] if refs else '',
                            'evidence_files': refs, 'source': 'public_sql_relations'})
        for f in r.get('fields') or []:
            if not isinstance(f, dict):
                continue
            field = str(f.get('column_name') or f.get('field_name') or f.get('name') or '').strip()
            if not field:
                continue
            ff = _file_refs(f) or refs
            results.append({'object_id': str(f.get('sql_field_id') or rid), 'name': field,
                            'kind': 'field', 'parent_relation': name,
                            'file': ff[0] if ff else '', 'evidence_files': ff,
                            'source': 'public_sql_relations'})
    return results


def declared_model_records(types: Iterable[dict[str, Any]], fields: Iterable[dict[str, Any]],
                           *, system_id: str, revision_id: str) -> list[dict[str, Any]]:
    """Project observed declared types and fields from public dataset records."""
    type_rows = list(types)
    owners = {str(r.get('type_occurrence_id')): r for r in type_rows}
    results: list[dict[str, Any]] = []
    for row in type_rows:
        fqcn = str(row.get('fully_qualified_name') or '')
        ref = row.get('source_ref') or {}
        results.append({'object_id': row.get('type_occurrence_id'), 'name': row.get('simple_name'),
                        'qualified_name': fqcn, 'kind': 'declared_type', 'repo_id': row.get('repo_id'),
                        'file': ref.get('repository_relative_path', ''), 'source_ref': ref,
                        'system_id': system_id, 'revision_id': revision_id,
                        'source': 'public_declared_model_dataset'})
    for row in fields:
        owner = owners.get(str(row.get('owner_type_occurrence_id')), {})
        ref = row.get('source_ref') or {}
        results.append({'object_id': row.get('field_occurrence_id'), 'name': row.get('name'),
                        'kind': 'declared_field', 'parent_type': owner.get('fully_qualified_name'),
                        'field_type': row.get('declared_type_expression'), 'repo_id': row.get('repo_id'),
                        'file': ref.get('repository_relative_path', ''), 'source_ref': ref,
                        'system_id': system_id, 'revision_id': revision_id,
                        'source': 'public_declared_model_dataset'})
    return [row for row in results if row.get('name')]


def replica_mapping_records(fields: Iterable[dict[str, Any]], entities: Iterable[dict[str, Any]],
                            *, system_id: str, revision_id: str) -> list[dict[str, Any]]:
    """Only observed TSA logical↔physical mapping evidence; no inferred equality."""
    entity_rows = list(entities)
    entity_by_id = {str(r.get('payload', {}).get('mapping_id')): r.get('payload', {})
                    for r in entity_rows}
    results: list[dict[str, Any]] = []
    for row in entity_rows:
        p = row.get('payload') or {}
        name = p.get('physical_table_name')
        if name:
            refs = p.get('source_refs') or []
            results.append({'object_id': row.get('local_id'), 'name': name,
                            'kind': 'replica_table', 'logical_type': p.get('logical_type_name'),
                            'mapping_status': p.get('mapping_status'), 'mapping_basis': p.get('mapping_basis'),
                            'file': refs[0].get('repository_relative_path', '') if refs else '',
                            'source_refs': refs, 'system_id': system_id, 'revision_id': revision_id,
                            'source': 'public_tsa_mapping_evidence'})
    for row in fields:
        p = row.get('payload') or {}
        parent = entity_by_id.get(str(p.get('entity_mapping_id')), {})
        refs = p.get('source_refs') or []
        data = {'object_id': row.get('local_id'), 'kind': 'replica_field',
                'physical_table': parent.get('physical_table_name'),
                'logical_type': p.get('logical_type_name'),
                'logical_field': p.get('logical_field_name'),
                'physical_column': p.get('physical_column_name'),
                'mapping_status': p.get('mapping_status'), 'mapping_basis': p.get('mapping_basis'),
                'file': refs[0].get('repository_relative_path', '') if refs else '',
                'source_refs': refs, 'system_id': system_id, 'revision_id': revision_id,
                'source': 'public_tsa_mapping_evidence'}
        if p.get('physical_column_name'):
            results.append({'name': p['physical_column_name'], **data})
        if p.get('logical_field_name') and p.get('logical_field_name') != p.get('physical_column_name'):
            results.append({'name': p['logical_field_name'], **data})
    return results
