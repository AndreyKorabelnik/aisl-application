from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

CSV_COLUMNS = (
    "ucp_type",
    "ucp_attribute",
    "ucp_service",
    "kpk_service",
    "kpk_crossing_attribute",
    "kpk_attribute",
    "tsa_replica_relation",
    "tsa_replica_column",
    "profile_fl_relation",
    "profile_fl_column",
    "kpk_branch_status",
    "profile_fl_branch_status",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _ucp_identity(endpoint_key: str) -> tuple[str, str]:
    value = _text(endpoint_key)
    if "." not in value:
        return value, ""
    return value.rsplit(".", 1)


def _ucp_service(row: Mapping[str, Any]) -> str:
    raw = _text(row.get("kpk_interaction_provenance_json"))
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, list):
        return ""
    values = sorted({
        _text(item.get("producer_repository"))
        for item in payload
        if isinstance(item, Mapping) and _text(item.get("producer_repository"))
    })
    return values[0] if len(values) == 1 else ""


def _profile_branch_proven(row: Mapping[str, Any]) -> bool:
    if not (_text(row.get("tsa_replica_relation")) and _text(row.get("tsa_replica_column"))):
        return False
    if not (_text(row.get("profile_fl_relation")) and _text(row.get("profile_fl_column"))):
        return False
    gap = _text(row.get("gap"))
    return not any(marker in gap for marker in (
        "right_context_not_exact",
        "task46_target_specific_ucp_context_not_bound",
        "profile_confirmed_lineage_not_found",
    ))


def consumer_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Render one common-UCP-origin view with two independent downstream branches.

    A row is retained when at least one downstream branch is mechanically proven:
    UCP -> final KPK egress, or UCP -> TSA -> Profile FL.  When final KPK egress
    is not proven but an exact KPK crossing is observed, preserve that crossing
    on rows backed by a proven Profile FL branch.  If a final KPK egress exists
    for the same UCP endpoint, partial crossings remain diagnostic-only so they
    cannot duplicate the proven KPK branch.
    """
    kpk_by_endpoint: dict[str, dict[tuple[str, str, str, str], Mapping[str, Any]]] = defaultdict(dict)
    kpk_crossings_by_endpoint: dict[str, dict[tuple[str, str, str], Mapping[str, Any]]] = defaultdict(dict)
    profile_by_endpoint: dict[str, dict[tuple[str, str, str, str], Mapping[str, Any]]] = defaultdict(dict)

    for raw in rows:
        row = dict(raw)
        endpoint = _text(row.get("ucp_endpoint_key"))
        if not endpoint:
            continue
        kpk_attribute = _text(row.get("kpk_attribute"))
        kpk_crossing = _text(row.get("cpc_crossing_attribute"))
        if kpk_attribute:
            key = (
                _ucp_service(row),
                _text(row.get("kpk_service")),
                kpk_crossing,
                kpk_attribute,
            )
            kpk_by_endpoint[endpoint].setdefault(key, row)
        elif kpk_crossing:
            key = (
                _ucp_service(row),
                _text(row.get("kpk_service")),
                kpk_crossing,
            )
            kpk_crossings_by_endpoint[endpoint].setdefault(key, row)
        if _profile_branch_proven(row):
            key = (
                _text(row.get("tsa_replica_relation")),
                _text(row.get("tsa_replica_column")),
                _text(row.get("profile_fl_relation")),
                _text(row.get("profile_fl_column")),
            )
            profile_by_endpoint[endpoint].setdefault(key, row)

    rendered: list[dict[str, str]] = []
    for endpoint in sorted(set(kpk_by_endpoint) | set(kpk_crossings_by_endpoint) | set(profile_by_endpoint)):
        ucp_type, ucp_attribute = _ucp_identity(endpoint)
        proven_kpk_rows = list(kpk_by_endpoint.get(endpoint, {}).values())
        observed_kpk_rows = list(kpk_crossings_by_endpoint.get(endpoint, {}).values())
        kpk_rows = proven_kpk_rows or observed_kpk_rows
        profile_rows = list(profile_by_endpoint.get(endpoint, {}).values())

        def base() -> dict[str, str]:
            return {
                "ucp_type": ucp_type,
                "ucp_attribute": ucp_attribute,
                "ucp_service": "",
                "kpk_service": "",
                "kpk_crossing_attribute": "",
                "kpk_attribute": "",
                "tsa_replica_relation": "",
                "tsa_replica_column": "",
                "profile_fl_relation": "",
                "profile_fl_column": "",
                "kpk_branch_status": "not_proven",
                "profile_fl_branch_status": "not_proven",
            }

        if profile_rows and kpk_rows:
            for profile in profile_rows:
                for kpk in kpk_rows:
                    out = base()
                    out.update({
                        "ucp_service": _ucp_service(kpk),
                        "kpk_service": _text(kpk.get("kpk_service")),
                        "kpk_crossing_attribute": _text(kpk.get("cpc_crossing_attribute")),
                        "kpk_attribute": _text(kpk.get("kpk_attribute")),
                        "tsa_replica_relation": _text(profile.get("tsa_replica_relation")),
                        "tsa_replica_column": _text(profile.get("tsa_replica_column")),
                        "profile_fl_relation": _text(profile.get("profile_fl_relation")),
                        "profile_fl_column": _text(profile.get("profile_fl_column")),
                        "kpk_branch_status": (
                            "proven" if _text(kpk.get("kpk_attribute"))
                            else "crossing_observed_egress_not_proven"
                        ),
                        "profile_fl_branch_status": "proven",
                    })
                    rendered.append(out)
        elif profile_rows:
            for profile in profile_rows:
                out = base()
                out.update({
                    "tsa_replica_relation": _text(profile.get("tsa_replica_relation")),
                    "tsa_replica_column": _text(profile.get("tsa_replica_column")),
                    "profile_fl_relation": _text(profile.get("profile_fl_relation")),
                    "profile_fl_column": _text(profile.get("profile_fl_column")),
                    "profile_fl_branch_status": "proven",
                })
                rendered.append(out)
        elif proven_kpk_rows:
            for kpk in proven_kpk_rows:
                out = base()
                out.update({
                    "ucp_service": _ucp_service(kpk),
                    "kpk_service": _text(kpk.get("kpk_service")),
                    "kpk_crossing_attribute": _text(kpk.get("cpc_crossing_attribute")),
                    "kpk_attribute": _text(kpk.get("kpk_attribute")),
                    "kpk_branch_status": "proven",
                })
                rendered.append(out)

    unique: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rendered:
        unique.setdefault(tuple(row[name] for name in CSV_COLUMNS), row)
    return sorted(unique.values(), key=lambda row: tuple(row[name] for name in CSV_COLUMNS))


def write_csv(rows: Sequence[Mapping[str, Any]], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(consumer_rows(rows))
