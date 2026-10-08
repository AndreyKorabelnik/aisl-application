from __future__ import annotations

import json
from pathlib import Path

import pytest

from aisl_ucp_tsa_replica_er import cli


class Gateway:
    def __init__(self, base_url: str):
        assert base_url == "http://aisl"

    def close(self):
        pass

    def load_ucp_dataset(self, binding):
        return {"types": [], "fields": [], "effective_fields": [], "relationships": [], "annotations": []}

    def load_tsa_mappings(self, binding):
        return {"entity_mappings": [], "field_mappings": []}


def test_cli_writes_all_outputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "build_replica_model", lambda **kwargs: {
        "schema_version": "ucp-tsa-replica-er/v1",
        "tables": [{
            "logical_type_fqcn": "X", "logical_type_name": "X", "replica_relation": "replica_x",
            "key_kind": "entity_id", "key_annotation": "MetaEntity",
            "key_logical_fields": ["id"], "key_replica_columns": ["id"],
            "key_status": "confirmed_declared_identity_mapped", "key_gap": "",
            "version_logical_field": "", "version_replica_column": "",
            "collocation_logical_field": "", "collocation_replica_column": "",
            "physical_constraint_status": "not_observed",
            "physical_constraint_gap": "database_primary_key_constraint_not_published",
            "provenance": {},
        }],
        "relationships": [{
            "source_replica_relation": "replica_x",
            "source_key_columns": ["id"],
            "relationship_field": "country",
            "target_replica_relation": "replica_country",
            "target_key_columns": ["code"],
            "status": "confirmed_ucp_relationship_projected_to_replicas",
            "physical_join_status": "not_observed",
        }],
    })
    monkeypatch.setattr(cli, "mermaid_flowchart", lambda payload: "flowchart LR\n")

    out_json = tmp_path / "model.json"
    tables = tmp_path / "tables.csv"
    rels = tmp_path / "relationships.csv"
    keys = tmp_path / "keys.csv"
    links = tmp_path / "links.csv"
    mermaid = tmp_path / "model.mmd"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--ucp-system", "ucp", "--ucp-revision", "rev-u",
        "--tsa-system", "tsa", "--tsa-revision", "rev-t",
        "--output-json", str(out_json), "--tables-csv", str(tables),
        "--relationships-csv", str(rels), "--keys-csv", str(keys),
        "--links-csv", str(links), "--output-mermaid", str(mermaid),
    ])
    assert rc == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["schema_version"] == "ucp-tsa-replica-er/v1"
    assert "replica_x" in tables.read_text(encoding="utf-8")
    assert rels.read_text(encoding="utf-8").startswith("source_type_fqcn,")
    assert keys.read_text(encoding="utf-8").splitlines() == [
        "table,logical_pk,key_kind,logical_pk_status,physical_pk_status,gap",
        "replica_x,id,entity_id,confirmed,not_observed,",
    ]
    assert links.read_text(encoding="utf-8").splitlines() == [
        "source_table,relationship,target_table,target_logical_pk,logical_link_status,physical_fk_status",
        "replica_x,country,replica_country,code,confirmed,not_observed",
    ]
    assert mermaid.read_text(encoding="utf-8") == "flowchart LR\n"


def test_cli_can_write_only_links_csv(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "build_replica_model", lambda **kwargs: {
        "tables": [{"replica_relation": "replica_x"}],
        "relationships": [{
            "source_replica_relation": "replica_x",
            "source_key_columns": ["id"],
            "relationship_field": "birthDate",
            "target_replica_relation": "replica_birthdate",
            "target_key_columns": ["id"],
            "status": "confirmed_ucp_relationship_projected_to_replicas",
            "physical_join_status": "not_observed",
        }],
    })

    links = tmp_path / "nested" / "links.csv"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--ucp-system", "ucp", "--ucp-revision", "rev-u",
        "--tsa-system", "tsa", "--tsa-revision", "rev-t",
        "--links-csv", str(links),
    ])
    assert rc == 0
    assert links.read_text(encoding="utf-8").splitlines()[1] == (
        "replica_x,birthDate,replica_birthdate,id,confirmed,not_observed"
    )
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == ["links.csv"]


def test_cli_can_write_only_keys_csv(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "build_replica_model", lambda **kwargs: {
        "tables": [{
            "replica_relation": "replica_country",
            "key_replica_columns": ["code"],
            "key_kind": "dictionary_code",
            "key_status": "confirmed_declared_identity_mapped",
            "key_gap": "",
            "physical_constraint_status": "not_observed",
        }],
        "relationships": [],
    })

    keys = tmp_path / "nested" / "keys.csv"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--ucp-system", "ucp", "--ucp-revision", "rev-u",
        "--tsa-system", "tsa", "--tsa-revision", "rev-t",
        "--keys-csv", str(keys),
    ])
    assert rc == 0
    assert keys.read_text(encoding="utf-8").splitlines()[1] == (
        "replica_country,code,dictionary_code,confirmed,not_observed,"
    )
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == ["keys.csv"]


def test_cli_requires_at_least_one_output(monkeypatch) -> None:
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "build", "--aisl-base-url", "http://aisl",
            "--ucp-system", "ucp", "--ucp-revision", "rev-u",
            "--tsa-system", "tsa", "--tsa-revision", "rev-t",
        ])
    assert exc.value.code == 2


def test_cli_can_write_only_replica_fields_csv(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "build_replica_model", lambda **kwargs: {
        "tables": [{"replica_relation": "replica_individual"}],
        "relationships": [],
        "replica_fields": [{
            "replica_relation": "replica_individual",
            "replica_column": "birth_date",
            "ucp_type_fqcn": "com.example.Individual",
            "ucp_type_description": "Частное лицо",
            "ucp_field": "birthDate",
            "ucp_field_type": "BirthDate",
            "ucp_field_description": "Дата рождения",
            "description_status": "confirmed",
            "mapping_status": "observed_exact",
            "gap": "",
            "provenance": {"mapping": "exact"},
        }],
    })
    out = tmp_path / "nested" / "replica-fields.csv"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--ucp-system", "ucp", "--ucp-revision", "rev-u",
        "--tsa-system", "tsa", "--tsa-revision", "rev-t",
        "--replica-fields-csv", str(out),
    ])
    assert rc == 0
    import csv
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["ucp_field_description"] == "Дата рождения"
    assert rows[0]["provenance_json"] == '{"mapping":"exact"}'
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["replica-fields.csv"]
