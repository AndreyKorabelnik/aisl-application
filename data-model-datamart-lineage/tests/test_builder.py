from __future__ import annotations

import json

from aisl_data_model_datamart_lineage.builder import build_lineage, list_source_fields
from aisl_data_model_datamart_lineage.contracts import RevisionBinding


SOURCE = RevisionBinding("ucp-data-model", "rev-source")
TSA = RevisionBinding("ucp-tsa-v4", "rev-tsa")
PROFILE = RevisionBinding("datamart_profile_fl", "rev-profile")
FQCN = "com.sbt.bm.ucp.retail.model.individual.BirthDate"
BASE = "com_sbt_bm_ucp_retail_model_individual_birthdate"


class Gateway:
    def search_declared_objects(self, binding, *, search, include_fields=True):
        assert binding == SOURCE
        return [{
            "object_id": "birth-date", "name": "BirthDate", "fqcn": FQCN,
            "binding_summary": {
                "incoming_examples": [{"source_name": "Individual", "source_field": "birthDate"}]
            },
        }]

    def get_data_model_object_context(self, binding, *, object_id):
        assert binding == SOURCE
        assert object_id == "birth-date"
        return {
            "schema_version": "data_model_object_context/v3",
            "object": {"object_id": "birth-date", "name": "BirthDate", "fqcn": FQCN},
            "fields": [{"field_id": "value", "name": "value", "type": "java.time.LocalDate"}],
            "relationships": [],
        }

    def find_tsa_field_mappings(self, binding, *, logical_type_name, logical_field_name):
        assert binding == TSA
        assert logical_type_name == FQCN
        assert logical_field_name == "value"
        return [{
            "item_kind": "field_mapping",
            "local_id": "mapping-birthdate-value",
            "payload": {
                "logical_type_name": FQCN,
                "logical_field_name": "value",
                "physical_table_name": BASE,
                "physical_column_name": "value",
                "mapping_status": "observed_exact",
                "mapping_basis": "observed_tsa_primitive_field_source_accessor_plus_ucp_replica_naming_contract",
                "source_refs": [{"relative_file": "BirthDateChangeVector.java", "line_start": 21}],
            },
        }]

    def find_sql_target_candidates(self, binding, *, source_relations, source_column, limit=100):
        assert binding == PROFILE
        assert source_relations == [BASE, BASE + "_hist", BASE + "_delta"]
        assert source_column == "value"
        return {
            "schema_version": "sql-target-candidates/v2",
            "candidate_count": 1,
            "candidates": [{
                "rank": 1,
                "score": 147,
                "repo_id": "datamart_profile_fl",
                "logical_target_name": "epk_client",
                "source_relation_matches": [
                    {"logical_name": BASE, "relation_name": "${snp}." + BASE},
                    {"logical_name": BASE + "_hist", "relation_name": "${hist}." + BASE + "_hist"},
                ],
                "source_column_matches": [
                    {"column_name": "value", "relation_name": "${snp}." + BASE},
                    {"column_name": "value", "relation_name": "${hist}." + BASE + "_hist"},
                ],
                "target_relation_candidates": [
                    "custom_b2c_profile_fl.epk_client",
                    "custom_b2c_profile_fl.epk_client_v2",
                ],
            }],
        }

    def get_sql_target_column_lineage(self, binding, *, target_relation, repo_id, limit=500):
        assert binding == PROFILE
        assert target_relation == "epk_client"
        assert repo_id == "datamart_profile_fl"
        base_path = [
            {"kind": "workflow_target", "target_logical_name": "epk_client"},
            {"kind": "observed_relation_materialization", "materialization_id": "m-stg"},
            {"kind": "observed_relation_materialization", "materialization_id": "m-joined"},
            {"kind": "observed_relation_materialization", "materialization_id": "m-bv"},
            {"kind": "observed_relation_materialization", "materialization_id": "m-snp"},
        ]
        hist_path = [*base_path[:-1], {"kind": "observed_relation_materialization", "materialization_id": "m-hist"}]
        return {
            "lineage_schema_version": "sql-target-column-lineage/v3",
            "requested_target_relation_name": "epk_client",
            "workflow_target_logical_name": "epk_client",
            "target_resolution": {
                "logical_target_name": "epk_client",
                "logical_target_status": "confirmed_unique",
                "physical_relation_status": "ambiguous",
                "physical_relation_recommendation_status": "probable_ranked",
                "recommended_target_relation": "custom_b2c_profile_fl.epk_client",
                "physical_relation_candidates": [
                    "custom_b2c_profile_fl.epk_client",
                    "custom_b2c_profile_fl.epk_client_v2",
                ],
            },
            "items": [
                {
                    "sql_recursive_column_lineage_id": "lineage-base-1",
                    "target_relation_name": None,
                    "workflow_target_logical_name": "epk_client",
                    "target_column": "birth_dt",
                    "terminal_relation_name": "${snp_src_schema_name}." + BASE,
                    "terminal_column": "value",
                    "recursion_depth": 18,
                    "lineage_status": "confirmed",
                    "branch_path_json": base_path,
                    "transformation_path_json": [
                        {"expression": "CAST(bdate.birth_date AS TIMESTAMP) AS birth_dt"},
                        {"expression": "value AS birth_date"},
                    ],
                    "mapping_basis": "workflow_recursive_lineage",
                    "evidence_json": [{"relative_file": "sql/epk_client.sql", "line_start": 10}],
                },
                {
                    "sql_recursive_column_lineage_id": "lineage-hist-1",
                    "target_relation_name": None,
                    "workflow_target_logical_name": "epk_client",
                    "target_column": "birth_dt",
                    "terminal_relation_name": "${hist_src_schema_name}." + BASE + "_hist",
                    "terminal_column": "value",
                    "recursion_depth": 18,
                    "lineage_status": "confirmed",
                    "branch_path_json": hist_path,
                    "transformation_path_json": [
                        {"expression": "CAST(bdate.birth_date AS TIMESTAMP) AS birth_dt"},
                        {"expression": "value AS birth_date"},
                    ],
                    "mapping_basis": "workflow_recursive_lineage",
                    "evidence_json": [{"relative_file": "sql/epk_client.sql", "line_start": 10}],
                },
            ],
        }

    def list_sql_relation_materializations(self, binding):
        assert binding == PROFILE
        common = [
            {"materialization_id": "m-stg", "query_file": "stg_epk_client_birthdate.sql", "output_table_name": "stg_epk_client_birthdate", "resolution_status": "matched", "mapping_basis": "script_call"},
            {"materialization_id": "m-joined", "query_file": "stg_epk_client_birthdate__joined.sql", "output_table_name": "stg_epk_client_birthdate__joined", "resolution_status": "matched", "mapping_basis": "script_call"},
            {"materialization_id": "m-bv", "query_file": "stg_epk_client_birthdate_bv.sql", "output_table_name": "stg_epk_client_birthdate_bv", "resolution_status": "matched", "mapping_basis": "script_call"},
        ]
        return [
            *common,
            {"materialization_id": "m-snp", "query_file": "stg_epk_client_birthdate_snp.sql", "output_table_name": "stg_epk_client_birthdate_union", "resolution_status": "matched", "mapping_basis": "script_call"},
            {"materialization_id": "m-hist", "query_file": "stg_epk_client_birthdate_hist.sql", "output_table_name": "stg_epk_client_birthdate_union", "resolution_status": "matched", "mapping_basis": "script_call"},
        ]



