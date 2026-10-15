"""SQL prototype reconstruction from revision-pinned, PUBLIC AISL Knowledge API.

Reads no SQL source files, DuckDB artifacts, or private internal tables.
It does not guess unsupported SQL structures: instead it reports gaps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import httpx
import sqlglot


class HTTPClient(Protocol):
    def get(self, url: str, *, params: dict[str, Any]): ...


class ReconstructionError(RuntimeError):
    pass


class PublicSqlRestorer:
    def __init__(self, client: HTTPClient, *, system_id: str, revision_id: str, repo_id: str):
        if not all([system_id, revision_id, repo_id]):
            raise ValueError('Exact system_id, revision_id, and repo_id are required')
        if revision_id in {'active', 'latest'}:
            raise ValueError('Use immutable revision ID; active/latest is not allowed')
        self.client = client
        self.system_id = system_id
        self.revision_id = revision_id
        self.repo_id = repo_id
        self.root = f'/api/knowledge/v1/systems/{system_id}'
        self._context_cache: dict[tuple[str, str | None], dict[str, Any]] = {}

    def _get(self, route: str, **params: Any) -> dict[str, Any]:
        p={'revision_id':self.revision_id, **params}
        resp=self.client.get(self.root+route,params=p)
        if resp.status_code!=200:
            raise ReconstructionError(f'Knowledge API {route}: HTTP {resp.status_code}: {resp.text[:600]}')
        return resp.json()

    def discover_queries(self) -> dict[str,str]:
        """Obtain query identifiers and file provenance solely from PUBLIC relation evidence."""
        observations:dict[str,set[str]]=defaultdict(set)
        offset=0
        while True:
            data=self._get('/sql/relations', view='all', offset=offset,limit=500,
                           include_fields='true',max_evidence_per_role=20,repo_id=self.repo_id)
            for relation in data.get('items',[]):
                for field in relation.get('fields',[]):
                    for ref in field.get('evidence_refs',[]):
                        name=str(ref.get('file') or '')
                        query=str(ref.get('query_id') or '')
                        if name and query and name.startswith('sql/targets/') and name.endswith('.sql'):
                            observations[name].add(query)
            page=data.get('page') or {}
            offset+=len(data.get('items') or [])
            if offset >= int(page.get('total',offset)) or not data.get('items'):
                break
        if not observations:
            raise ReconstructionError('No SQL query identities found via public relation evidence')
        ambiguous={name: sorted(ids) for name,ids in observations.items() if len(ids)!=1}
        if ambiguous:
            raise ReconstructionError(f'Non-unique query identities: {ambiguous}')
        return {name:next(iter(ids)) for name,ids in sorted(observations.items())}

    def context(self, query_id:str, scope_id:str|None=None) -> dict[str,Any]:
        key=(query_id,scope_id)
        if key not in self._context_cache:
            kw={'repo_id':self.repo_id,'query_id':query_id}
            if scope_id:kw['scope_id']=scope_id
            c=self._get('/sql/query-context',**kw)
            if c.get('selection_status')!='selected':
                raise ReconstructionError(f'Not uniquely selected query/scope {key}: {c.get("diagnostics") or c.get("selection_status")}')
            if c.get('diagnostics'):
                raise ReconstructionError(f'Knowledge diagnostics in {key}: {c["diagnostics"]}')
            self._context_cache[key]=c
        return self._context_cache[key]

    @staticmethod
    def _from_expr(rel:dict[str,Any]) -> str:
        name=str(rel.get('relation_name') or '').strip()
        if not name:
            raise ReconstructionError('Missing observed relation name')
        alias=str(rel.get('alias') or '').strip()
        return f'{name} AS {alias}' if alias and alias!=name else name

    def _render_relation(self, query_id: str, rel: dict[str, Any]) -> str:
        kind=str(rel.get('relation_kind') or '')
        if kind == 'generated':
            raise ReconstructionError('Generated relation must be rendered as a LATERAL VIEW clause')
        if kind == 'derived':
            scopes=rel.get('source_scope_ids') or []
            if len(scopes) != 1:
                raise ReconstructionError(f'Derived relation needs one exact source scope: {rel.get("relation_name")}')
            alias=rel.get('alias') or rel.get('relation_name')
            if not alias:
                raise ReconstructionError('Derived relation has no alias')
            return f'({self.render_scope(query_id, str(scopes[0]))}) AS {alias}'
        return self._from_expr(rel)

    def render_scope(self, query:str, scope_id:str) -> str:
        ctx=self.context(query,scope_id)
        scope=ctx['scope']
        projections=sorted(ctx['projections'],key=lambda p:p['projection_ordinal'])
        if len(projections)!=int(scope.get('projection_count') or len(projections)):
            raise ReconstructionError(f'Incomplete projections {query}:{scope_id}')
        if not projections or any(not p.get('expression') for p in projections):
            raise ReconstructionError(f'Projection expressions missing {query}:{scope_id}')
        # The expressions are published SQL AST-derived facts, not a source SQL replay.
        sql='SELECT '+ ('DISTINCT ' if scope.get('distinct_clause') else '')+ ',\n       '.join(str(p['expression']) for p in projections)
        rels=ctx.get('scope_relations') or []
        initial=[r for r in rels if r.get('usage_role')=='from']
        if len(initial)!=1:
            raise ReconstructionError(f'Expected one FROM relation in {query}:{scope_id}; got {len(initial)}')
        sql+='\nFROM '+self._render_relation(query,initial[0])
        joined_ids=set()
        for edge in sorted(ctx.get('joins') or [],key=lambda r:r.get('join_ordinal') or 0):
            target=str(edge.get('right_relation_id') or '')
            matching=[r for r in rels if r.get('sql_relation_id')==target]
            if len(matching)!=1:
                raise ReconstructionError(f'JOIN right relation unresolved in {query}:{scope_id}: {target}')
            jr=matching[0];joined_ids.add(target)
            kind=str(edge.get('join_type') or '').strip().upper()
            if kind in {'', 'JOIN'}:kind='INNER'
            if kind not in {'LEFT','RIGHT','INNER','FULL','CROSS','LEFT OUTER','RIGHT OUTER','FULL OUTER','SEMI','ANTI','LEFT SEMI','LEFT ANTI'}:
                raise ReconstructionError(f'Unsupported JOIN type: {kind}')
            line=f'\n{kind} JOIN {self._render_relation(query,jr)}'
            pred=str(edge.get('predicate') or '').strip()
            using=edge.get('using_columns') or []
            if pred:
                line+=f' ON {pred}'
            elif using:
                line+=' USING ('+', '.join(using)+')'
            elif kind!='CROSS':
                raise ReconstructionError(f'JOIN condition not published {query}:{scope_id}')
            sql+=line
        other=[r for r in rels if r.get('usage_role')=='join' and r.get('sql_relation_id') not in joined_ids]
        generated = [r for r in rels if r.get('relation_kind') == 'generated']
        if generated:
            # The published legacy relation facts do not record LATERAL ordering
            # relative to JOINs or multiple generators. Refuse ambiguous cases.
            if ctx.get('joins') or len(generated) != 1:
                raise ReconstructionError(f'Generated-source clause ordering is unresolved in {query}:{scope_id}')
            # Each generated relation is a row source, never a physical table.
            # A reconstructed SELECT must retain that row-multiplying operation.
            # The legacy public facts lack lateral ordering/OUTER information;
            # reject multiple generators instead of choosing an arbitrary order.
            groups = {(str(r.get('generator_expression') or ''),
                       str(r.get('generator_wrapper_alias') or '')) for r in generated}
            if len(groups) != 1:
                raise ReconstructionError(f'Ambiguous LATERAL VIEW generators in {query}:{scope_id}')
            expression, alias = next(iter(groups))
            names = [str(r.get('relation_name') or '') for r in generated]
            if not expression or not alias or not all(names):
                raise ReconstructionError(f'Generated source expression/alias missing in {query}:{scope_id}')
            # The generator comes after the FROM/JOIN sources, before predicates.
            sql += '\nLATERAL VIEW ' + expression + ' ' + alias + ' AS ' + ', '.join(names)
        if other:
            raise ReconstructionError(f'Non-reconstructed JOIN relations {query}:{scope_id}: {[r.get("relation_name") for r in other]}')
        for attr,keyword in [('where_predicate','WHERE'),('group_by_clause','GROUP BY'),
                             ('having_predicate','HAVING'),('qualify_predicate','QUALIFY'),
                             ('order_by_clause','ORDER BY'),('sort_by_clause','SORT BY'),
                             ('distribute_by_clause','DISTRIBUTE BY'),('cluster_by_clause','CLUSTER BY'),
                             ('limit_clause','LIMIT'),('offset_clause','OFFSET')]:
            raw=scope.get(attr)
            if raw:
                raw=str(raw).strip();
                if raw.upper().startswith(keyword+' '):
                    sql+='\n'+raw
                else:
                    sql+=f'\n{keyword} {raw}'
        return sql

    def render_query(self, query_id:str)->str:
        root=self.context(query_id)
        stmt=root.get('statement') or {}
        ctes=stmt.get('cte_definitions') or []
        ops={str(op['set_operation_id']):op for op in stmt.get('set_operations') or []}
        seen=set()
        def render_ref(ref:dict[str,str])->str:
            kind=ref.get('kind');key=str(ref.get('id') or '')
            if not key:raise ReconstructionError('Missing set-operation child reference')
            if kind=='select_scope':return self.render_scope(query_id,key)
            if kind!='set_operation':raise ReconstructionError(f'Unexpected definition kind: {kind}')
            if key in seen:raise ReconstructionError('Cyclic set-operation topology')
            if key not in ops:raise ReconstructionError(f'Set-operation not published: {key}')
            seen.add(key)
            op=ops[key]
            operator=str(op.get('operator') or '').upper()
            if operator not in {'UNION','EXCEPT','INTERSECT'}:raise ReconstructionError(f'Unsupported set operator: {operator}')
            sep=operator + ('' if op.get('distinct') else ' ALL')
            left=render_ref(op['left']);right=render_ref(op['right']);seen.remove(key)
            return f'{left}\n{sep}\n{right}'
        rendered=[]
        for cte in sorted(ctes,key=lambda x:x['cte_ordinal']):
            name=str(cte['cte_name']); ref=cte['definition']
            inner=render_ref(ref)
            cols=cte.get('column_aliases') or []
            label=name+('('+', '.join(cols)+')' if cols else '')
            rendered.append(f'{label} AS (\n{inner}\n)')
        recursive=any(bool(cte.get('recursive')) for cte in ctes)
        sql=('WITH RECURSIVE ' if recursive else 'WITH ')+',\n'.join(rendered)+'\n' if rendered else ''
        sql+=self.render_scope(query_id,str(root['scope_id']))
        # Fail-closed on unsupported SQL. sqlglot parser does not establish data semantics.
        try:
            ast=sqlglot.parse_one(sql, read='spark',error_level='RAISE')
            if ast is None:raise ValueError('empty parse')
        except Exception as exc:
            raise ReconstructionError(f'Reconstructed SQL not parseable: {exc}') from exc
        return sql.rstrip()+'\n'

    def restore_all(self,out_dir:Path)->dict[str,Any]:
        out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
        queries=self.discover_queries()
        results=[]
        for relative, qid in queries.items():
            # Only names and IDs from the pinned public revision determine filenames.
            if '..' in PurePosixPath(relative).parts or PurePosixPath(relative).is_absolute():
                raise ReconstructionError('Untrusted source path in API')
            name=PurePosixPath(relative).name
            dest=out_dir/name
            try:
                sql=self.render_query(qid)
                dest.write_text(sql,encoding='utf-8')
                results.append({'file':name,'source_query_id':qid,'status':'restored',
                                'sha256':hashlib.sha256(sql.encode()).hexdigest(),
                                'bytes':len(sql.encode())})
            except ReconstructionError as exc:
                # A previous run must never leave a stale SQL under an unresolved target.
                if dest.exists():
                    dest.unlink()
                results.append({'file':name,'source_query_id':qid,'status':'unresolved','diagnostic':str(exc)})
        return {'schema_version':'aisl_sql_restoration_report/v1','system_id':self.system_id,
                'revision_id':self.revision_id,'repo_id':self.repo_id,
                'query_count':len(queries),'restored_count':sum(x['status']=='restored' for x in results),
                'unresolved_count':sum(x['status']=='unresolved' for x in results),'items':results}


def main()->int:
    p=argparse.ArgumentParser(description='Restore SQL from PUBLIC pinned AISL Knowledge API')
    p.add_argument('--api-url',required=True,help='Origin URL or URL ending in /api/knowledge/v1')
    p.add_argument('--system-id',required=True)
    p.add_argument('--revision-id',required=True)
    p.add_argument('--repo-id',required=True)
    p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    base=a.api_url.rstrip('/')
    if base.endswith('/api/knowledge/v1'):base=base[:-len('/api/knowledge/v1')]
    with httpx.Client(base_url=base,timeout=45,follow_redirects=False) as c:
        restored=PublicSqlRestorer(c,system_id=a.system_id,revision_id=a.revision_id,repo_id=a.repo_id).restore_all(Path(a.output_dir))
    out=Path(a.output_dir)/'restoration_report.json';out.write_text(json.dumps(restored,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in restored.items() if k!='items'},ensure_ascii=False,indent=2))
    return 0 if restored['unresolved_count']==0 else 2

if __name__=='__main__':raise SystemExit(main())
