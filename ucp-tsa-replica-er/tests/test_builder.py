from __future__ import annotations

from aisl_ucp_tsa_replica_er.builder import build_replica_model, mermaid_flowchart
from aisl_ucp_tsa_replica_er.contracts import RevisionBinding


def _ann(type_id: str, name: str, **args: str) -> dict:
    return {
        "annotation_occurrence_id": f"ann-{type_id}-{name}",
        "target_kind": "type",
        "target_occurrence_id": type_id,
        "annotation_name": name,
        "structured_arguments_json": [
            {
                "name": key,
                "raw": f'"{value}"',
                "expression_tree": {"literal_value": value},
            }
            for key, value in args.items()
        ],
        "source_ref_json": {"path": f"{type_id}.java"},
    }


def _entity(fqcn: str, table: str, mapping_id: str) -> dict:
    return {
        "item_kind": "entity_mapping",
        "local_id": mapping_id,
        "payload": {
            "mapping_id": mapping_id,
            "mapping_status": "observed_exact",
            "logical_type_name": fqcn,
            "physical_table_name": table,
            "source_refs": [{"path": "tsa.java"}],
        },
    }


def _field(fqcn: str, name: str, column: str, entity_mapping_id: str, mapping_id: str) -> dict:
    return {
        "item_kind": "field_mapping",
        "local_id": mapping_id,
        "payload": {
            "mapping_id": mapping_id,
            "mapping_status": "observed_exact",
            "entity_mapping_id": entity_mapping_id,
            "logical_type_name": fqcn,
            "logical_field_name": name,
            "physical_column_name": column,
            "source_refs": [{"path": "tsa.java"}],
        },
    }


def _fixture() -> tuple[dict, dict]:
    individual = "com.example.Individual"
    birthdate = "com.example.BirthDate"
    dataset = {
        "types": [
            {"type_occurrence_id": "t-ind", "fully_qualified_name": individual, "simple_name": "Individual", "source_ref_json": {}},
            {"type_occurrence_id": "t-bd", "fully_qualified_name": birthdate, "simple_name": "BirthDate", "source_ref_json": {}},
        ],
        "fields": [
            {"field_occurrence_id": "f-ind-id", "owner_type_occurrence_id": "t-ind", "name": "id", "declared_type_expression": "String"},
            {"field_occurrence_id": "f-ind-v", "owner_type_occurrence_id": "t-ind", "name": "version", "declared_type_expression": "Long"},
            {"field_occurrence_id": "f-ind-bd", "owner_type_occurrence_id": "t-ind", "name": "birthDate", "declared_type_expression": "BirthDate"},
            {"field_occurrence_id": "f-bd-id", "owner_type_occurrence_id": "t-bd", "name": "id", "declared_type_expression": "String"},
            {"field_occurrence_id": "f-bd-v", "owner_type_occurrence_id": "t-bd", "name": "version", "declared_type_expression": "Long"},
        ],
        "effective_fields": [
            {"effective_field_occurrence_id": "ef1", "effective_owner_type_occurrence_id": "t-ind", "field_name": "id"},
            {"effective_field_occurrence_id": "ef2", "effective_owner_type_occurrence_id": "t-ind", "field_name": "version"},
            {"effective_field_occurrence_id": "ef3", "effective_owner_type_occurrence_id": "t-ind", "field_name": "birthDate"},
            {"effective_field_occurrence_id": "ef4", "effective_owner_type_occurrence_id": "t-bd", "field_name": "id"},
            {"effective_field_occurrence_id": "ef5", "effective_owner_type_occurrence_id": "t-bd", "field_name": "version"},
        ],
        "relationships": [
            {
                "relationship_occurrence_id": "rel1",
                "source_type_occurrence_id": "t-ind",
                "target_type_occurrence_id": "t-bd",
                "field_occurrence_id": "f-ind-bd",
                "relationship_kind": "declared_field_type_reference",
                "resolution_status": "same_package",
                "provenance_json": {"basis": "resolved_effective_field_type_reference"},
            }
        ],
        "annotations": [
            _ann("t-ind", "MetaRootEntity", id="id", version="version", collocationId="id"),
            _ann("t-bd", "MetaVersionedEntity", id="id", version="version"),
        ],
    }
    mappings = {
        "entity_mappings": [
            _entity(individual, "replica_individual", "em-ind"),
            _entity(birthdate, "replica_birthdate", "em-bd"),
        ],
        "field_mappings": [
            _field(individual, "id", "id", "em-ind", "fm-ind-id"),
            _field(individual, "version", "version", "em-ind", "fm-ind-v"),
            _field(birthdate, "id", "id", "em-bd", "fm-bd-id"),
            _field(birthdate, "version", "version", "em-bd", "fm-bd-v"),
        ],
    }
    return dataset, mappings


