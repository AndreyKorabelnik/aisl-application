from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from aisl_ctl_topology.builder import build_topology
from aisl_ctl_topology.gateway import CTL_RECORD_KINDS
from aisl_ctl_topology.output import write_csv, write_json, write_mermaid


def snapshot(system, *, producer=False, consumer=False, stat='2', multiple=False):
    d={kind:[] for kind in CTL_RECORD_KINDS}
    if producer:
        for idx in range(2 if multiple else 1):
            fid=f'p{idx}'
            d['ctl_flow'].append({'flow_id':fid,'flow_name':f'producer_{idx}','active':True,'source_file':'ctl/prod.yml'})
            d['ctl_flow_entity'].append({'flow_id':fid,'flow_name':f'producer_{idx}','active':True,
                                         'relation':'published_entity','profile':'prod','entity_id':'935120603',
                                         'published_stats_json':'["2"]','source_file':'ctl/prod.yml'})
    if consumer:
        d['ctl_flow'].append({'flow_id':'c','flow_name':'init_b2c_profile_fl','active':True,'source_file':'ctl/consumer.yml'})
        d['ctl_trigger'].append({'trigger_id':'t','flow_id':'c','flow_name':'init_b2c_profile_fl',
                                 'active':True,'upstream_profile':'prod','upstream_entity_id':'935120603',
                                 'statistic_id':stat,'source_file':'ctl/consumer.yml'})
        d['ctl_dependency_gap'].append({'gap_id':'g','trigger_id':'t','reason_code':'NO_ENTITY_DECLARATION_IN_REPOSITORY'})
    return {'system_id':system,'revision_id':'rev-1','artifact_id':f'artifact-{system}','records':d}


def test_cross_revision_proven_and_three_outputs(tmp_path):
    result=build_topology([snapshot('profile',producer=True),snapshot('insurance',consumer=True)])
    assert result['counts']=={'revisions':2,'flows':2,'edges':1,'gaps':0}
    edge=result['edges'][0]
    assert (edge['producer_system'],edge['consumer_system'],edge['entity_id'],edge['statistic_id']) == ('profile','insurance','935120603','2')
    assert edge['status']=='resolved_unique'
    assert next(r for r in result['revisions'] if r['system_id']=='insurance')['records']['ctl_dependency_gap']  # source gap retained
    write_json(result,tmp_path/'out.json')
    write_csv(result,tmp_path/'out.csv')
    write_mermaid(result,tmp_path/'out.mmd')
    assert len(json.loads((tmp_path/'out.json').read_text())['revisions'])==2
    rows=list(csv.DictReader((tmp_path/'out.csv').open(encoding='utf-8-sig')))
    assert rows[0]['row_kind']=='dependency'
    assert rows[0]['status']=='resolved_unique'
    assert 'flowchart LR' in (tmp_path/'out.mmd').read_text()
    assert 'init_b2c_profile_fl' in (tmp_path/'out.mmd').read_text()


def test_stat_mismatch_is_gap_not_edge():
    result=build_topology([snapshot('profile',producer=True),snapshot('insurance',consumer=True,stat='15')])
    assert not result['edges']
    assert result['gaps'][0]['status']=='statistic_not_confirmed'


def test_multi_producer_keeps_ambiguity():
    result=build_topology([snapshot('profile',producer=True,multiple=True),snapshot('insurance',consumer=True)])
    assert len(result['edges'])==2
    assert {e['status'] for e in result['edges']}=={'ambiguous_multiple'}
    assert result['gaps'][0]['status']=='ambiguous_multiple'


def test_missing_producer_half_wire_and_isolated_flow():
    result=build_topology([snapshot('insurance',consumer=True)])
    assert not result['edges']
    assert result['gaps'][0]['status']=='external_half_wire'
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/'half-wire.mmd'
        write_mermaid(result,path)
        rendered=path.read_text()
        assert 'unresolved upstream' in rendered and 'external_half_wire' in rendered
        assert '-.->' in rendered



def test_duplicate_revision_rejected():
    with pytest.raises(ValueError,match='duplicate pinned'):
        build_topology([snapshot('p'),snapshot('p')])


def test_local_dependency_kept_separate_from_cross_candidates():
    src=snapshot('profile',producer=True,consumer=True)
    src['records']['ctl_dependency'].append({
        'trigger_id':'t','producer_flow_id':'p0','producer_flow_name':'producer_0',
        'consumer_flow_id':'c','consumer_flow_name':'init_b2c_profile_fl','resolution_status':'resolved_unique',
        'profile':'prod','entity_id':'935120603','statistic_id':'2',
        'producer_stat_supported':True,'producer_candidate_count':1,
    })
    result=build_topology([src,snapshot('elsewhere',producer=True)])
    assert len(result['edges'])==1
    assert result['edges'][0]['kind']=='repository_local'
