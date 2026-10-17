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
            for _, score, i in process.extract(term, names, scorer=fuzz.WRatio, limit=max(limit * 4, 50), score_cutoff=65):
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
