from __future__ import annotations

import csv
from pathlib import Path

from aisl_ucp_tsa_replica_er.builder import build_replica_model
from aisl_ucp_tsa_replica_er.contracts import RevisionBinding
from aisl_ucp_tsa_replica_er.output import REPLICA_FIELD_COLUMNS, write_replica_fields_csv
from test_builder import _fixture, _field


def _build(dataset: dict, mappings: dict):
    return build_replica_model(
        ucp=RevisionBinding("ucp", "rev-u"),
        tsa=RevisionBinding("tsa", "rev-t"),
        ucp_dataset=dataset,
        tsa_mappings=mappings,
        root_objects=("Individual",),
    )


def test_field_csv_preserves_ucp_documentation_and_explicit_gaps(tmp_path: Path):
    ucp, tsa = _fixture()
    ucp["types"][0]["documentation"] = {"description": "Частное лицо"}
    ucp["fields"][0]["documentation"] = {"description": "Идентификатор человека"}
    ucp["fields"][1]["documentation"] = {"description": "Версия записи"}
    tsa["field_mappings"].append(_field("com.example.Individual", "birthDate", "birth_date", "em-ind", "fm-birth"))
    tsa["field_mappings"].append(_field("com.example.Individual", "extra", "extra", "em-ind", "fm-extra"))
    result = _build(ucp, tsa)
    rows = result["replica_fields"]
    assert [(r["replica_relation"], r["replica_column"]) for r in rows] == sorted(
        (r["replica_relation"], r["replica_column"]) for r in rows
    )
    by_column = {(r["replica_relation"], r["replica_column"]): r for r in rows}
    id_row = by_column["replica_individual", "id"]
    assert id_row["ucp_field"] == "id"
    assert id_row["ucp_field_type"] == "String"
    assert id_row["ucp_type_description"] == "Частное лицо"
    assert id_row["ucp_field_description"] == "Идентификатор человека"
    assert id_row["description_status"] == "confirmed"
    assert id_row["gap"] == ""
    assert id_row["provenance"]["tsa_field_mapping"]
    assert by_column["replica_individual", "birth_date"]["gap"] == "ucp_description_not_published"
    assert by_column["replica_individual", "extra"]["gap"] == "ucp_field_not_found"
    assert by_column["replica_individual", "extra"]["ucp_field_description"] == ""
    csv_path = tmp_path / "replica-fields.csv"
    write_replica_fields_csv(rows, csv_path)
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert tuple(reader.fieldnames or ()) == REPLICA_FIELD_COLUMNS
        as_csv = list(reader)
    assert len(as_csv) == len(rows)
    assert any(r["ucp_field_description"] == "Идентификатор человека" for r in as_csv)


def test_inherited_field_documentation_from_exact_effective_occurrence():
    ucp, tsa = _fixture()
    ucp["fields"].append({
        "field_occurrence_id": "base-field", "owner_type_occurrence_id": "t-base",
        "name": "origin", "declared_type_expression": "String",
        "documentation": {"description": "Унаследованный источник"},
    })
    ucp["effective_fields"].append({
        "effective_field_occurrence_id": "ef-inherited",
        "effective_owner_type_occurrence_id": "t-ind",
        "field_occurrence_id": "base-field", "field_name": "origin",
        "declaring_type_occurrence_id": "t-base", "inherited_depth": 1,
    })
    tsa["field_mappings"].append(_field("com.example.Individual", "origin", "origin", "em-ind", "fm-origin"))
    rows = _build(ucp, tsa)["replica_fields"]
    origin = next(r for r in rows if r["replica_relation"] == "replica_individual" and r["replica_column"] == "origin")
    assert origin["ucp_field_description"] == "Унаследованный источник"
    assert origin["description_status"] == "confirmed"


def test_ambiguous_column_not_reported_as_single_confirmed_source():
    ucp, tsa = _fixture()
    ucp["fields"][0]["documentation"] = {"description": "Идентификатор"}
    tsa["field_mappings"].append(_field("com.example.Individual", "version", "id", "em-ind", "fm-ambiguous"))
    tsa["field_mappings"].append(_field("com.example.Individual", "id", "id", "em-ind", "fm-dupe"))
    rows = [r for r in _build(ucp, tsa)["replica_fields"] if r["replica_relation"] == "replica_individual" and r["replica_column"] == "id"]
    assert len(rows) == 2
    assert {r["ucp_field"] for r in rows} == {"id", "version"}
    assert all(r["mapping_status"] == "ambiguous_multiple_ucp_fields" for r in rows)
    assert all(r["gap"] == "tsa_column_mapping_ambiguous" for r in rows)
