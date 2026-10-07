from __future__ import annotations

from aisl_kpk_profile_fl_lineage.bridge import bind_kpk_consumers, compose_one
from aisl_kpk_profile_fl_lineage.contracts import CrossingUcpEvidence, KpkUcpEvidence


def _crossing(path: str, endpoint: str, crossing: str = "clientInfo.birthDate") -> CrossingUcpEvidence:
    return CrossingUcpEvidence(
        crossing_attribute=crossing,
        classification="FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
        ucp_semantic_path=path,
        endpoint_key=endpoint,
    )


def _bound(*, kpk_attribute: str = "bankAcctRecs[].cardAcctId.custInfo.personInfo.birthday", crossing: str = "clientInfo.birthDate") -> KpkUcpEvidence:
    return KpkUcpEvidence(
        kpk_service="cpc_efs_gateway_get_cards_by_client_id",
        kpk_interaction="HTTP POST /cpcGet",
        kpk_attribute=kpk_attribute,
        kpk_output_root="bankAcctRecs",
        crossing_attribute=crossing,
        interaction_consumer_attribute=kpk_attribute,
        classification="FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
        ucp_semantic_path="Individual.birthDate → BirthDate.value",
        endpoint_key="com.sbt.bm.ucp.retail.model.individual.BirthDate.value",
    )


def test_task43_crossing_binds_to_final_kpk_consumer_attribute():
    evidence = _crossing(
        "IndividualName.surname",
        "com.sbt.bm.ucp.retail.model.individual.IndividualName.surname",
        "clientInfo.names.surname",
    )
    rows = bind_kpk_consumers([evidence], [{
        "interaction": "HTTP POST /cpcGet",
        "role": "response",
        "consumer_repository": "cpc_efs_gateway_get_cards_by_client_id",
        "crossing_attribute": "clientInfo.names.surname",
        "consumer_attribute": "bankAcctRecs[].cardAcctId.custInfo.personInfo.personName.lastName",
        "gap": "",
        "full_attribute_path": "source → clientInfo.names.surname → ... → personName.lastName",
    }], consumer_repository="cpc_efs_gateway_get_cards_by_client_id", output_root="bankAcctRecs")

    assert len(rows) == 1
    assert rows[0].crossing_attribute == "clientInfo.names.surname"
    assert rows[0].kpk_attribute == "bankAcctRecs[].cardAcctId.custInfo.personInfo.personName.lastName"
    assert rows[0].kpk_gap == ""


def test_missing_final_kpk_egress_is_explicit_gap():
    evidence = _crossing(
        "Individual.id",
        "com.sbt.bm.ucp.retail.model.individual.Individual.id",
        "clientInfo.ucpID",
    )
    rows = bind_kpk_consumers([evidence], [{
        "interaction": "HTTP POST /cpcGet",
        "role": "response",
        "consumer_repository": "cpc_efs_gateway_get_cards_by_client_id",
        "crossing_attribute": "clientInfo.ucpID",
        "consumer_attribute": "",
        "gap": "source external link unproven",
        "full_attribute_path": "... clientInfo.ucpID",
    }], consumer_repository="cpc_efs_gateway_get_cards_by_client_id", output_root="bankAcctRecs")

    assert rows[0].kpk_attribute == ""
    assert rows[0].kpk_gap == "kpk_consumer_attribute_not_observed"


def test_full_name_cannot_be_promoted_to_last_name_without_kpk_egress():
    evidence = KpkUcpEvidence(
        kpk_service="cpc_efs_gateway_get_cards_by_client_id",
        kpk_interaction="HTTP POST /cpcGet",
        kpk_attribute="",
        kpk_output_root="bankAcctRecs",
        crossing_attribute="clientInfo.names.fullName",
        interaction_consumer_attribute="",
        classification="DOWNSTREAM_DERIVATION",
        ucp_semantic_path="IndividualName.surname",
        endpoint_key="com.sbt.bm.ucp.retail.model.individual.IndividualName.surname",
        kpk_gap="kpk_consumer_attribute_not_observed",
    )
    rows = compose_one(evidence, [{
        "status": "confirmed",
        "source_type_fqcn": "com.sbt.bm.ucp.retail.model.individual.IndividualName",
        "source_field": "surname",
        "source_attribute_path": "IndividualName.surname",
        "source_revision_id": "rev-u",
        "replica_relation": "replica_name",
        "replica_column": "surname",
        "target_relation": "epk_client",
        "target_column": "last_name",
    }])

    assert len(rows) == 1
    assert rows[0]["join_status"] == "unresolved_kpk_egress"
    assert rows[0]["kpk_attribute"] == ""
    assert rows[0]["cpc_crossing_attribute"] == "clientInfo.names.fullName"
    assert rows[0]["profile_fl_column"] == "last_name"
    assert rows[0]["gap"] == "kpk_consumer_attribute_not_observed"