def test_candidate_exact_source_evidence_accepts_column_alias_at_same_observed_position() -> None:
    from aisl_data_model_datamart_lineage.builder import _candidate_has_exact_source_evidence

    candidate = {
        "source_relation_matches": [{
            "file": "sql/stg_individualname_snp.sql",
            "line_start": 1,
            "logical_name": "com_sbt_bm_ucp_retail_model_individual_individualname",
            "relation_name": "${snp}.com_sbt_bm_ucp_retail_model_individual_individualname",
        }],
        "source_column_matches": [{
            "file": "sql/stg_individualname_snp.sql",
            "line_start": 1,
            "column_name": "surname",
            "relation_name": "source",
        }],
    }

    assert _candidate_has_exact_source_evidence(
        candidate,
        replica_relation="com_sbt_bm_ucp_retail_model_individual_individualname",
        replica_column="surname",
    )


def test_candidate_exact_source_evidence_accepts_exact_relation_even_when_column_match_is_elsewhere() -> None:
    from aisl_data_model_datamart_lineage.builder import _candidate_has_exact_source_evidence

    candidate = {
        "source_relation_matches": [{
            "file": "sql/stg_individualname_snp.sql",
            "line_start": 1,
            "logical_name": "com_sbt_bm_ucp_retail_model_individual_individualname",
        }],
        "source_column_matches": [{
            "file": "sql/stg_individualname_snp.sql",
            "line_start": 2,
            "column_name": "surname",
            "relation_name": "source",
        }],
    }

    assert _candidate_has_exact_source_evidence(
        candidate,
        replica_relation="com_sbt_bm_ucp_retail_model_individual_individualname",
        replica_column="surname",
    )


def test_candidate_exact_source_evidence_rejects_missing_exact_relation() -> None:
    from aisl_data_model_datamart_lineage.builder import _candidate_has_exact_source_evidence

    candidate = {
        "source_relation_matches": [{
            "file": "sql/other.sql",
            "line_start": 1,
            "logical_name": "unrelated_relation",
        }],
        "source_column_matches": [{
            "file": "sql/other.sql",
            "line_start": 1,
            "column_name": "name",
            "relation_name": "unrelated_relation",
        }],
    }

    assert not _candidate_has_exact_source_evidence(
        candidate,
        replica_relation="com_sbt_bm_ucp_retail_model_individual_individualname",
        replica_column="name",
    )

