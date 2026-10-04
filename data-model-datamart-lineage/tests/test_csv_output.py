from __future__ import annotations

import csv
from pathlib import Path

from aisl_data_model_datamart_lineage.csv_output import CSV_COLUMNS, write_csv


def test_write_csv_keeps_full_contract(tmp_path: Path):
    row = {name: f"v-{name}" for name in CSV_COLUMNS}
    output = tmp_path / "result.csv"
    write_csv([row], output)
    with output.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert rows[0]["path_segments_json"] == "v-path_segments_json"
