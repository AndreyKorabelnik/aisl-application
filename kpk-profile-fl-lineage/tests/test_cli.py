from __future__ import annotations

import csv
import json
from pathlib import Path

from aisl_kpk_profile_fl_lineage import cli


def test_cli_uses_task43_final_consumer_and_keeps_missing_egress_unresolved(monkeypatch, tmp_path: Path):
    evidence = tmp_path / "crossing-ucp.csv"
    with evidence.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "crossing_attribute", "classification", "left_status", "ucp_semantic_path", "endpoint_key",
            "ucp_resolution_provenance_json",
        ])
        writer.writeheader()
        writer.writerow({
            "crossing_attribute": "clientInfo.names.surname",
            "classification": "FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
            "left_status": "exact_field",
            "ucp_semantic_path": "IndividualName.surname",
            "endpoint_key": "com.sbt.bm.ucp.retail.model.individual.IndividualName.surname",
            "ucp_resolution_provenance_json": "[]",
        })
        writer.writerow({
            "crossing_attribute": "clientInfo.ucpID",
            "classification": "FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED",
            "left_status": "exact_field",
            "ucp_semantic_path": "Individual.id",
            "endpoint_key": "com.sbt.bm.ucp.retail.model.individual.Individual.id",
            "ucp_resolution_provenance_json": "[]",
        })

    interactions = tmp_path / "interaction.csv"
    with interactions.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, delimiter=";", fieldnames=[
            "interaction", "role", "producer_repository", "producer_attribute", "crossing_attribute",
            "consumer_repository", "consumer_attribute", "gap", "full_attribute_path",
        ])
        writer.writeheader()
        writer.writerow({
            "interaction": "HTTP POST /cpcGet",
            "role": "response",
            "producer_repository": "ucp",
            "producer_attribute": "clientInfo.names.surname",
            "crossing_attribute": "clientInfo.names.surname",
            "consumer_repository": "cpc",
            "consumer_attribute": "bankAcctRecs[].cardAcctId.custInfo.personInfo.personName.lastName",
            "gap": "",
            "full_attribute_path": "ucp → clientInfo.names.surname → cpc.lastName",
        })
        writer.writerow({
            "interaction": "HTTP POST /cpcGet",
            "role": "response",
            "producer_repository": "ucp",
            "producer_attribute": "ucp.id",
            "crossing_attribute": "clientInfo.ucpID",
            "consumer_repository": "cpc",
            "consumer_attribute": "",
            "gap": "external semantic evidence only",
            "full_attribute_path": "ucp.id → clientInfo.ucpID",
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
        if kwargs["source_field"] == "surname":
            return [{
                "status": "confirmed",
                "source_type_fqcn": kwargs["source_object"],
                "source_field": kwargs["source_field"],
                "source_attribute_path": "IndividualName.surname",
                "source_revision_id": "rev-u",
                "replica_relation": "individualname_replica",
                "replica_column": "surname",
                "target_relation": "epk_client",
                "target_column": "last_name",
            }]
        return [{
            "status": "confirmed",
            "source_type_fqcn": kwargs["source_object"],
            "source_field": kwargs["source_field"],
            "source_attribute_path": "Individual.id",
            "source_revision_id": "rev-u",
            "replica_relation": "individual_replica",
            "replica_column": "id",
            "target_relation": "epkid_2_epkid",
            "target_column": "merge_epk_id",
        }]
    monkeypatch.setattr(cli, "build_lineage", fake_build_lineage)

    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"
    rc = cli.main([
        "build", "--aisl-base-url", "http://aisl",
        "--crossing-ucp-evidence", str(evidence),
        "--interaction-lineage-csv", str(interactions),
        "--consumer-repository", "cpc",
        "--consumer-output-root", "bankAcctRecs",
        "--source-system", "ucp", "--source-revision", "rev-u",
        "--bridge-system", "tsa", "--bridge-revision", "rev-t",
        "--target-system", "profile", "--target-revision", "rev-p",
        "--output-json", str(out_json), "--output-csv", str(out_csv),
    ])
    assert rc == 0
    assert sorted(calls) == [
        ("com.sbt.bm.ucp.retail.model.individual.Individual", "id"),
        ("com.sbt.bm.ucp.retail.model.individual.IndividualName", "surname"),
    ]
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "kpk-profile-fl-lineage/v2"
    by_crossing = {row["cpc_crossing_attribute"]: row for row in payload["rows"]}
    assert by_crossing["clientInfo.names.surname"]["kpk_attribute"].endswith("personName.lastName")
    assert by_crossing["clientInfo.names.surname"]["profile_fl_column"] == "last_name"
    assert by_crossing["clientInfo.names.surname"]["join_status"] == "confirmed_exact_ucp_semantic_path_and_kpk_egress"
    assert by_crossing["clientInfo.ucpID"]["kpk_attribute"] == ""
    assert by_crossing["clientInfo.ucpID"]["profile_fl_column"] == "merge_epk_id"
    assert by_crossing["clientInfo.ucpID"]["join_status"] == "unresolved_kpk_egress"
    assert by_crossing["clientInfo.ucpID"]["gap"] == "kpk_consumer_attribute_not_observed"
    assert out_csv.exists()


def test_cli_rejects_old_misnamed_kpk_attribute_input(monkeypatch, tmp_path: Path):
    evidence = tmp_path / "old.csv"
    evidence.write_text(
        "kpk_attribute,classification,left_status,ucp_semantic_path,endpoint_key\n"
        "clientInfo.names.surname,FAMILY_LEVEL_EXTERNAL_SEMANTIC_COVERED,exact_field,IndividualName.surname,x.y\n",
        encoding="utf-8",
    )
    interactions = tmp_path / "interaction.csv"
    interactions.write_text(
        "interaction;role;producer_repository;producer_attribute;crossing_attribute;consumer_repository;consumer_attribute;gap;full_attribute_path\n",
        encoding="utf-8",
    )
    rc = cli.main([
        "build",
        "--crossing-ucp-evidence", str(evidence),
        "--interaction-lineage-csv", str(interactions),
        "--consumer-repository", "cpc",
        "--consumer-output-root", "bankAcctRecs",
        "--source-system", "ucp", "--source-revision", "rev-u",
        "--bridge-system", "tsa", "--bridge-revision", "rev-t",
        "--target-system", "profile", "--target-revision", "rev-p",
        "--output-json", str(tmp_path / "o.json"), "--output-csv", str(tmp_path / "o.csv"),
    ])
    assert rc == 2