def test_projects_declared_identity_and_relationship_without_inventing_fk() -> None:
    dataset, mappings = _fixture()
    result = build_replica_model(
        ucp=RevisionBinding("ucp", "rev-u"),
        tsa=RevisionBinding("tsa", "rev-t"),
        ucp_dataset=dataset,
        tsa_mappings=mappings,
        root_objects=("Individual",),
    )

    assert result["counts"] == {
        "selected_ucp_types": 2,
        "replica_tables": 2,
        "relationships": 1,
        "tables_with_confirmed_declared_key_mapping": 2,
        "table_key_gaps": 0,
        "relationships_with_physical_join_gap": 1,
        "mapping_gaps": 0,
    }
    tables = {row["logical_type_name"]: row for row in result["tables"]}
    assert tables["Individual"]["replica_relation"] == "replica_individual"
    assert tables["Individual"]["key_replica_columns"] == ["id"]
    assert tables["Individual"]["version_replica_column"] == "version"
    assert tables["Individual"]["collocation_replica_column"] == "id"
    assert tables["Individual"]["key_status"] == "confirmed_declared_identity_mapped"
    assert tables["Individual"]["physical_constraint_status"] == "not_observed"

    rel = result["relationships"][0]
    assert rel["source_replica_relation"] == "replica_individual"
    assert rel["target_replica_relation"] == "replica_birthdate"
    assert rel["source_key_columns"] == ["id"]
    assert rel["target_key_columns"] == ["id"]
    assert rel["relationship_field"] == "birthDate"
    assert rel["status"] == "confirmed_ucp_relationship_projected_to_replicas"
    assert rel["physical_join_status"] == "not_observed"
    assert rel["physical_join_condition"] == ""
    assert rel["gap"] == "physical_fk_join_not_observed"

    mermaid = mermaid_flowchart(result)
    assert "replica_individual" in mermaid
    assert "replica_birthdate" in mermaid
    assert 'birthDate' in mermaid
    assert "physical FK join is not asserted" in mermaid


def test_dictionary_code_is_declared_identity() -> None:
    fqcn = "com.example.Country"
    dataset = {
        "types": [{"type_occurrence_id": "t", "fully_qualified_name": fqcn, "simple_name": "Country"}],
        "fields": [{"field_occurrence_id": "f", "owner_type_occurrence_id": "t", "name": "code", "declared_type_expression": "String"}],
        "effective_fields": [{"effective_field_occurrence_id": "ef", "effective_owner_type_occurrence_id": "t", "field_name": "code"}],
        "relationships": [],
        "annotations": [_ann("t", "MetaDictionary", code="code")],
    }
    mappings = {
        "entity_mappings": [_entity(fqcn, "replica_country", "em")],
        "field_mappings": [_field(fqcn, "code", "code", "em", "fm")],
    }
    result = build_replica_model(
        ucp=RevisionBinding("ucp", "r1"), tsa=RevisionBinding("tsa", "r2"),
        ucp_dataset=dataset, tsa_mappings=mappings,
    )
    table = result["tables"][0]
    assert table["key_kind"] == "dictionary_code"
    assert table["key_replica_columns"] == ["code"]
    assert table["key_status"] == "confirmed_declared_identity_mapped"


def test_missing_identity_field_mapping_is_explicit_gap() -> None:
    dataset, mappings = _fixture()
    mappings["field_mappings"] = [
        row for row in mappings["field_mappings"]
        if not (row["payload"]["logical_type_name"] == "com.example.BirthDate" and row["payload"]["logical_field_name"] == "id")
    ]
    result = build_replica_model(
        ucp=RevisionBinding("ucp", "r1"), tsa=RevisionBinding("tsa", "r2"),
        ucp_dataset=dataset, tsa_mappings=mappings,
    )
    table = next(row for row in result["tables"] if row["logical_type_name"] == "BirthDate")
    assert table["key_status"] == "gap"
    assert table["key_gap"] == "tsa_identity_field_mapping_not_found"
    rel = result["relationships"][0]
    assert rel["target_key_status"] == "gap"


def test_ambiguous_entity_mapping_fails_closed() -> None:
    dataset, mappings = _fixture()
    mappings["entity_mappings"].append(_entity("com.example.BirthDate", "replica_birthdate_second", "em-bd-2"))
    result = build_replica_model(
        ucp=RevisionBinding("ucp", "r1"), tsa=RevisionBinding("tsa", "r2"),
        ucp_dataset=dataset, tsa_mappings=mappings,
    )
    assert not any(row["logical_type_name"] == "BirthDate" for row in result["tables"])
    assert result["relationships"] == []
    assert {gap["kind"] for gap in result["gaps"]} == {"tsa_entity_mapping_ambiguous"}


def test_root_selection_is_outgoing_closure_and_rejects_ambiguous_simple_name() -> None:
    dataset, mappings = _fixture()
    result = build_replica_model(
        ucp=RevisionBinding("ucp", "r1"), tsa=RevisionBinding("tsa", "r2"),
        ucp_dataset=dataset, tsa_mappings=mappings, root_objects=("Individual",),
    )
    assert {row["logical_type_name"] for row in result["tables"]} == {"Individual", "BirthDate"}

    dataset["types"].append({"type_occurrence_id": "t-other", "fully_qualified_name": "other.Individual", "simple_name": "Individual"})
    try:
        build_replica_model(
            ucp=RevisionBinding("ucp", "r1"), tsa=RevisionBinding("tsa", "r2"),
            ucp_dataset=dataset, tsa_mappings=mappings, root_objects=("Individual",),
        )
    except ValueError as exc:
        assert "resolve exactly once" in str(exc)
    else:
        raise AssertionError("expected ambiguous simple-name failure")
