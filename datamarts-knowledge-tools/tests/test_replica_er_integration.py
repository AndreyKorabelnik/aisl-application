"""Task 54 integration: Task 49 is the only builder for replica-model relationships."""
from types import SimpleNamespace

from aisl_ucp_tsa_replica_er import RevisionBinding, build_replica_model
from aisl_datamarts_knowledge_tools.replica_er import ReplicaERIndex
from aisl_datamarts_knowledge_tools.tools import DataMartsTools


def _model():
    ucp = RevisionBinding('ucp', 'rev-u')
    tsa = RevisionBinding('tsa', 'rev-t')
    types = [
        {'type_occurrence_id': 'i', 'fully_qualified_name': 'demo.Individual', 'simple_name': 'Individual'},
        {'type_occurrence_id': 'b', 'fully_qualified_name': 'demo.BirthDate', 'simple_name': 'BirthDate'},
    ]
    fields = [
        {'field_occurrence_id': 'if', 'owner_type_occurrence_id': 'i', 'name': 'birthDate', 'declared_type_expression': 'BirthDate'},
        {'field_occurrence_id': 'id', 'owner_type_occurrence_id': 'i', 'name': 'id', 'declared_type_expression': 'String'},
        {'field_occurrence_id': 'bid', 'owner_type_occurrence_id': 'b', 'name': 'id', 'declared_type_expression': 'String'},
    ]
    relationships = [{'relationship_occurrence_id': 'r', 'source_type_occurrence_id': 'i',
                      'target_type_occurrence_id': 'b', 'field_occurrence_id': 'if',
                      'relationship_kind': 'declared_field_type_reference', 'resolution_status': 'resolved'}]
    ann = [{'annotation_occurrence_id': 'a', 'target_kind': 'type', 'target_occurrence_id': 'i',
            'annotation_name': 'MetaRootEntity', 'structured_arguments_json': [
                {'name': 'id', 'expression_tree': {'literal_value': 'id'}}]},
           {'annotation_occurrence_id': 'ab', 'target_kind': 'type', 'target_occurrence_id': 'b',
            'annotation_name': 'MetaRootEntity', 'structured_arguments_json': [
                {'name': 'id', 'expression_tree': {'literal_value': 'id'}}]}]
    def ent(fqcn, table, mid):
        return {'local_id': mid, 'payload': {'mapping_id': mid, 'mapping_status': 'observed_exact',
                'logical_type_name': fqcn, 'physical_table_name': table}}
    def fld(fqcn, name, column, eid):
        return {'local_id': f'{eid}:{name}', 'payload': {'mapping_id': f'{eid}:{name}',
                'mapping_status': 'observed_exact', 'logical_type_name': fqcn,
                'logical_field_name': name, 'physical_column_name': column, 'entity_mapping_id': eid}}
    return build_replica_model(ucp=ucp, tsa=tsa, ucp_dataset={
        'types': types, 'fields': fields, 'effective_fields': [],
        'relationships': relationships, 'annotations': ann,
    }, tsa_mappings={
        'entity_mappings': [ent('demo.Individual', 'replica_individual', 'e1'),
                            ent('demo.BirthDate', 'replica_birthdate', 'e2')],
        'field_mappings': [fld('demo.Individual', 'id', 'id', 'e1'),
                           fld('demo.BirthDate', 'id', 'id', 'e2')],
    })


class MockGateway:
    def __init__(self, role):
        self.system_id = role
        self.revision_id = {'profile': 'rev-p', 'ucp': 'rev-u', 'tsa': 'rev-t'}[role]
        self.client = SimpleNamespace(base_url='http://aisl.test')
        self.requests = []

    def relations(self):
        return []

    def declared_records(self, kind):
        self.requests.append(('declared', kind))
        return []

    def tsa_mapping_records(self):
        self.requests.append(('tsa',))
        entities = [{'local_id': 'e1', 'payload': {'mapping_id': 'e1', 'mapping_status': 'observed_exact',
                 'physical_table_name': 'replica_individual', 'logical_type_name': 'demo.Individual'}},
                {'local_id': 'e2', 'payload': {'mapping_id': 'e2', 'mapping_status': 'observed_exact',
                 'physical_table_name': 'replica_birthdate', 'logical_type_name': 'demo.BirthDate'}}]
        return [], entities

    def target_lineage(self, relation, **kw):
        return {'items': [], 'item_count': 0, 'target_resolution': {'status': 'not_found'}, 'gaps': []}

    def downstream_candidates(self, relation, **kw):
        return {'candidate_count': 0, 'candidates': []}

    def close(self):
        pass


