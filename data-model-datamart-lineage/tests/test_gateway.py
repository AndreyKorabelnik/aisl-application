from __future__ import annotations

from types import SimpleNamespace

from aisl_data_model_datamart_lineage.contracts import RevisionBinding
from aisl_data_model_datamart_lineage.gateway import KnowledgeApiGateway


class _Revision:
    def list_products(self, *, capability):
        assert capability == "common.observed-record-set"
        return [SimpleNamespace(
            model_kind="logical-physical-mapping-evidence",
            artifact_id="tsa-mapping",
        )]


class _Client:
    def __init__(self):
        self.calls = []

    def revision(self, system_id, revision_id):
        assert (system_id, revision_id) == ("ucp-tsa-v4", "rev-tsa")
        return _Revision()

    def get_json(self, path, *, params):
        self.calls.append((path, params))
        if params["item_kind"] == "field_mapping":
            return {
                "items": [{
                    "item_kind": "field_mapping",
                    "local_id": "field-1",
                    "payload": {
                        "entity_mapping_id": "entity-1",
                        "logical_type_name": "com.example.BirthDate",
                        "logical_field_name": "value",
                        "physical_column_name": "value",
                        "mapping_status": "observed_exact",
                    },
                }]
            }
        assert params["item_kind"] == "entity_mapping"
        assert params["filter_path"] == ["/mapping_id"]
        assert params["filter_value"] == ["entity-1"]
        return {
            "items": [{
                "item_kind": "entity_mapping",
                "local_id": "entity-1",
                "payload": {
                    "mapping_id": "entity-1",
                    "physical_table_name": "com_example_birthdate",
                    "mapping_status": "observed_exact",
                },
            }]
        }



def test_tsa_field_mapping_resolves_explicit_entity_mapping_reference():
    gateway = KnowledgeApiGateway.__new__(KnowledgeApiGateway)
    gateway._client = _Client()
    rows = gateway.find_tsa_field_mappings(
        RevisionBinding("ucp-tsa-v4", "rev-tsa"),
        logical_type_name="com.example.BirthDate",
        logical_field_name="value",
    )
    assert len(rows) == 1
    assert rows[0]["payload"]["physical_table_name"] == "com_example_birthdate"
    assert rows[0]["entity_mapping_record"]["local_id"] == "entity-1"
    assert len(gateway._client.calls) == 2


class _PagedSqlClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, *, params):
        self.calls.append((path, dict(params)))
        if path.endswith('/sql/target-column-lineage'):
            offset = params['offset']
            if offset == 0:
                return {
                    'target_resolution': {'logical_target_name': 'epk_client'},
                    'items': [{'sql_recursive_column_lineage_id': 'a'}],
                    'page': {'offset': 0, 'limit': 1, 'total': 2},
                }
            assert offset == 1
            return {
                'target_resolution': {'logical_target_name': 'epk_client'},
                'items': [{'sql_recursive_column_lineage_id': 'b'}],
                'page': {'offset': 1, 'limit': 1, 'total': 2},
            }
        if path.endswith('/sql/relation-materializations'):
            offset = params['offset']
            if offset == 0:
                return {
                    'items': [{'materialization_id': 'm1'}],
                    'page': {'offset': 0, 'limit': 500, 'total': 2},
                }
            assert offset == 1
            return {
                'items': [{'materialization_id': 'm2'}],
                'page': {'offset': 1, 'limit': 500, 'total': 2},
            }
        raise AssertionError(path)


def test_target_column_lineage_paginates_and_caches_complete_result():
    gateway = KnowledgeApiGateway.__new__(KnowledgeApiGateway)
    gateway._client = _PagedSqlClient()
    binding = RevisionBinding('profile', 'rev-profile')
    first = gateway.get_sql_target_column_lineage(
        binding, target_relation='epk_client', repo_id='repo', limit=1
    )
    second = gateway.get_sql_target_column_lineage(
        binding, target_relation='epk_client', repo_id='repo', limit=1
    )
    assert [x['sql_recursive_column_lineage_id'] for x in first['items']] == ['a', 'b']
    assert first['page']['total'] == 2
    assert second is first
    lineage_calls = [x for x in gateway._client.calls if x[0].endswith('/sql/target-column-lineage')]
    assert [x[1]['offset'] for x in lineage_calls] == [0, 1]


def test_relation_materializations_paginate_and_cache():
    gateway = KnowledgeApiGateway.__new__(KnowledgeApiGateway)
    gateway._client = _PagedSqlClient()
    binding = RevisionBinding('profile', 'rev-profile')
    first = gateway.list_sql_relation_materializations(binding)
    second = gateway.list_sql_relation_materializations(binding)
    assert [x['materialization_id'] for x in first] == ['m1', 'm2']
    assert second is first
    calls = [x for x in gateway._client.calls if x[0].endswith('/sql/relation-materializations')]
    assert [x[1]['offset'] for x in calls] == [0, 1]
