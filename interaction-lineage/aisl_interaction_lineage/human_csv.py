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
    "source_external_origin_unresolved": (
        "источник атрибута выходит за текущую опубликованную область знаний; "
        "внешний owner не определён механически"
    ),
    "source_external_origin_link_unproven": (
        "внешний semantic evidence найден; точная связь этого evidence с локальным вызовом "
        "между репозиториями не наблюдается"
    ),
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


def _source_semantic_chain(side: Any) -> list[str]:
    projection = _mapping(_mapping(side).get("semantic_projection"))
    return [
        str(_mapping(item).get("display_ref") or "").strip()
        for item in _sequence(projection.get("chain"))
        if isinstance(item, Mapping) and str(_mapping(item).get("display_ref") or "").strip()
    ]


def _external_origin_segments(side: Any) -> list[Mapping[str, Any]]:
    evidence = _mapping(_mapping(side).get("external_origin_evidence"))
    return [item for item in _sequence(evidence.get("segments")) if isinstance(item, Mapping)]


def _external_transformation_label(item: Mapping[str, Any]) -> str:
    base = _display_ref(item)
    supplemental = _mapping(item.get("unresolved_callee_semantic_evidence"))
    if not supplemental:
        return base
    observed = _join_unique(
        (_display_ref(value) for value in _sequence(supplemental.get("transformations")) if isinstance(value, Mapping)),
        separator=" → ",
    )
    operation = str(supplemental.get("operation") or supplemental.get("method_name") or "").strip()
    if not observed:
        return base
    qualifier = f"unique observed {operation}; call link not observed" if operation else "unique observed method body; call link not observed"
    if base:
        return f"{base} ~[{qualifier}]~ {observed}"
    return f"[{qualifier}] {observed}"


def _external_origin_projection(side: Any) -> str:
    segments = _external_origin_segments(side)
    direct_by_target = {
        _display_ref(_mapping(segment.get("target"))): segment
        for segment in segments
        if int(segment.get("semantic_depth") or 0) == 0
        and _display_ref(_mapping(segment.get("target")))
    }
    direct_by_target_id = {
        str(_mapping(segment.get("target")).get("value_node_id") or ""): segment
        for segment in segments
        if int(segment.get("semantic_depth") or 0) == 0
        and str(_mapping(segment.get("target")).get("value_node_id") or "")
    }
    expanded_parent_ids = {
        str(segment.get("parent_segment_target_value_node_id") or "")
        for segment in segments
        if int(segment.get("semantic_depth") or 0) > 0
        and str(segment.get("parent_segment_target_value_node_id") or "")
    }

    projected: list[str] = []
    ordered = sorted(
        segments,
        key=lambda item: (
            -int(item.get("semantic_depth") or 0),
            str(item.get("repository_id") or ""),
            _display_ref(_mapping(item.get("target"))),
        ),
    )
    for segment in ordered:
        semantic_depth = int(segment.get("semantic_depth") or 0)
        target_mapping = _mapping(segment.get("target"))
        target_id = str(target_mapping.get("value_node_id") or "")
        if semantic_depth == 0 and target_id in expanded_parent_ids:
            # The nested segment is a strictly richer projection of this exact
            # observed parent mapping.  Render the richer branch once rather
            # than duplicating its shallower prefix.
            continue

        repository_id = str(segment.get("repository_id") or "").strip()
        origin_items = (
            _sequence(segment.get("composed_origins"))
            if semantic_depth > 0 and _sequence(segment.get("composed_origins"))
            else _sequence(segment.get("origins"))
        )
        origins = [_display_ref(item) for item in origin_items if isinstance(item, Mapping)]
        target = _display_ref(target_mapping)
        transformations = [
            _external_transformation_label(item) for item in _sequence(segment.get("transformations"))
            if isinstance(item, Mapping)
        ]
        origin = _join_unique(origins, separator=" | OR | ")
        transform = _join_unique(transformations, separator=" -> ")
        if not repository_id or not origin or not target:
            continue
        path = f"{repository_id}: {origin}"
        if transform:
            path += f" --[{transform}]→ {target}"
        elif origin != target:
            path += f" → {target}"

        if semantic_depth > 0:
            parent_id = str(segment.get("parent_segment_target_value_node_id") or "")
            parent = direct_by_target_id.get(parent_id)
            parent_target = _display_ref(_mapping(parent.get("target"))) if parent else ""
            parent_transform = str(segment.get("parent_transformation_display_ref") or "").strip()
            if parent_target:
                if parent_transform:
                    path += f" ~[inside {parent_transform}]→ {parent_target}"
                else:
                    path += f" ~[inside observed parent mapping]→ {parent_target}"
        projected.append(path)
    return _join_unique(projected, separator=" | OR SEGMENT | ")


