from __future__ import annotations

import csv
import json
from pathlib import Path

from aisl_kpk_profile_fl_lineage import cli


def test_cli_calls_task46_builder_once_per_exact_endpoint(monkeypatch, tmp_path: Path):
    evidence = tmp_path / "left.csv"
    with evidence.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "kpk_attribute", "classification", "left_status", "ucp_semantic_path", "endpoint_key",
            "ucp_resolution_provenance_json",
        ])
        writer.writeheader()
        writer.writerow({
            "kpk_attribute": "clientInfo.birthDate",
            "classification": "FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
            "left_status": "exact_field",
            "ucp_semantic_path": "Individual.birthDate → BirthDate.value",
            "endpoint_key": "com.sbt.bm.ucp.retail.model.individual.BirthDate.value",
            "ucp_resolution_provenance_json": "[]",
        })

    class Gateway:
        def __init__(self, base_url):
            assert base_url == "http://aisl"
        def close(self):
            pass

    calls = []
    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    def fake_build_lineage(**kwargs):
        calls.append((kwargs["source_object"], kwargs["source_field"]))
        return [{
            "status": "confirmed",
            "source_type_fqcn": kwargs["source_object"],
            "source_field": kwargs["source_field"],
            "source_attribute_path": "Individual.birthDate → BirthDate.value",
            "source_revision_id": "rev-u",
            "replica_relation": "birthdate_replica",
            "replica_column": "value",
            "target_relation": "epk_client",
            "target_column": "birth_dt",
        }]
    monkeypatch.setattr(cli, "build_lineage", fake_build_lineage)

    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--kpk-ucp-evidence", str(evidence),
        "--source-system", "ucp", "--source-revision", "rev-u",
        "--bridge-system", "tsa", "--bridge-revision", "rev-t",
        "--target-system", "profile", "--target-revision", "rev-p",
        "--output-json", str(out_json), "--output-csv", str(out_csv),
    ])
    assert rc == 0
    assert calls == [("com.sbt.bm.ucp.retail.model.individual.BirthDate", "value")]
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "kpk-profile-fl-lineage/v1"
    assert payload["rows"][0]["profile_fl_column"] == "birth_dt"
    assert out_csv.exists()
