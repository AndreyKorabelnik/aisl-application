from __future__ import annotations

import csv
import json

from aisl_interaction_lineage.cli import main
from aisl_interaction_lineage.human_csv import HUMAN_CSV_COLUMNS, human_rows


def lineage() -> dict:
    return {
        "format": "interaction-attribute-lineage/v1",
        "edge": {"protocol": "http", "method": "POST", "matched_identity": "/cpcGet"},
        "journeys": [{
            "transport_role": "request",
            "field_path": "ucpID",
            "source_repository_id": "caller",
            "target_repository_id": "provider",
            "source_side": {
                "anchor_status": "resolved",
                "resolved_anchor": {"display_ref": "request.ucpID", "operation": "Caller.buildRequest"},
                "query": {"result": {"paths": [{
                    "start": {"display_ref": "ucpID", "operation": "Caller.boundary"},
                    "end": {"display_ref": "clientId.toString()", "operation": "Caller.buildRequest"},
                    "steps": [{
                        "source": {"display_ref": "ucpID"},
                        "target": {"display_ref": "clientId.toString()"},
                        "transformation": {"kind": "observed_expression", "expression": "toString"},
                    }],
                }]}}
            },
            "target_side": {
                "anchor_status": "resolved",
                "resolved_anchor": {"display_ref": "ucpID", "operation": "Provider.boundary"},
                "query": {"result": {"paths": [{
                    "start": {"display_ref": "ucpID", "operation": "Provider.boundary"},
                    "end": {"display_ref": "RSC client lookup", "operation": "Provider.lookup"},
                    "steps": [{
                        "source": {"display_ref": "ucpID"},
                        "target": {"display_ref": "RSC client lookup"},
                        "transformation": {"kind": "observed_expression", "expression": "Long.parseLong"},
                    }],
                }]}}
            },
        }],
        "gaps": [],
    }


def test_human_rows_use_compact_analyst_contract_and_preserve_full_path() -> None:
    rows = human_rows(lineage())
    assert len(rows) == 1
    row = rows[0]
    assert tuple(row) == HUMAN_CSV_COLUMNS
    assert row == {
        "interaction": "HTTP POST /cpcGet",
        "role": "request",
        "producer_repository": "caller",
        "producer_attribute": "clientId.toString()",
        "crossing_attribute": "ucpID",
        "consumer_repository": "provider",
        "consumer_attribute": "ucpID",
        "gap": "",
        "full_attribute_path": (
            "caller: clientId.toString() --[toString]→ ucpID "
            "== HTTP POST /cpcGet / request ==> "
            "provider: ucpID --[Long.parseLong]→ RSC client lookup"
        ),
    }


def test_consumer_attribute_is_first_resolved_local_anchor_not_final_destination() -> None:
    row = human_rows(lineage())[0]
    assert row["consumer_attribute"] == "ucpID"
    assert "RSC client lookup" in row["full_attribute_path"]


def test_human_rows_translate_gap_to_russian_but_keep_machine_gap_in_full_path() -> None:
    value = lineage()
    journey = value["journeys"][0]
    journey["target_side"] = {
        "anchor_status": "unresolved",
        "resolved_anchor": None,
        "query": {"result": {"paths": []}},
    }
    value["gaps"] = [{
        "reason": "target_local_anchor_unresolved",
        "repository_id": "provider",
        "transport_role": "request",
        "field_path": "ucpID",
        "side": "target",
    }]

    row = human_rows(value)[0]
    assert row["consumer_attribute"] == ""
    assert row["gap"] == "не удалось определить дальнейшее использование атрибута в consumer"
    assert row["full_attribute_path"].endswith("[GAP: target_local_anchor_unresolved]")


def test_human_rows_collapse_multiple_producer_origins_to_crossing_attribute() -> None:
    value = lineage()
    source_side = value["journeys"][0]["source_side"]
    source_side["query"]["result"]["paths"].append({
        "start": {"display_ref": "ucpID", "operation": "Caller.boundary"},
        "end": {"display_ref": "fallback.ucpID", "operation": "Caller.fallback"},
        "steps": [],
    })

    row = human_rows(value)[0]
    assert row["producer_attribute"] == "ucpID"
    assert "clientId.toString() | OR | fallback.ucpID" in row["full_attribute_path"]

def test_csv_cli_writes_semicolon_utf8_human_projection(tmp_path) -> None:
    source = tmp_path / "lineage.json"
    output = tmp_path / "lineage.csv"
    source.write_text(json.dumps(lineage()), encoding="utf-8")

    assert main(["csv", "--input", str(source), "--output", str(output)]) == 0

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert len(rows) == 1
    assert rows[0]["crossing_attribute"] == "ucpID"
    assert list(rows[0]) == list(HUMAN_CSV_COLUMNS)
