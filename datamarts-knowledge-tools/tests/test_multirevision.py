"""HTTP-contract tests for publishing multiple revisions to the GLM search tool."""
import httpx
import pytest

from aisl_datamarts_knowledge_tools.gateway import Gateway, KnowledgeError
from aisl_datamarts_knowledge_tools.tools import DataMartsTools


def test_target_discovery_pages_through_all_110_candidates():
    seen = []
    def respond(request):
        p = request.url.params
        seen.append((int(p['offset']), int(p['limit'])))
        if request.url.path.endswith('/sql/target-candidates'):
            start = int(p['offset'])
            return httpx.Response(200, json={
                'candidate_count': 110,
                'candidates': [{'rank': i + 1, 'logical_target_name': f'target{i}'}
                               for i in range(start, min(start + 100, 110))],
            })
        return httpx.Response(404)
    client = httpx.Client(transport=httpx.MockTransport(respond), base_url='http://aisl.test')
    try:
        gateway = Gateway('http://aisl.test','datamart','rev-1',client=client)
        candidates = gateway.downstream_candidates('epk_client',source_column='birth_dt')
        assert len(candidates['candidates']) == 110
        assert candidates['returned_count'] == 110
        assert seen == [(0,100),(100,100)]
    finally:
        client.close()


def test_target_discovery_rejects_incomplete_second_page():
    def respond(req):
        offset = int(req.url.params['offset'])
        return httpx.Response(200, json={'candidate_count': 101,
                                         'candidates': ([{'rank':i} for i in range(100)] if not offset else [])})
    client = httpx.Client(transport=httpx.MockTransport(respond),base_url='http://aisl.test')
    try:
        with pytest.raises(KnowledgeError,match='truncated'):
            Gateway('http://aisl.test','datamart','rev-1',client=client).downstream_candidates('source')
    finally:
        client.close()


def test_cross_revision_search_is_evidence_only_and_preserves_identity():
    def respond(req):
        path = req.url.path
        offset = int(req.url.params.get('offset',0))
        if path.endswith('/sql/relations'):
            return httpx.Response(200,json={'items':[],'page':{'total':0}})
        if path.endswith('/data-model/declared-dataset/types'):
            rows = [{'type_occurrence_id':'t1','simple_name':'BirthDate',
                     'fully_qualified_name':'org.example.BirthDate',
                     'source_ref':{'repository_relative_path':'ucp/BirthDate.java'}}]
            return httpx.Response(200,json={'items':rows[offset:offset+500],'page':{'total':1}})
        if path.endswith('/data-model/declared-dataset/fields'):
            rows=[{'field_occurrence_id':'f1','name':'birthDate','owner_type_occurrence_id':'t1',
                   'source_ref':{'repository_relative_path':'ucp/Individual.java'}}]
            return httpx.Response(200,json={'items':rows[offset:offset+500],'page':{'total':1}})
        if path.endswith('/revisions/rev-tsa'):
            return httpx.Response(200,json={'knowledge_artifacts':[{
                'artifact_id':'mapping','model_kind':'logical-physical-mapping-evidence',
                'capabilities':['common.observed-record-set']} ]})
        if path.endswith('/observed-records/mapping'):
            kind=req.url.params['item_kind']
            if kind=='entity_mapping':
                rows=[{'local_id':'e1','payload':{'mapping_id':'m1','physical_table_name':'org_example_birthdate',
                    'logical_type_name':'org.example.BirthDate','mapping_status':'observed_exact',
                    'source_refs':[{'repository_relative_path':'tsa/Mapping.java'}]}}]
            else:
                rows=[{'local_id':'f2','payload':{'entity_mapping_id':'m1','logical_field_name':'value',
                    'logical_type_name':'org.example.BirthDate','physical_column_name':'value',
                    'mapping_status':'observed_exact',
                    'source_refs':[{'repository_relative_path':'tsa/Mapping.java'}]}}]
            return httpx.Response(200,json={'items':rows[offset:offset+500],'page':{'total':len(rows)}})
        return httpx.Response(404)
    client=httpx.Client(transport=httpx.MockTransport(respond),base_url='http://aisl.test')
    dm = DataMartsTools(Gateway('http://aisl.test','dm','rev-dm',client=client),
                        model_gateway=Gateway('http://aisl.test','ucp','rev-ucp',client=client),
                        replica_gateway=Gateway('http://aisl.test','tsa','rev-tsa',client=client))
    try:
        matches=dm.search_objects(query='BirthDate')
        assert any(x['kind']=='declared_type' and x['revision_id']=='rev-ucp' for x in matches['items'])
        rep=dm.search_objects(query='org_example_birthdate')
        assert rep['items'][0]['kind']=='replica_table'
        assert rep['items'][0]['system_id']=='tsa'
        details=dm.get_object_details(relation='',object_id='f1')
        assert details['count']==1
        assert details['matches'][0]['parent_type']=='org.example.BirthDate'
        assert 'public_tsa_mapping_evidence' in matches['search_coverage']
    finally:
        dm.close()
        client.close()
