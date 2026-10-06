from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


TABLE_COLUMNS = (
    "logical_type_fqcn",
    "logical_type_name",
    "replica_relation",
    "key_kind",
    "key_annotation",
    "key_logical_fields",
    "key_replica_columns",
    "key_status",
    "key_gap",
    "version_logical_field",
    "version_replica_column",
    "collocation_logical_field",
    "collocation_replica_column",
    "physical_constraint_status",
    "physical_constraint_gap",
    "provenance_json",
)

LINK_COLUMNS = (
    "source_table",
    "relationship",
    "target_table",
    "source_identity",
    "target_identity",
    "physical_join_status",
)

RELATIONSHIP_COLUMNS = (
    "source_type_fqcn",
    "source_replica_relation",
    "source_key_columns",
    "source_key_status",
    "relationship_field",
    "declared_type_expression",
    "relationship_kind",
    "ucp_resolution_status",
    "target_type_fqcn",
    "target_replica_relation",
    "target_key_columns",
    "target_key_status",
    "physical_join_status",
    "physical_join_condition",
    "status",
    "gap",
    "provenance_json",
)


def _cell(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return ";".join(str(v) for v in value)
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return value if value is not None else ""


def _write_csv(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            rendered = {name: _cell(row.get(name)) for name in columns}
            if "provenance_json" in columns:
                rendered["provenance_json"] = json.dumps(
                    row.get("provenance") or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            writer.writerow(rendered)


def write_tables_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    _write_csv(rows, TABLE_COLUMNS, output)


def write_relationships_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    _write_csv(rows, RELATIONSHIP_COLUMNS, output)


def write_links_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    projected = [
        {
            "source_table": row.get("source_replica_relation"),
            "relationship": row.get("relationship_field"),
            "target_table": row.get("target_replica_relation"),
            "source_identity": row.get("source_key_columns") or [],
            "target_identity": row.get("target_key_columns") or [],
            "physical_join_status": row.get("physical_join_status"),
        }
        for row in rows
    ]
    _write_csv(projected, LINK_COLUMNS, output)
