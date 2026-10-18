"""A6 consumer-visible: one Task46 composer, separate Task49 evidence, lossless pages."""
import pytest

from test_replica_er_integration import _tools
from aisl_datamarts_knowledge_tools.catalog import tool_definitions


class AcceptedTask46:
    def __init__(self):
        self.calls = []
    def for_field(self, *, relation, column, mapped_fields):
        self.calls.append((relation, column))
        assert any(f['replica_column'] == column and f['mapping_status'] == 'observed_exact'
                   for f in mapped_fields)
        return {'status': 'available', 'rows': [
            {'source_type_fqcn': 'demo.BirthDate', 'source_field': 'id',
             'replica_relation': relation, 'replica_column': column,
             'target_relation': 'epk_client', 'target_column': c,
             'lineage_depth': 4, 'status': 'confirmed_lineage_target_relation_ambiguous',
             'gap': 'physical_target_ambiguous', 'provenance_json': '{"ucp":"observed"}',
             'path_segments_json': '["ucp","tsa","sql"]'}
            for c in ('birth_dt', 'birth_dt', 'united_person_hash')],
            'total_count': 3, 'confirmed_branch_count': 3, 'complete': True,
            'bindings': [{'system_id': 'ucp', 'revision_id': 'rev-u'},
                         {'system_id': 'tsa', 'revision_id': 'rev-t'},
                         {'system_id': 'profile', 'revision_id': 'rev-p'}]}


def test_lineage_reuses_exact_task46_and_preserves_branch_evidence():
    t, _ = _tools()
    fake = AcceptedTask46()
    t._cross_revision = fake
    try:
        lineage = t.get_attribute_lineage(relation='replica_birthdate', column='id')
        assert lineage['item_count'] == 0  # no SQL *target* facts for source replica
        assert lineage['cross_revision_lineage_status'] == 'available'
        paths = lineage['cross_revision_lineage']
        assert paths['total_count'] == 3 and paths['confirmed_branch_count'] == 3
        assert not paths['details_included']
        assert all('provenance_json' not in x for x in paths['rows'])
        assert all('ambiguous' in x['status'] for x in paths['rows'])
        assert len(fake.calls) == 1
        detail = t.get_evidence(relation='replica_birthdate', column='id',
                                evidence_source='task46', record_index=2)
        assert detail['source_status'] == 'available'
        assert detail['item_count'] == 3 and len(detail['items']) == 1
        assert detail['items'][0]['target_column'] == 'united_person_hash'
        assert 'provenance_json' in detail['items'][0]
        assert detail['bindings'][0]['revision_id'] == 'rev-u'
        assert 'not_publisher_identity' in detail['selection_policy']
        assert len(fake.calls) == 2  # composer result cache belongs to Task46 bridge
    finally:
        t.close()


def test_task49_relation_evidence_is_not_promoted_to_physical_join():
    t, _ = _tools()
    try:
        detail = t.get_evidence(relation='replica_birthdate', evidence_source='task49', record_index=0)
        assert detail['source_status'] == 'available'
        assert detail['item_count'] == 1
        row = detail['items'][0]
        assert row['relationship_field'] == 'birthDate'
        assert row['physical_join_status'] == 'not_observed'
        assert row['data_transfer_status'] == 'not_proven'
        assert detail['ucp_binding']['revision_id'] == 'rev-u'
        assert t.get_evidence(relation='replica_birthdate', evidence_source='task49', record_index=7)['items'] == []
        not_replica = t.get_evidence(relation='nonexistent', evidence_source='task49')
        assert not_replica['source_status'] == 'not_exact_replica'
    finally:
        t.close()


def test_evidence_validates_scope_and_tool_contract():
    t, _ = _tools()
    try:
        with pytest.raises(ValueError, match='column is required'):
            t.get_evidence(relation='replica_birthdate', evidence_source='task46')
        with pytest.raises(ValueError, match='evidence_source'):
            t.get_evidence(relation='replica_birthdate', evidence_source='nonsense')
        with pytest.raises(ValueError, match='offset'):
            t.get_evidence(relation='replica_birthdate', offset=-1)
        defs = {x['function']['name']: x['function']['parameters']['properties']
                for x in tool_definitions()}
        assert len(defs) == 7
        assert 'evidence_source' in defs['get_evidence']
        assert 'record_index' in defs['get_evidence']
        assert 'include_cross_revision_details' in defs['get_attribute_lineage']
    finally:
        t.close()


def test_unmapped_source_never_calls_task46():
    t, _ = _tools()
    fake = AcceptedTask46()
    t._cross_revision = fake
    try:
        x = t.get_attribute_lineage(relation='epk_client', column='birth_dt')
        assert x['cross_revision_lineage_status'] == 'not_exact_replica'
        assert not fake.calls
        e = t.get_evidence(relation='epk_client', column='birth_dt', evidence_source='task46')
        assert e['source_status'] == 'not_exact_replica' and e['items'] == []
    finally:
        t.close()


def test_sql_lineage_pagination_is_lossless_without_exposing_full_payload():
    from test_a5_integrations import ManyGateway
    from aisl_datamarts_knowledge_tools.tools import DataMartsTools
    t = DataMartsTools(ManyGateway())
    try:
        first = t.get_attribute_lineage(relation='epk_client', column='birth_dt', sql_limit=15)
        assert first['item_count'] == 41
        assert len(first['items']) == 15
        assert first['sql_page']['next_offset'] == 15
        assert not first['sql_details_included']
        assert 'transformation_path_json' not in first['items'][0]
        all_ids = []
        for offset in (0, 15, 30):
            page = t.get_attribute_lineage(relation='epk_client', column='birth_dt',
                                           sql_offset=offset, sql_limit=15)
            all_ids.extend(row['sql_recursive_column_lineage_id'] for row in page['items'])
        assert len(all_ids) == len(set(all_ids)) == 41
        tail = t.get_attribute_lineage(relation='epk_client', column='birth_dt',
                                       sql_offset=40, sql_limit=20, include_sql_details=True)
        assert tail['sql_page']['has_more'] is False
        assert 'transformation_path_json' in tail['items'][0]
        original_evidence = t.get_evidence(relation='epk_client', column='birth_dt', offset=40)
        assert original_evidence['item_count'] == 41 and len(original_evidence['items']) == 1
        with pytest.raises(ValueError, match='sql_offset'):
            t.get_attribute_lineage(relation='epk_client', column='birth_dt', sql_limit=0)
    finally:
        t.close()
