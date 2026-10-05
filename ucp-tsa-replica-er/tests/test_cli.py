from __future__ import annotations

import json
from pathlib import Path

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
        "relationships": [],
    })
    monkeypatch.setattr(cli, "mermaid_flowchart", lambda payload: "flowchart LR\n")

    out_json = tmp_path / "model.json"
    tables = tmp_path / "tables.csv"
    rels = tmp_path / "relationships.csv"
    mermaid = tmp_path / "model.mmd"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--ucp-system", "ucp", "--ucp-revision", "rev-u",
        "--tsa-system", "tsa", "--tsa-revision", "rev-t",
        "--output-json", str(out_json), "--tables-csv", str(tables),
        "--relationships-csv", str(rels), "--output-mermaid", str(mermaid),
    ])
    assert rc == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["schema_version"] == "ucp-tsa-replica-er/v1"
    assert "replica_x" in tables.read_text(encoding="utf-8")
    assert rels.read_text(encoding="utf-8").startswith("source_type_fqcn,")
    assert mermaid.read_text(encoding="utf-8") == "flowchart LR\n"
