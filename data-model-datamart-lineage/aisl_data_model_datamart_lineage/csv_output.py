from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Sequence


CSV_COLUMNS = (
    "source_system_id",
    "source_revision_id",
    "source_root_object",
    "source_attribute_path",
    "source_type_fqcn",
    "source_field",
    "tsa_system_id",
    "tsa_revision_id",
    "tsa_mapping_status",
    "tsa_mapping_basis",
    "replica_relation",
    "replica_column",
    "profile_system_id",
    "profile_revision_id",
    "profile_source_relation",
    "profile_source_column",
    "profile_representation_variant",
    "target_relation",
    "target_column",
    "relation_path",
    "lineage_depth",
    "transformation_path",
    "path_segments_json",
    "status",
    "gap",
    "provenance_json",
)


def write_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in CSV_COLUMNS})
