from __future__ import annotations

from types import SimpleNamespace

import pytest

from aisl_ctl_topology.gateway import AislCtlGateway, CTL_RECORD_KINDS


class FakePublicSdk:
    def __init__(self):
        self.calls=[]
    def revision(self, sys, rev):
        assert (sys,rev)==('profile','rev-1')
        return SimpleNamespace(list_products=lambda capability:[SimpleNamespace(
            model_kind='ctl-orchestration',schema_version='ctl-orchestration/v1',artifact_id='product-1'
        )])
    def get_json(self,path,params):
        self.calls.append((path,params))
        kind=path.split('/')[-1]
        assert kind in CTL_RECORD_KINDS
        return {'system_id':'profile','revision_id':'rev-1','artifact_id':'product-1',
                'record_kind':kind,'items':[{'flow_id':'a'}] if kind=='ctl_flow' else [],
                'page':{'total':1 if kind=='ctl_flow' else 0}}


def test_gateway_loads_only_public_revision_pinned_pages():
    gateway=object.__new__(AislCtlGateway)
    fake=FakePublicSdk()
    gateway._client=fake
    result=gateway.load_revision('profile','rev-1')
    assert len(result['records'])==8
    assert result['records']['ctl_flow']==[{'flow_id':'a'}]
    assert len(fake.calls)==8
    assert all(params['revision_id']=='rev-1' and params['limit']==500 for _,params in fake.calls)


def test_gateway_detects_public_identity_mismatch():
    gateway=object.__new__(AislCtlGateway)
    fake=FakePublicSdk()
    old=fake.get_json
    def incorrect(path,params):
        row=old(path,params)
        row['revision_id']='wrong'
        return row
    fake.get_json=incorrect
    gateway._client=fake
    with pytest.raises(RuntimeError,match='identity mismatch'):
        gateway.load_revision('profile','rev-1')
