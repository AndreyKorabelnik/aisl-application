"""Consumer-visible A5 tests; no new cross-revision semantic resolver."""
import httpx
import pytest

from aisl_datamarts_knowledge_tools.cross_revision import CrossRevisionLineage
from aisl_datamarts_knowledge_tools.gateway import Gateway
from aisl_datamarts_knowledge_tools.tools import DataMartsTools


class ManyGateway:
    system_id='profile'; revision_id='rev-p'
    def __init__(self):
        from types import SimpleNamespace
        self.client=SimpleNamespace(base_url='http://test')
    def target_lineage(self, relation, **kwargs):
        return {'items':[{'sql_recursive_column_lineage_id':f'l{i}', 'target_column':'birth_dt',
                          'terminal_relation_name':'replica_birthdate','terminal_column':'value',
                          'lineage_status':'confirmed','branch_path_json':[{'kind':'workflow_target','workflow_context_file':'ctl/a.yaml'}],
                          'transformation_path_json':['expensive' * 100]} for i in range(41)],
                'item_count':41,'gaps':[],'target_resolution':{'status':'ambiguous'}}
    def downstream_candidates(self,*a,**kw):return {'candidate_count':0,'candidates':[]}
    def close(self):pass


def test_a5_weak_llm_projection_and_lossless_page():
    t=DataMartsTools(ManyGateway())
    first=t.get_dependencies(relation='epk_client', edge_limit=10)
    assert first['edge_count']==41
    assert first['edge_page']=={'offset':0,'limit':10,'returned':10,'total':41,'has_more':True,'next_offset':10}
    assert 'transformations' not in first['edges'][0]
    assert first['coverage_by_family']['topology']=='not_queried'
    full=t.get_dependencies(relation='epk_client',edge_offset=40,edge_limit=10,include_edge_details=True)
    assert full['edge_page']['has_more'] is False
    assert len(full['edges'])==1 and full['edges'][0]['lineage_id']=='l40'
    assert full['edges'][0]['transformations']==['expensive'*100]
    with pytest.raises(ValueError):t.get_dependencies(relation='epk_client',edge_offset=-1)


def test_a5_task46_only_unique_exact_task49_field_mapping(monkeypatch):
    import aisl_datamarts_knowledge_tools.cross_revision as mod
    calls=[]
    class FakeLineageGateway:
        def __init__(self,base):calls.append(('open',base))
        def close(self):calls.append(('close',))
    def accepted_builder(**kwargs):
        calls.append(('build',kwargs['source_object'],kwargs['source_field']))
        return [{'status':'confirmed_lineage_target_relation_ambiguous','target_column':c,
                 'gap':'physical_target_relation_ambiguous'} for c in ('birth_dt','birth_dt','hash','hash')]
    monkeypatch.setattr(mod,'build_lineage',accepted_builder)
    bridge=CrossRevisionLineage('http://aisl',model_system='ucp',model_revision='rev-u',
           replica_system='tsa',replica_revision='rev-t',profile_system='fl',profile_revision='rev-fl',
           gateway_factory=FakeLineageGateway)
    fields=[{'replica_column':'value','ucp_type_fqcn':'demo.BirthDate',
             'ucp_field':'value','mapping_status':'observed_exact'}]
    x=bridge.for_field(relation='replica_birthdate',column='value',mapped_fields=fields)
    assert x['confirmed_branch_count']==4 and x['complete']
    assert all(r['gap']=='physical_target_relation_ambiguous' for r in x['rows'])
    assert bridge.for_field(relation='replica_birthdate',column='value',mapped_fields=fields)['total_count']==4
    assert len([c for c in calls if c[0]=='build'])==1
    fields.append({'replica_column':'value','ucp_type_fqcn':'other.BirthDate',
                   'ucp_field':'value','mapping_status':'observed_exact'})
    assert bridge.for_field(relation='replica_birthdate',column='value',mapped_fields=fields)['status']=='ambiguous_mapping'
    assert bridge.for_field(relation='replica_birthdate',column='missing',mapped_fields=fields)['status']=='not_mapped'


def test_a5_ctl_exact_id_and_not_a_sql_join():
    artifact='art-ctl'
    rows={
       'ctl_entity':[{'entity_id':'123','entity_name':'schema_blago.epk_client'},
                     {'entity_id':'444','entity_name':'other'}],
       'ctl_flow_entity':[{'entity_id':'123','flow_id':'f1'},
                          {'entity_id':'123','flow_id':'f2'},
                          {'entity_id':'444','flow_id':'f3'}],
       'ctl_flow':[{'flow_id':'f1','flow_name':'main'}, {'flow_id':'f2','flow_name':'rollback'}],
       'ctl_dependency':[],
       'ctl_dependency_gap':[{'reason':'unresolved_target'}],
    }
    def handle(req):
        path=req.url.path
        if path.endswith('/revisions/rev-p'):
            return httpx.Response(200,json={'knowledge_artifacts':[
                {'model_kind':'ctl-orchestration','capabilities':['common.ctl-orchestration'],'artifact_id':artifact}]})
        for kind,full in rows.items():
            if path.endswith('/records/'+kind):
                offset=int(req.url.params.get('offset','0'));limit=int(req.url.params.get('limit','500'))
                return httpx.Response(200,json={'items':full[offset:offset+limit],
                                                'page':{'total':len(full)}})
        return httpx.Response(404)
    client=httpx.Client(base_url='http://aisl',transport=httpx.MockTransport(handle))
    gw=Gateway('http://aisl','profile','rev-p',client=client)
    result=gw.ctl_entity_context('123')
    assert result['link_count']==2 and result['complete']
    assert result['cross_product_sql_identity_status']=='not_proven'
    assert len(result['published_ctl_dependency_gaps'])==1
    assert result['published_ctl_dependency_count']==0
    assert gw.ctl_entity_context('999')['status']=='not_found'
    client.close()


def test_a5_sql_context_exact_keys_and_bounded_samples():
    rows={
      'joins':[{'query_id':'q1','sql_join_edge_id':str(n)} for n in range(7)],
      'relation-materializations':[{'workflow_context_file':'a.yaml','materialization_id':str(n)} for n in range(9)],
      'workflow-bindings':[{'file':'a.yaml','sql_workflow_binding_id':'w1'}, {'file':'b.yaml','sql_workflow_binding_id':'w2'}],
      'workflow-context-files':[{'workflow_context_file':'a.yaml','reachable_file':'ctx.json'}],
    }
    def handle(req):
        kind=req.url.path.split('/')[-1]
        full=rows.get(kind,[])
        off=int(req.url.params.get('offset','0'));limit=int(req.url.params.get('limit','500'))
        return httpx.Response(200,json={'items':full[off:off+limit], 'page':{'total':len(full)}})
    client=httpx.Client(base_url='http://aisl',transport=httpx.MockTransport(handle))
    gw=Gateway('http://aisl','profile','rev-p',client=client)
    result=gw.sql_execution_context({'q1'}, {'a.yaml'},sample_limit=2)
    assert result['categories']['joins']['count']==7
    assert result['categories']['joins']['sample_count']==2
    assert result['categories']['joins']['has_more'] is True
    assert result['categories']['workflow-bindings']['count']==1
    assert result['categories']['workflow-bindings']['selection_key']=='file'
    assert result['complete']
    client.close()
