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
        return httpx.Response(200, json={'candidate_count': 1, 'candidates': [{'logical_target_name':'epk_client','repo_id':'profile', 'source_relation_matches': [{'logical_name': 'epk_client'}]}]})
    if path.endswith('/sql/query-context'):
        return httpx.Response(200, json={'selection_status': 'selected', 'query_id': p.get('query_id'),
                                         'projections': [{'output_name': 'birth_dt','expression': 'CAST(birth_dt AS TIMESTAMP) AS birth_dt'}, {'output_name': 'death_dt', 'expression': 'death_dt'}]})
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
    assert graph['coverage'] == 'published_sql_target_column_lineage_and_target_candidate_discovery_plus_optional_ucp_tsa_replica_er'
    assert graph['downstream_candidate_count'] == 1
    assert any('require separate lineage confirmation' in reason for reason in graph['limitations'])
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


def test_unknown_source_does_not_inherit_global_downstream_candidates(tools):
    # The provider returns the same broad candidate pool for unknown source names.
    # The app must not pass unrelated rows as evidence for that source.
    result = tools.get_dependencies(relation='unpublished_missing_relation')
    assert result['edge_count'] == 1  # mock upstream is intentionally unfiltered
    assert result['downstream_candidate_count'] == 0
    assert result['discovery_pool_count'] == 1
    assert result['candidate_match_policy'] == 'exact_observed_source_relation_only'


def test_column_dependency_candidates_remain_unverified(tools):
    result = tools.get_dependencies(relation='epk_client', column='birth_dt')
    assert result['downstream_candidate_count'] == 1
    assert result['candidate_column_evidence_status'] == 'not_proven_by_relation_match'
    assert 'source_relation_matches' in result['downstream_target_candidates'][0]


def test_search_selection_ref_resolves_published_occurrence(tools):
    result = tools.search_objects(query='epk_client', include_fuzzy=False)
    assert result['items']
    key = result['items'][0]['selection_ref']
    resolved = tools.get_object_details(selection_ref_id=key)
    assert resolved['count'] == 1
    assert resolved['matches'][0]['name'] == result['items'][0]['name']
    assert resolved['resolution'] == 'exact_published_record'
    assert key.startswith('search-row-sha256:')


def test_get_object_details_requires_identifier(tools):
    with pytest.raises(ValueError,match='Provide relation'):
        tools.get_object_details()


def test_exact_projection_context_is_bounded_and_does_not_pretend_full_lineage(tools):
    result = tools.get_calculation_logic(query_id='q1', repo_id='profile', output_name='birth_dt')
    assert result['matched_projection_count'] == 1
    assert result['total_scope_projection_count'] == 2
    assert result['projections'][0]['output_name'] == 'birth_dt'
    assert 'not proof of full upstream calculation' in result['limitations'][0]
    absent = tools.get_calculation_logic(query_id='q1', repo_id='profile', output_name='missing_field')
    assert absent['projection_match_status'] == 'not_found_in_selected_scope'


def test_candidates_compact_by_default_with_full_evidence_opt_in(tools):
    compact = tools.get_dependencies(relation='epk_client')
    assert compact['downstream_candidate_count'] == 1
    assert compact['candidate_details_included'] is False
    assert compact['downstream_target_candidates'][0]['candidate_status'] == 'unconfirmed_dependency'
    full = tools.get_dependencies(relation='epk_client', include_candidate_details=True)
    assert full['candidate_details_included'] is True
    assert full['downstream_target_candidates'][0]['logical_target_name'] == compact['downstream_target_candidates'][0]['logical_target_name']
