import json
import sqlite3
from unittest.mock import Mock

import httpx
import pytest

from aisl_datamarts_knowledge_tools.gateway import Gateway, KnowledgeError
from aisl_datamarts_knowledge_tools.search import ObjectSearch, relation_records
from aisl_datamarts_knowledge_tools.tools import DataMartsTools
from aisl_datamarts_knowledge_tools.catalog import tool_definitions


def _payload(request):
    path = request.url.path
    p = request.url.params
    offset = int(p.get('offset', '0'))
    if path.endswith('/sql/relations'):
        rows = [
            {'sql_relation_id': 'r1', 'relation_name': 'replica_client_birth_dt_hist', 'relation_kind': 'physical_template',
             'evidence_refs': [{'file': 'sql/birth.sql', 'line_start': 22}],
             'fields': [{'column_name': 'birth_dt', 'evidence_refs': [{'file': 'sql/birth.sql', 'line_start': 23}]}]},
            {'sql_relation_id': 'r2', 'relation_name': 'epk_client', 'relation_kind': 'physical',
             'evidence_refs': [{'file': 'sql/epk.sql', 'line_start': 1}],
             'fields': [{'column_name': 'birth_dt'}]},
        ]
        chunk = rows[offset:offset+1]
        return httpx.Response(200, json={'items': chunk, 'page': {'total': len(rows), 'offset': offset}})
    if path.endswith('/sql/target-column-lineage'):
        rows = [{'sql_recursive_column_lineage_id': 'l1', 'workflow_target_logical_name': 'epk_client',
                 'target_column': 'birth_dt', 'terminal_relation_name': 'replica_client_birth_dt_hist',
                 'terminal_column': 'value', 'file': 'sql/epk.sql', 'query_id': 'q1',
                 'line_start': 2, 'branch_path_json': ['a', 'b'], 'transformation_path_json': ['CAST'],
                 'lineage_status': 'confirmed', 'physical_origin_status': 'confirmed'}]
        return httpx.Response(200, json={'items': rows[offset:offset+1], 'page': {'total': 1},
                                         'target_resolution': {'status': 'ambiguous'},
                                         'gaps': [{'kind': 'missing_physical_mapping'}], 'gaps_truncated': False})
    if path.endswith('/sql/target-candidates'):
        return httpx.Response(200, json={'candidate_count': 1, 'candidates': [{'logical_target_name':'epk_client','repo_id':'profile'}]})
    if path.endswith('/sql/query-context'):
        return httpx.Response(200, json={'selection_status': 'selected', 'query_id': p.get('query_id'),
                                         'projections': [{'expression': 'CAST(birth_dt AS TIMESTAMP) AS birth_dt'}]})
    return httpx.Response(404, text='unavailable')


@pytest.fixture
def tools():
    client = httpx.Client(base_url='http://aisl.test', transport=httpx.MockTransport(_payload))
    instance = DataMartsTools(Gateway('http://aisl.test', 'profile', 'rev-123', client=client))
    yield instance
    instance.close()
    client.close()


def test_search_existing_and_fuzzy(tools):
    exact = tools.search_objects(query='birth_dt')
    assert exact['items'][0]['match_kind'] == 'exact'
    assert exact['items'][0]['name'] == 'birth_dt'
    sub = tools.search_objects(query='birth_dt_hist', include_fuzzy=False)
    assert any(x['name'] == 'replica_client_birth_dt_hist' and x['match_kind'] == 'fts5' for x in sub['items'])
    misspelled = tools.search_objects(query='epk_clxent')
    assert any(x['name'] == 'epk_client' and x['match_kind'] == 'fuzzy_candidate' for x in misspelled['items'])
    assert misspelled['identity_policy'].startswith('exact')


def test_sql_tools_keep_gaps_and_candidates(tools):
    details = tools.get_object_details(relation='epk_client')
    assert details['count'] == 1
    lineage = tools.get_attribute_lineage(relation='epk_client', column='birth_dt')
    assert lineage['item_count'] == 1
    assert lineage['gaps'][0]['kind'] == 'missing_physical_mapping'
    graph = tools.get_dependencies(relation='epk_client')
    assert graph['edge_count'] == 1
    assert graph['coverage'] == 'published_sql_target_column_lineage_and_target_candidate_discovery'
    assert graph['downstream_candidate_count'] == 1
    assert 'Downstream candidates require separate lineage confirmation' in graph['limitations']
    candidates = tools.find_change_locations(relation='epk_client', column='birth_dt')
    assert candidates['status'] == 'candidates_only'
    assert candidates['files'][0]['file'] == 'sql/epk.sql'
    logic = tools.get_calculation_logic(query_id='q1', repo_id='profile')
    assert logic['selection_status'] == 'selected'
    evidence = tools.get_evidence(relation='epk_client', column='birth_dt')
    assert evidence['items'][0]['file'] == 'sql/epk.sql'
    assert evidence['target_resolution']['status'] == 'ambiguous'


def test_pagination_is_mandatory():
    def incomplete(req):
        return httpx.Response(200,json={'items':[],'page':{'total':5}})
    cl = httpx.Client(base_url='http://t.test',transport=httpx.MockTransport(incomplete))
    try:
        gw = Gateway('http://t.test','s','rev-1',client=cl)
        with pytest.raises(KnowledgeError, match='truncated'):
            gw.relations()
    finally:
        cl.close()


def test_invalid_revision_rejected():
    with pytest.raises(ValueError):
        Gateway('http://t.test','s','latest')


def test_tool_catalog_is_seven_and_valid_json_schema():
    data = tool_definitions()
    assert len(data)==7
    assert len({x['function']['name'] for x in data})==7
    for tool in data:
        fn=tool['function']
        assert fn['parameters']['type']=='object'
        assert set(fn['parameters']['required']).issubset(fn['parameters']['properties'])
        json.dumps(tool)


def test_limit_indicates_truncation():
    search=ObjectSearch([{'name':'epk_client_1'}, {'name':'epk_client_2'}])
    try:
        r=search.search('epk_client',limit=1,include_fuzzy=False)
        assert r['truncated'] and r['total_matches']==2 and len(r['items'])==1
    finally:
        search.close()