def _producer_attribute(side: Any, start_attribute: str, crossing_attribute: str) -> str:
    if str(_mapping(side).get("anchor_status") or "") != "resolved":
        return ""
    segments = _external_origin_segments(side)
    deepest_composed_depth = max(
        (
            int(segment.get("semantic_depth") or 0)
            for segment in segments
            if _sequence(segment.get("composed_origins"))
        ),
        default=-1,
    )
    if deepest_composed_depth >= 0:
        composed_origins = [
            _display_ref(origin)
            for segment in segments
            if int(segment.get("semantic_depth") or 0) == deepest_composed_depth
            for origin in _sequence(segment.get("composed_origins"))
            if isinstance(origin, Mapping)
        ]
        composed_unique = _join_unique(composed_origins, separator=" | OR | ")
        if composed_unique and " | OR | " not in composed_unique:
            return composed_unique
        if composed_unique:
            return crossing_attribute

    external_origins = [
        _display_ref(origin)
        for segment in segments
        for origin in _sequence(segment.get("origins"))
        if isinstance(origin, Mapping)
    ]
    external_unique = _join_unique(external_origins, separator=" | OR | ")
    if external_unique and " | OR | " not in external_unique:
        return external_unique
    if external_unique:
        return crossing_attribute
    starts = [_display_ref(_mapping(path.get("end"))) for path in _paths(side)]
    unique = _join_unique(starts, separator=" | OR | ")
    if unique and " | OR | " not in unique:
        return unique
    if unique:
        return crossing_attribute
    return start_attribute or crossing_attribute


def _consumer_attribute(side: Any) -> str:
    """Return the deepest mechanically proven semantic consumer after the crossing."""
    if str(_mapping(side).get("anchor_status") or "") != "resolved":
        return ""
    semantic = _mapping(_mapping(side).get("semantic_projection"))
    semantic_chain = [
        str(_mapping(item).get("semantic_ref") or "").strip()
        for item in _sequence(semantic.get("chain"))
        if isinstance(item, Mapping) and str(_mapping(item).get("semantic_ref") or "").strip()
    ]
    if semantic_chain:
        return semantic_chain[-1]
    consumer = str(semantic.get("consumer_attribute") or "").strip()
    if consumer:
        return consumer
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
    """Project forward AISL paths into boundary -> semantic local destination."""
    semantic = _mapping(_mapping(side).get("semantic_projection"))
    semantic_refs = [
        str(_mapping(item).get("semantic_ref") or "").strip()
        for item in _sequence(semantic.get("chain"))
        if isinstance(item, Mapping)
    ]
    semantic_path = _join_unique(semantic_refs, separator=" → ")
    if semantic_path:
        return "", semantic_path

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

        semantic_source_chain = _source_semantic_chain(source_side)
        if semantic_source_chain:
            source_path = " → ".join(semantic_source_chain)
            if semantic_source_chain[-1] != crossing_attribute:
                source_path += f" → {crossing_attribute}"
        else:
            source_path = start_attribute or "[unresolved source]"
            if source_transformation:
                source_path += f" --[{source_transformation}]→ {crossing_attribute}"
            elif source_path != crossing_attribute:
                source_path += f" → {crossing_attribute}"

        target_path = crossing_attribute
        target_terminal = str(target_side.get("anchor_status") or "") == "terminal"
        if target_transformation:
            target_path += f" --[{target_transformation}]→ {target_destination or '[unresolved target]'}"
        elif target_destination and target_destination != crossing_attribute:
            target_path += f" → {target_destination}"
        elif not target_destination and not target_terminal:
            target_path += " → [unresolved target]"

        external_projection = _external_origin_projection(source_side)
        source_projection = f"{source_repository}: {source_path}"
        if external_projection:
            source_projection = (
                f"{external_projection} "
                f"~[cross-repository link not observed]~ {source_projection}"
            )
        full_path = (
            f"{source_projection} "
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