def _tools():
    t = DataMartsTools(MockGateway('profile'),
                       model_gateway=MockGateway('ucp'), replica_gateway=MockGateway('tsa'))
    calls = []
    er = ReplicaERIndex('http://aisl.test', model_system='ucp', model_revision='rev-u',
                        replica_system='tsa', replica_revision='rev-t',
                        load=lambda: (calls.append('load'), _model())[1])
    t._replica_er = er
    return t, calls


def test_task49_full_graph_incoming_outgoing_and_no_physical_claims():
    t, calls = _tools()
    outbound = t.get_dependencies(relation='replica_individual')
    assert outbound['edge_count'] == 0  # no SQL target-column lineage
    r = outbound['replica_logical_relationships']
    assert r['relationship_count'] == 1
    assert r['outgoing_count'] == 1 and r['incoming_count'] == 0
    assert r['total_published_projection_relationships'] == 1
    assert r['relationships'][0]['relationship_field'] == 'birthDate'
    assert r['relationships'][0]['status'] == 'confirmed_ucp_relationship_projected_to_replicas'
    assert r['relationships'][0]['physical_join_status'] == 'not_observed'
    assert r['relationships'][0]['physical_join_condition'] == ''
    assert r['relationships'][0]['data_transfer_status'] == 'not_proven'
    inbound = t.get_dependencies(relation='replica_birthdate')
    assert inbound['replica_logical_relationships']['incoming_count'] == 1
    assert inbound['replica_logical_relationships']['outgoing_count'] == 0
    assert calls == ['load']  # once for pinned revision pair
    t.close()


def test_column_query_does_not_upgrade_logical_edge_to_attribute_lineage():
    t, _ = _tools()
    x = t.get_dependencies(relation='replica_birthdate', column='id')
    r = x['replica_logical_relationships']
    assert r['relationship_count'] == 1
    assert r['relation_level_only']
    assert r['column_evidence_status'] == 'not_proven_by_logical_relationship'
    assert r['relationships'][0]['attribute_lineage_status'] == 'not_proven'
    t.close()


def test_unrelated_sql_relation_does_not_load_replica_graph():
    t, calls = _tools()
    x = t.get_dependencies(relation='epk_client')
    assert x['replica_logical_relationship_status'] == 'not_a_published_exact_replica'
    assert x['replica_logical_relationships'] is None
    assert calls == []
    t.close()


def test_task49_table_details_keys_and_fields_are_reused():
    t, calls = _tools()
    x = t.get_object_details(relation='replica_individual')
    assert x['count'] == 1
    y = x['matches'][0]['ucp_tsa_replica_er']
    assert y['table']['key_replica_columns'] == ['id']
    assert y['table']['physical_constraint_status'] == 'not_observed'
    assert y['replica_fields'][0]['replica_column'] == 'id'
    assert calls == ['load']
    t.close()


def test_unavailable_er_is_explicit_and_sql_results_survive():
    t, _ = _tools()
    t._replica_er = ReplicaERIndex('http://aisl.test', model_system='ucp', model_revision='rev-u',
                          replica_system='tsa', replica_revision='rev-t',
                          load=lambda: (_ for _ in ()).throw(RuntimeError('missing published product')))
    result = t.get_dependencies(relation='replica_birthdate')
    assert result['replica_logical_relationship_status'] == 'unavailable'
    assert 'missing published product' in result['replica_logical_relationships']['gap']
    assert result['replica_logical_relationships']['complete_projected_model'] is False
    t.close()


def test_replica_model_revision_mismatch_fails_closed():
    er = ReplicaERIndex('http://aisl.test', model_system='ucp', model_revision='wrong-rev',
                        replica_system='tsa', replica_revision='rev-t', load=_model)
    try:
        er.relationships('replica_birthdate')
    except ValueError as e:
        assert 'binding mismatch' in str(e)
    else:
        assert False, 'unpinned model cannot be projected into other revision'
