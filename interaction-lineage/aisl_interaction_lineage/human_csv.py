from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

LINEAGE_FORMAT = "interaction-attribute-lineage/v1"
HUMAN_CSV_COLUMNS = (
    "interaction",
    "role",
    "producer_repository",
    "producer_attribute",
    "crossing_attribute",
    "consumer_repository",
    "consumer_attribute",
    "gap",
    "full_attribute_path",
)

_GAP_LABELS_RU = {
    "source_local_anchor_unresolved": "не удалось определить источник атрибута внутри producer",
    "target_local_anchor_unresolved": "не удалось определить дальнейшее использование атрибута в consumer",
    "payload_identity_not_exactly_compatible": "не удалось доказать точное соответствие transport payload",
    "OBSERVED_TERMINAL_NO_USE": "дальнейшее использование атрибута не наблюдается",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _display_ref(node: Any) -> str:
    return str(_mapping(node).get("display_ref") or "").strip()


def _transformation(step: Any) -> str:
    transformation = _mapping(_mapping(step).get("transformation"))
    expression = str(transformation.get("expression") or "").strip()
    if expression:
        return expression
    return str(transformation.get("kind") or "").strip()


def _join_unique(values: Iterable[str], *, separator: str = " | ") -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return separator.join(ordered)


def _result(side: Any) -> Mapping[str, Any]:
    return _mapping(_mapping(_mapping(side).get("query")).get("result"))


def _paths(side: Any) -> list[Mapping[str, Any]]:
    return [item for item in _sequence(_result(side).get("paths")) if isinstance(item, Mapping)]


def _source_projection(side: Any) -> tuple[str, str]:
    """Project reverse AISL paths into actual data-flow direction: local origin -> boundary."""
    paths = _paths(side)
    if not paths:
        anchor = _mapping(_mapping(side).get("resolved_anchor"))
        return _display_ref(anchor), ""

    starts: list[str] = []
    transformations: list[str] = []
    for path in paths:
        origin = _mapping(path.get("end"))
        starts.append(_display_ref(origin))
        steps = [item for item in _sequence(path.get("steps")) if isinstance(item, Mapping)]
        transformations.extend(_transformation(step) for step in reversed(steps))
    return (
        _join_unique(starts, separator=" | OR | "),
        _join_unique(transformations, separator=" -> "),
    )


def _producer_attribute(side: Any, start_attribute: str, crossing_attribute: str) -> str:
    if str(_mapping(side).get("anchor_status") or "") != "resolved":
        return ""
    starts = [_display_ref(_mapping(path.get("end"))) for path in _paths(side)]
    unique = _join_unique(starts, separator=" | OR | ")
    if unique and " | OR | " not in unique:
        return unique
    if unique:
        return crossing_attribute
    return start_attribute or crossing_attribute


def _consumer_attribute(side: Any) -> str:
    """Return the first mechanically proven local attribute after the crossing."""
    if str(_mapping(side).get("anchor_status") or "") != "resolved":
        return ""
    anchor = _display_ref(_mapping(_mapping(side).get("resolved_anchor")))
    if anchor:
        return anchor
    starts = [_display_ref(_mapping(path.get("start"))) for path in _paths(side)]
    unique = _join_unique(starts, separator=" | OR | ")
    return unique if " | OR | " not in unique else ""


def _human_gap(reasons: Iterable[str]) -> str:
    translated: list[str] = []
    for reason in reasons:
        value = str(reason or "").strip()
        if not value:
            continue
        try:
            translated.append(_GAP_LABELS_RU[value])
        except KeyError as exc:
            raise ValueError(f"Russian human CSV label is not defined for gap reason: {value}") from exc
    return _join_unique(translated, separator="; ")


def _target_projection(side: Any) -> tuple[str, str]:
    """Project forward AISL paths into boundary -> local destination direction."""
    paths = _paths(side)
    if not paths:
        anchor = _mapping(_mapping(side).get("resolved_anchor"))
        return "", _display_ref(anchor)

    transformations: list[str] = []
    destinations: list[str] = []
    for path in paths:
        destination = _mapping(path.get("end"))
        destinations.append(_display_ref(destination))
        for step in _sequence(path.get("steps")):
            transformations.append(_transformation(step))

    return (
        _join_unique(transformations, separator=" -> "),
        _join_unique(destinations, separator=" | "),
    )


def _transport(edge: Mapping[str, Any]) -> str:
    protocol = str(edge.get("protocol") or "").upper().strip()
    method = str(edge.get("method") or "").upper().strip()
    identity = str(edge.get("matched_identity") or "").strip()
    return " ".join(part for part in (protocol, method, identity) if part)


def _gap_index(lineage: Mapping[str, Any]) -> dict[tuple[str, str, str, str], list[str]]:
    index: dict[tuple[str, str, str, str], list[str]] = {}
    for raw in _sequence(lineage.get("gaps")):
        gap = _mapping(raw)
        key = (
            str(gap.get("transport_role") or ""),
            str(gap.get("field_path") or ""),
            str(gap.get("repository_id") or ""),
            str(gap.get("side") or ""),
        )
        reason = str(gap.get("reason") or "").strip()
        if reason:
            index.setdefault(key, []).append(reason)
    return index


def human_rows(lineage: Mapping[str, Any]) -> list[dict[str, str]]:
    if str(lineage.get("format") or "") != LINEAGE_FORMAT:
        raise ValueError(f"{LINEAGE_FORMAT} JSON required")

    edge = _mapping(lineage.get("edge"))
    transport = _transport(edge)
    gaps = _gap_index(lineage)
    rows: list[dict[str, str]] = []

    for raw in _sequence(lineage.get("journeys")):
        journey = _mapping(raw)
        role = str(journey.get("transport_role") or "")
        crossing_attribute = str(journey.get("field_path") or "")
        source_repository = str(journey.get("source_repository_id") or "")
        target_repository = str(journey.get("target_repository_id") or "")
        source_side = _mapping(journey.get("source_side"))
        target_side = _mapping(journey.get("target_side"))

        start_attribute, source_transformation = _source_projection(source_side)
        target_transformation, target_destination = _target_projection(target_side)
        producer_attribute = _producer_attribute(source_side, start_attribute, crossing_attribute)
        consumer_attribute = _consumer_attribute(target_side)

        reasons = [
            *gaps.get((role, crossing_attribute, source_repository, "source"), []),
            *gaps.get((role, crossing_attribute, target_repository, "target"), []),
            *gaps.get((role, crossing_attribute, source_repository, "crossing"), []),
        ]
        machine_gap = _join_unique(reasons)
        gap = _human_gap(reasons)

        source_path = start_attribute or "[unresolved source]"
        if source_transformation:
            source_path += f" --[{source_transformation}]→ {crossing_attribute}"
        elif source_path != crossing_attribute:
            source_path += f" → {crossing_attribute}"

        target_path = crossing_attribute
        if target_transformation:
            target_path += f" --[{target_transformation}]→ {target_destination or '[unresolved target]'}"
        elif target_destination and target_destination != crossing_attribute:
            target_path += f" → {target_destination}"
        elif not target_destination:
            target_path += " → [unresolved target]"

        full_path = (
            f"{source_repository}: {source_path} "
            f"== {transport} / {role} ==> "
            f"{target_repository}: {target_path}"
        )
        if machine_gap:
            full_path += f" [GAP: {machine_gap}]"

        rows.append({
            "interaction": transport,
            "role": role,
            "producer_repository": source_repository,
            "producer_attribute": producer_attribute,
            "crossing_attribute": crossing_attribute,
            "consumer_repository": target_repository,
            "consumer_attribute": consumer_attribute,
            "gap": gap,
            "full_attribute_path": full_path,
        })

    return rows


def write_human_csv(lineage: Mapping[str, Any], output: str | Path) -> None:
    rows = human_rows(lineage)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 BOM + semicolon makes the file open cleanly in common Excel locales.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HUMAN_CSV_COLUMNS, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
