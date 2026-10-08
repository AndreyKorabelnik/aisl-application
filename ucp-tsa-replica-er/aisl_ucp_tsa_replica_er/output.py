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

REPLICA_FIELD_COLUMNS = (
    "replica_relation",
    "replica_column",
    "ucp_type_fqcn",
    "ucp_type_description",
    "ucp_field",
    "ucp_field_type",
    "ucp_field_description",
    "description_status",
    "mapping_status",
    "gap",
    "provenance_json",
)


KEY_COLUMNS = (
    "table",
    "logical_pk",
    "key_kind",
    "logical_pk_status",
    "physical_pk_status",
    "gap",
)

LINK_COLUMNS = (
    "source_table",
    "relationship",
    "target_table",
    "target_logical_pk",
    "logical_link_status",
    "physical_fk_status",
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


def _compact_status(value: Any, confirmed_value: str) -> str:
    text = str(value or "").strip()
    if text == confirmed_value:
        return "confirmed"
    return text


def write_keys_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    projected = [
        {
            "table": row.get("replica_relation"),
            "logical_pk": row.get("key_replica_columns") or [],
            "key_kind": row.get("key_kind"),
            "logical_pk_status": _compact_status(
                row.get("key_status"), "confirmed_declared_identity_mapped"
            ),
            "physical_pk_status": row.get("physical_constraint_status"),
            "gap": row.get("key_gap"),
        }
        for row in rows
    ]
    _write_csv(projected, KEY_COLUMNS, output)


def write_links_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    projected = [
        {
            "source_table": row.get("source_replica_relation"),
            "relationship": row.get("relationship_field"),
            "target_table": row.get("target_replica_relation"),
            "target_logical_pk": row.get("target_key_columns") or [],
            "logical_link_status": _compact_status(
                row.get("status"), "confirmed_ucp_relationship_projected_to_replicas"
            ),
            "physical_fk_status": row.get("physical_join_status"),
        }
        for row in rows
    ]
    _write_csv(projected, LINK_COLUMNS, output)


def write_replica_fields_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    _write_csv(rows, REPLICA_FIELD_COLUMNS, output)
