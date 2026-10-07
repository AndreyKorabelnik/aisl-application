from __future__ import annotations

import json

from aisl_kpk_profile_fl_lineage.csv_output import consumer_rows


UCP_SERVICE = "ucp_synapse_gateway_cpc_get_profile"
KPK_SERVICE = "cpc_efs_gateway_get_cards_by_client_id"


def _interaction_provenance() -> str:
    return json.dumps(
        [{"producer_repository": UCP_SERVICE}],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _row(
    *,
    endpoint: str,
    crossing: str = "",
    kpk_attribute: str = "",
    replica_relation: str = "",
    replica_column: str = "",
    profile_relation: str = "",
    profile_column: str = "",
    gap: str = "",
) -> dict[str, str]:
    return {
        "ucp_endpoint_key": endpoint,
        "kpk_service": KPK_SERVICE,
        "cpc_crossing_attribute": crossing,
        "kpk_attribute": kpk_attribute,
        "kpk_interaction_provenance_json": _interaction_provenance(),
        "tsa_replica_relation": replica_relation,
        "tsa_replica_column": replica_column,
        "profile_fl_relation": profile_relation,
        "profile_fl_column": profile_column,
        "gap": gap,
    }


def test_first_name_joins_independent_kpk_and_profile_branches_by_common_ucp_origin():
    endpoint = "com.sbt.bm.ucp.retail.model.individual.IndividualName.name"
    kpk_attribute = "bankAcctRecs[].cardAcctId.custInfo.personInfo.personName.firstName"
    raw = [
        _row(
            endpoint=endpoint,
            crossing="clientInfo.names.name",
            kpk_attribute=kpk_attribute,
        ),
        *[
            _row(
                endpoint=endpoint,
                replica_relation="individualname",
                replica_column="name",
                profile_relation="custom_b2c_profile_fl.epk_client",
                profile_column=column,
            )
            for column in ("first_name", "first_name_hash", "united_person_hash")
        ],
    ]

    rows = consumer_rows(raw)

    assert len(rows) == 3
    assert {row["profile_fl_column"] for row in rows} == {
        "first_name",
        "first_name_hash",
        "united_person_hash",
    }
    assert {row["ucp_attribute"] for row in rows} == {"name"}
    assert {row["ucp_service"] for row in rows} == {UCP_SERVICE}
    assert {row["kpk_crossing_attribute"] for row in rows} == {"clientInfo.names.name"}
    assert {row["kpk_attribute"] for row in rows} == {kpk_attribute}
    assert {row["kpk_branch_status"] for row in rows} == {"proven"}
    assert {row["profile_fl_branch_status"] for row in rows} == {"proven"}


def test_surname_full_name_partial_diagnostic_does_not_duplicate_proven_kpk_branch():
    endpoint = "com.sbt.bm.ucp.retail.model.individual.IndividualName.surname"
    kpk_attribute = "bankAcctRecs[].cardAcctId.custInfo.personInfo.personName.lastName"
    columns = ("last_name", "last_name_hash", "united_person_hash")
    raw: list[dict[str, str]] = []
    for column in columns:
        raw.append(
            _row(
                endpoint=endpoint,
                crossing="clientInfo.names.fullName",
                replica_relation="individualname",
                replica_column="surname",
                profile_relation="custom_b2c_profile_fl.epk_client",
                profile_column=column,
            )
        )
        raw.append(
            _row(
                endpoint=endpoint,
                crossing="clientInfo.names.surname",
                kpk_attribute=kpk_attribute,
                replica_relation="individualname",
                replica_column="surname",
                profile_relation="custom_b2c_profile_fl.epk_client",
                profile_column=column,
            )
        )

    rows = consumer_rows(raw)

    assert len(rows) == 3
    assert {row["profile_fl_column"] for row in rows} == set(columns)
    assert {row["kpk_crossing_attribute"] for row in rows} == {"clientInfo.names.surname"}
    assert {row["kpk_attribute"] for row in rows} == {kpk_attribute}
    assert all("fullName" not in row["kpk_crossing_attribute"] for row in rows)


def test_consumer_rows_keep_only_rows_with_at_least_one_proven_downstream_branch():
    kpk_only = _row(
        endpoint="example.ucp.KpkOnly.value",
        crossing="clientInfo.kpkOnly",
        kpk_attribute="bankAcctRecs[].kpkOnly",
    )
    profile_only = _row(
        endpoint="example.ucp.ProfileOnly.value",
        replica_relation="profile_only_replica",
        replica_column="value",
        profile_relation="custom_b2c_profile_fl.epk_client",
        profile_column="profile_only",
    )
    neither = _row(endpoint="example.ucp.Neither.value", crossing="clientInfo.partial")

    rows = consumer_rows([kpk_only, profile_only, neither])

    assert len(rows) == 2
    assert {row["ucp_type"] for row in rows} == {"example.ucp.KpkOnly", "example.ucp.ProfileOnly"}
    assert all(
        row["kpk_branch_status"] == "proven" or row["profile_fl_branch_status"] == "proven"
        for row in rows
    )


def test_ucp_id_preserves_observed_kpk_crossing_when_profile_branch_is_proven():
    endpoint = "com.sbt.bm.ucp.retail.model.individual.Individual.id"
    raw = [
        _row(
            endpoint=endpoint,
            crossing="clientInfo.ucpID",
            replica_relation="com_sbt_bm_ucp_retail_model_individual_individual",
            replica_column="id",
            profile_relation="custom_b2c_profile_fl.epkid_2_epkid",
            profile_column="merge_epk_id",
            gap="kpk_consumer_attribute_not_observed",
        )
    ]

    rows = consumer_rows(raw)

    assert len(rows) == 1
    assert rows[0]["ucp_attribute"] == "id"
    assert rows[0]["ucp_service"] == UCP_SERVICE
    assert rows[0]["kpk_service"] == KPK_SERVICE
    assert rows[0]["kpk_crossing_attribute"] == "clientInfo.ucpID"
    assert rows[0]["kpk_attribute"] == ""
    assert rows[0]["tsa_replica_relation"] == "com_sbt_bm_ucp_retail_model_individual_individual"
    assert rows[0]["tsa_replica_column"] == "id"
    assert rows[0]["profile_fl_relation"] == "custom_b2c_profile_fl.epkid_2_epkid"
    assert rows[0]["profile_fl_column"] == "merge_epk_id"
    assert rows[0]["kpk_branch_status"] == "crossing_observed_egress_not_proven"
    assert rows[0]["profile_fl_branch_status"] == "proven"


def test_partial_kpk_crossing_without_any_proven_branch_stays_out_of_consumer_view():
    rows = consumer_rows([
        _row(
            endpoint="example.ucp.ObservedOnly.value",
            crossing="clientInfo.observedOnly",
            gap="kpk_consumer_attribute_not_observed",
        )
    ])

    assert rows == []
