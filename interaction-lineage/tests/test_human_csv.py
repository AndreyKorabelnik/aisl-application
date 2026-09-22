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


def test_human_rows_are_compact_and_follow_actual_data_flow() -> None:
    rows = human_rows(lineage())
    assert len(rows) == 1
    row = rows[0]
    assert tuple(row) == HUMAN_CSV_COLUMNS
    assert row["role"] == "request"
    assert row["start_attribute"] == "clientId.toString()"
    assert row["source_origin"] == "Caller.buildRequest"
    assert row["source_transformation"] == "toString"
    assert row["crossing_attribute"] == "ucpID"
    assert row["transport"] == "HTTP POST /cpcGet"
    assert row["target_transformation"] == "Long.parseLong"
    assert row["target_destination"] == "RSC client lookup"
    assert "crossing_status" not in row
    assert "source_anchor_basis" not in row
    assert row["full_attribute_path"] == (
        "caller: clientId.toString() --[toString]→ ucpID "
        "== HTTP POST /cpcGet / request ==> "
        "provider: ucpID --[Long.parseLong]→ RSC client lookup"
    )


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


def test_nested_crossing_attributes_are_separate_human_rows() -> None:
    payload = lineage()
    base = payload["journeys"][0]
    first = dict(base)
    first["field_path"] = "clientInfo.identifications.documentSeries"
    second = dict(base)
    second["field_path"] = "clientInfo.identifications.documentNumber"
    payload["journeys"] = [first, second]

    rows = human_rows(payload)

    assert [row["crossing_attribute"] for row in rows] == [
        "clientInfo.identifications.documentSeries",
        "clientInfo.identifications.documentNumber",
    ]
