from __future__ import annotations

from aisl_kpk_profile_fl_lineage.bridge import compose_one
from aisl_kpk_profile_fl_lineage.contracts import KpkUcpEvidence


def _evidence(path: str, endpoint: str) -> KpkUcpEvidence:
    return KpkUcpEvidence(
        kpk_attribute="clientInfo.birthDate",
        classification="FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
        ucp_semantic_path=path,
        endpoint_key=endpoint,
    )


def test_exact_full_ucp_semantic_path_is_confirmed():
    evidence = _evidence(
        "Individual.birthDate → BirthDate.value",
        "com.sbt.bm.ucp.retail.model.individual.BirthDate.value",
    )
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
    assert rows[0]["join_status"] == "confirmed_exact_ucp_semantic_path"
    assert rows[0]["profile_fl_column"] == "birth_dt"


def test_same_leaf_with_collapsed_context_fails_closed():
    evidence = KpkUcpEvidence(
        kpk_attribute="clientInfo.names.nameType.code",
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


def test_endpoint_key_requires_owner_and_field():
    evidence = KpkUcpEvidence("x", "confirmed", "X", "bad")
    try:
        _ = evidence.source_type_fqcn
    except ValueError as exc:
        assert "endpoint_key" in str(exc)
    else:
        raise AssertionError("expected ValueError")