def test_birthdate_vertical_slice_preserves_base_and_hist_depth_and_ambiguity():
    rows = build_lineage(
        gateway=Gateway(),
        source=SOURCE,
        tsa=TSA,
        profile=PROFILE,
        source_object=FQCN,
        source_field="value",
    )
    assert len(rows) == 2
    assert [row["profile_representation_variant"] for row in rows] == ["base", "hist"]
    assert all(row["source_attribute_path"] == "Individual.birthDate → BirthDate.value" for row in rows)
    assert all(row["replica_relation"] == BASE for row in rows)
    assert all(row["target_relation"] == "custom_b2c_profile_fl.epk_client" for row in rows)
    assert all(row["target_column"] == "birth_dt" for row in rows)
    assert all(row["status"] == "confirmed_lineage_target_relation_ambiguous" for row in rows)
    assert all(row["gap"] == "physical_target_relation_ambiguous" for row in rows)
    assert all("value AS birth_date" in row["transformation_path"] for row in rows)
    assert all("CAST(bdate.birth_date AS TIMESTAMP) AS birth_dt" in row["transformation_path"] for row in rows)
    assert all(row["transformation_path"].startswith("value AS birth_date") for row in rows)
    assert all(row["transformation_path"].endswith("CAST(bdate.birth_date AS TIMESTAMP) AS birth_dt") for row in rows)
    segments = [json.loads(row["path_segments_json"]) for row in rows]
    assert all(items[-1]["recursion_depth"] == 18 for items in segments)
    assert all(len(items[-1]["branch_path"]) == 5 for items in segments)
    assert "stg_epk_client_birthdate_snp" in rows[0]["relation_path"]
    assert "stg_epk_client_birthdate_hist" in rows[1]["relation_path"]
    assert all("stg_epk_client_birthdate_union" in row["relation_path"] for row in rows)
    assert all(row["relation_path"].endswith("custom_b2c_profile_fl.epk_client.birth_dt") for row in rows)
    assert all(row["lineage_depth"] == 18 for row in rows)


def test_hist_variant_without_base_anchor_is_not_promoted():
    class HistOnly(Gateway):
        def get_sql_target_column_lineage(self, binding, *, target_relation, repo_id, limit=500):
            payload = super().get_sql_target_column_lineage(
                binding, target_relation=target_relation, repo_id=repo_id, limit=limit
            )
            payload["items"] = [payload["items"][1]]
            return payload

    rows = build_lineage(
        gateway=HistOnly(), source=SOURCE, tsa=TSA, profile=PROFILE,
        source_object=FQCN, source_field="value",
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "gap"
    assert rows[0]["gap"] == "profile_confirmed_lineage_not_found"


def test_tsa_multiple_exact_records_stay_ambiguous():
    class AmbiguousTsa(Gateway):
        def find_tsa_field_mappings(self, binding, *, logical_type_name, logical_field_name):
            one = super().find_tsa_field_mappings(
                binding, logical_type_name=logical_type_name, logical_field_name=logical_field_name
            )[0]
            two = dict(one)
            two["local_id"] = "other"
            return [one, two]

    rows = build_lineage(
        gateway=AmbiguousTsa(), source=SOURCE, tsa=TSA, profile=PROFILE,
        source_object=FQCN, source_field="value",
    )
    assert rows[0]["status"] == "ambiguity"
    assert rows[0]["gap"] == "tsa_field_mapping_ambiguous"


def test_distinct_confirmed_lineage_branches_are_not_collapsed():
    class DuplicateBranches(Gateway):
        def get_sql_target_column_lineage(self, binding, *, target_relation, repo_id, limit=500):
            payload = super().get_sql_target_column_lineage(
                binding, target_relation=target_relation, repo_id=repo_id, limit=limit
            )
            base = dict(payload["items"][0])
            base["sql_recursive_column_lineage_id"] = "lineage-base-2"
            hist = dict(payload["items"][1])
            hist["sql_recursive_column_lineage_id"] = "lineage-hist-2"
            payload["items"] = [payload["items"][0], base, payload["items"][1], hist]
            return payload

    rows = build_lineage(
        gateway=DuplicateBranches(), source=SOURCE, tsa=TSA, profile=PROFILE,
        source_object=FQCN, source_field="value",
    )
    assert len(rows) == 4
    lineage_ids = [json.loads(row["path_segments_json"])[-1]["lineage_id"] for row in rows]
    assert set(lineage_ids) == {"lineage-base-1", "lineage-base-2", "lineage-hist-1", "lineage-hist-2"}


def test_list_source_fields_uses_declared_model_context():
    fields = list_source_fields(gateway=Gateway(), source=SOURCE, source_object=FQCN)
    assert fields == ["value"]
