from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .contracts import SUPPORTED_INVENTORY_FORMAT
from .model import HalfWire

_REQUEST_FIELD_RE = re.compile(r"^\$\.request_fields\[\d+\]\.name$")
_RESPONSE_FIELD_RE = re.compile(r"^\$\.response_fields\[\d+\]\.name$")
_PAYLOAD_FIELD_RE = re.compile(r"^\$\.payload_fields\[\d+\]\.name$")


class InventoryInputError(ValueError):
    pass


REDUCED_INVENTORY_FILENAME = "repository_inventory_reduced.json"


def discover_reduced_inventory_paths(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        raise InventoryInputError(f"inventory directory does not exist: {root}")
    if not root.is_dir():
        raise InventoryInputError(f"inventory directory is not a directory: {root}")
    paths = sorted(path for path in root.rglob(REDUCED_INVENTORY_FILENAME) if path.is_file())
    if len(paths) < 2:
        raise InventoryInputError(
            f"inventory directory must contain at least two {REDUCED_INVENTORY_FILENAME} artifacts: {root}"
        )
    return paths


def load_reduced_inventory(path: Path, *, input_index: int) -> tuple[dict[str, Any], list[HalfWire]]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InventoryInputError(f"invalid JSON: {path}: {exc}") from exc
    if payload.get("format") != SUPPORTED_INVENTORY_FORMAT:
        raise InventoryInputError(
            f"unsupported inventory format for {path}: {payload.get('format')!r}; expected {SUPPORTED_INVENTORY_FORMAT!r}"
        )
    source_inventory = payload.get("source_inventory") or {}
    repository_id = str(source_inventory.get("repository_id") or "")
    if not repository_id:
        raise InventoryInputError(f"missing source_inventory.repository_id: {path}")
    artifact_id = str(payload.get("reduced_inventory_id") or "")
    semantic_fingerprint = str(payload.get("semantic_fingerprint") or "")
    if not artifact_id or not semantic_fingerprint:
        raise InventoryInputError(f"missing reduced inventory identity/fingerprint: {path}")

    exact_by_id = {
        str(row.get("exact_representation_id")): row
        for row in payload.get("exact_representations") or []
        if isinstance(row, dict) and row.get("exact_representation_id")
    }
    half_wires: list[HalfWire] = []
    seen: set[tuple[Any, ...]] = set()
    for observed in payload.get("observed_identities") or []:
        if not isinstance(observed, dict):
            continue
        identity = observed.get("identity") or {}
        if identity.get("family_kind") not in {"http_boundary_observation", "kafka_boundary_observation"}:
            continue
        relevant_exact = []
        metrics_candidates = []
        for exact_id in observed.get("exact_representation_ids") or []:
            exact = exact_by_id.get(str(exact_id))
            if not exact:
                continue
            basis = exact.get("exact_representation_basis") or {}
            if basis.get("family_kind") != identity.get("family_kind"):
                continue
            metrics = basis.get("observed_metrics") or {}
            relevant_exact.append(str(exact_id))
            metrics_candidates.append(metrics)
        if not metrics_candidates:
            continue

        facet_values: dict[str, list[str]] = defaultdict(list)
        for facet in identity.get("string_facets") or []:
            if isinstance(facet, dict) and isinstance(facet.get("path"), str) and isinstance(facet.get("value"), str):
                facet_values[facet["path"]].append(facet["value"])
        family_label = str(identity.get("family_label") or "")

        # Metrics are shape-redacted exact representations; direction/method/status are stable structural values.
        for metrics in metrics_candidates:
            protocol = str(metrics.get("protocol") or "")
            direction = str(metrics.get("direction") or "")
            if protocol not in {"http", "kafka"} or direction not in {"inbound", "outbound", "consume", "publish"}:
                continue
            method = metrics.get("method") if isinstance(metrics.get("method"), str) else None
            path_status = metrics.get("path_status") if isinstance(metrics.get("path_status"), str) else None
            transport_identity_kind = None
            if protocol == "http":
                paths: list[str] = []
                if path_status == "resolved" and family_label.startswith("/"):
                    paths.append(family_label)
                for key, values in facet_values.items():
                    if key.startswith("$.path_candidates["):
                        paths.extend(values)
            else:
                topic_status = metrics.get("topic_status") if isinstance(metrics.get("topic_status"), str) else None
                transport_identity_kind = metrics.get("topic_identity_kind") if isinstance(metrics.get("topic_identity_kind"), str) else None
                path_status = topic_status
                paths = []
                if topic_status == "resolved":
                    # Kafka family_label is the observed topic identity for literal/config-key facts.
                    if family_label:
                        paths.append(family_label)
                for key, values in facet_values.items():
                    if key.startswith("$.topic_candidates["):
                        paths.extend(values)
            paths = sorted(set(v for v in paths if v))
            request_fields = sorted(
                set(v for key, values in facet_values.items() if _REQUEST_FIELD_RE.match(key) for v in values)
            )
            request_payload = _first(facet_values.get("$.request_payload"))
            response_payload = _first(facet_values.get("$.response_payload"))
            response_fields = sorted(
                set(v for key, values in facet_values.items() if _RESPONSE_FIELD_RE.match(key) for v in values)
            )
            payload_identity = _first(facet_values.get("$.payload_identity"))
            payload_fields = sorted(set(v for key, values in facet_values.items() if _PAYLOAD_FIELD_RE.match(key) for v in values))
            key = (
                repository_id,
                str(observed.get("observed_identity_id") or ""),
                protocol,
                direction,
                method,
                path_status,
                tuple(paths),
            )
            if key in seen:
                continue
            seen.add(key)
            half_wires.append(
                HalfWire(
                    repository_id=repository_id,
                    input_index=input_index,
                    observed_identity_id=str(observed.get("observed_identity_id") or ""),
                    exact_representation_ids=tuple(sorted(set(relevant_exact))),
                    representative_evidence_id=str(observed.get("representative_evidence_id") or ""),
                    direction=direction,
                    protocol=protocol,
                    method=method,
                    path_status=path_status,
                    paths=tuple(paths),
                    family_label=family_label,
                    occurrence_count=int(observed.get("occurrence_count") or 0),
                    transport_identity_kind=transport_identity_kind,
                    request_payload=request_payload,
                    request_field_names=tuple(request_fields),
                    response_payload=response_payload,
                    response_field_names=tuple(response_fields),
                    payload_identity=payload_identity,
                    payload_field_names=tuple(payload_fields),
                )
            )

    input_record = {
        "repository_id": repository_id,
        "artifact_format": SUPPORTED_INVENTORY_FORMAT,
        "artifact_id": artifact_id,
        "semantic_fingerprint": semantic_fingerprint,
        "source_inventory_id": str(source_inventory.get("inventory_id") or ""),
        "source_snapshot_fingerprint": str(source_inventory.get("source_snapshot_fingerprint") or ""),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    half_wires.sort(key=lambda h: (h.protocol, h.direction, h.method or "", h.paths, h.observed_identity_id))
    return input_record, half_wires


def _first(values: Iterable[str] | None) -> str | None:
    if not values:
        return None
    return next(iter(values), None)