def test_exact_full_ucp_semantic_path_and_kpk_egress_is_confirmed():
    evidence = _bound()
    rows = compose_one(evidence, [{
        "status": "confirmed",
        "source_type_fqcn": "com.sbt.bm.ucp.retail.model.individual.BirthDate",
        "source_field": "value",
        "source_attribute_path": "Individual.birthDate → BirthDate.value",
        "source_revision_id": "rev-u",
        "replica_relation": "replica_birthdate",
        "replica_column": "value",
        "target_relation": "epk_client",
        "target_column": "birth_dt",
    }])
    assert len(rows) == 1
    assert rows[0]["join_status"] == "confirmed_exact_ucp_semantic_path_and_kpk_egress"
    assert rows[0]["profile_fl_column"] == "birth_dt"
    assert rows[0]["kpk_attribute"].endswith("personInfo.birthday")
    assert "clientInfo.birthDate" in rows[0]["full_attribute_path"]


def test_same_leaf_with_collapsed_context_fails_closed():
    evidence = KpkUcpEvidence(
        kpk_service="cpc",
        kpk_interaction="HTTP POST /cpcGet",
        kpk_attribute="bankAcctRecs[].nameType",
        kpk_output_root="bankAcctRecs",
        crossing_attribute="clientInfo.names.nameType.code",
        interaction_consumer_attribute="bankAcctRecs[].nameType",
        classification="FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
        ucp_semantic_path="IndividualName.nameType → NameType.code",
        endpoint_key="com.sbt.bm.ucp.common.model.dictionary.NameType.code",
    )
    rows = compose_one(evidence, [{
        "status": "confirmed",
        "source_type_fqcn": "com.sbt.bm.ucp.common.model.dictionary.NameType",
        "source_field": "code",
        "source_attribute_path": "NameType.code",
        "source_revision_id": "rev-u",
        "target_relation": "epk_client",
        "target_column": "name_type_cd",
    }])
    assert len(rows) == 1
    assert rows[0]["join_status"] == "context_ambiguous"
    assert "right_context_not_exact" in rows[0]["gap"]


def test_task43_internal_consumer_outside_selected_service_output_root_is_gap():
    evidence = _crossing(
        "IndividualIdentification.documentType → PartyIdentificationType.code",
        "com.sbt.bm.ucp.common.model.dictionary.PartyIdentificationType.code",
        "clientInfo.identifications.documentType",
    )
    rows = bind_kpk_consumers([evidence], [{
        "interaction": "HTTP POST /cpcGet",
        "role": "response",
        "consumer_repository": "cpc_efs_gateway_get_cards_by_client_id",
        "crossing_attribute": "clientInfo.identifications.documentType",
        "consumer_attribute": "identifications.documentType",
        "gap": "",
        "full_attribute_path": "clientInfo.identifications.documentType → identifications.documentType",
    }], consumer_repository="cpc_efs_gateway_get_cards_by_client_id", output_root="bankAcctRecs")

    assert rows[0].kpk_attribute == ""
    assert rows[0].interaction_consumer_attribute == "identifications.documentType"
    assert rows[0].kpk_gap == "kpk_consumer_attribute_outside_selected_output_root"


def test_endpoint_key_requires_owner_and_field():
    evidence = CrossingUcpEvidence("x", "confirmed", "X", "bad")
    try:
        _ = evidence.source_type_fqcn
    except ValueError as exc:
        assert "endpoint_key" in str(exc)
    else:
        raise AssertionError("expected ValueError")
