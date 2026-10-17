"""Smoke test with fields captured from actual public Profile FL API readback."""
import json
from pathlib import Path
import httpx
from aisl_datamarts_knowledge_tools.gateway import Gateway
from aisl_datamarts_knowledge_tools.tools import DataMartsTools


def test_real_profile_fl_api_shape():
    sample=json.loads((Path(__file__).parent/'fixtures/public_api_birth_dt_sample.json').read_text())
    def handler(req):
        if req.url.path.endswith('/sql/target-column-lineage'):
            items=sample['lineage']['items']
            offset=int(req.url.params.get('offset',0))
            return httpx.Response(200,json={**sample['lineage'],
                'items':items[offset:offset+500],
                'page':{'total':len(items), 'offset':offset}})
        if req.url.path.endswith('/sql/query-context'):
            return httpx.Response(200,json=sample['context'])
        if req.url.path.endswith('/sql/target-candidates'):
            return httpx.Response(200,json={'candidates':[],'candidate_count':0})
        raise AssertionError(req.url.path)
    cl=httpx.Client(base_url='http://test.local',transport=httpx.MockTransport(handler))
    tools=DataMartsTools(Gateway('http://test.local','profile','rev-actual',client=cl))
    try:
        result=tools.get_attribute_lineage(relation='epk_client',column='birth_dt')
        assert result['item_count']==len(sample['lineage']['items'])
        assert all(i['target_column']=='birth_dt' for i in result['items'])
        assert result['target_resolution']['status']==sample['lineage']['target_resolution']['status']
        context=tools.get_calculation_logic(query_id=sample['context']['query_id'],repo_id=sample['context']['repo_id'])
        assert context['selection_status']=='selected'
        assert any(p['output_name']=='birth_dt' for p in context['projections'])
        edge=tools.get_dependencies(relation='epk_client',column='birth_dt')
        assert edge['edge_count']==len(sample['lineage']['items'])
    finally:
        tools.close();cl.close()
