from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Sequence

CSV_COLUMNS = (
    "kpk_service",
    "kpk_interaction",
    "kpk_attribute",
    "kpk_output_root",
    "cpc_crossing_attribute",
    "interaction_consumer_attribute",
    "kpk_evidence_classification",
    "ucp_semantic_path",
    "ucp_endpoint_key",
    "ucp_revision_id",
    "tsa_replica_relation",
    "tsa_replica_column",
    "profile_fl_relation",
    "profile_fl_column",
    "join_status",
    "gap",
    "kpk_interaction_gap",
    "full_attribute_path",
    "left_provenance_json",
    "kpk_interaction_provenance_json",
    "right_provenance_json",
)


def write_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in CSV_COLUMNS})
