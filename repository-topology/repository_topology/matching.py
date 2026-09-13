from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .model import HalfWire


HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD = 0.8


@dataclass(frozen=True)
class Match:
    source: HalfWire
    target: HalfWire
    classification: str
    claim_classification: str
    confidence: str
    matched_identity: str
    basis: tuple[dict[str, object], ...]


def match_all(half_wires: Iterable[HalfWire]) -> list[Match]:
    rows = list(half_wires)
    matches = [*match_http(rows), *match_kafka(rows)]
    matches.sort(key=_match_sort_key)
    return matches


def match_http(half_wires: Iterable[HalfWire]) -> list[Match]:
    outgoing = [h for h in half_wires if h.protocol == "http" and h.direction == "outbound"]
    incoming = [h for h in half_wires if h.protocol == "http" and h.direction == "inbound"]
    matches: list[Match] = []
    exact_pairs: set[tuple[str, str]] = set()

    for source in outgoing:
        if not _http_exact_source_eligible(source):
            continue
        for target in incoming:
            match = _http_exact_pair(source, target)
            if match is None:
                continue
            exact_pairs.add((source.observed_identity_id, target.observed_identity_id))
            matches.append(match)

    for source in outgoing:
        if not _http_probable_source_eligible(source):
            continue
        for target in incoming:
            if (source.observed_identity_id, target.observed_identity_id) in exact_pairs:
                continue
            match = _http_probable_pair(source, target)
            if match is not None:
                matches.append(match)
    return sorted(matches, key=_match_sort_key)


def match_kafka(half_wires: Iterable[HalfWire]) -> list[Match]:
    publishers = [h for h in half_wires if h.protocol == "kafka" and h.direction == "publish"]
    consumers = [h for h in half_wires if h.protocol == "kafka" and h.direction == "consume"]
    matches: list[Match] = []
    for source in publishers:
        if not _is_exact_literal_topic(source):
            continue
        for target in consumers:
            match = _kafka_exact_pair(source, target)
            if match is not None:
                matches.append(match)
    return sorted(matches, key=_match_sort_key)


def analyze_matchability(
    half_wires: Iterable[HalfWire],
    matches: Iterable[Match],
    *,
    repository_ids: Iterable[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Explain input transport coverage and why unmatched half-wires did not form edges.

    This is diagnostic projection owned by the same matching module as edge matching.
    It never creates an edge and it does not add fallback matching rules.
    """
    rows = list(half_wires)
    match_rows = list(matches)
    repositories = sorted(set(str(value) for value in repository_ids))
    matched_ids = {
        half_wire.observed_identity_id
        for match in match_rows
        for half_wire in (match.source, match.target)
    }

    indexes = _build_matchability_indexes(rows)
    unmatched_details: list[dict[str, object]] = []
    for row in rows:
        if row.observed_identity_id in matched_ids:
            continue
        detail = _unmatched_detail(row, indexes)
        unmatched_details.append(detail)
    unmatched_details.sort(
        key=lambda row: (
            str(row.get("repository_id", "")),
            str(row.get("protocol", "")),
            str(row.get("direction", "")),
            str(row.get("observed_identity_id", "")),
        )
    )

    reason_counter = Counter(
        (str(row["protocol"]), str(row["direction"]), str(row["reason"]))
        for row in unmatched_details
    )
    unmatched_reason_counts = [
        {"protocol": protocol, "direction": direction, "reason": reason, "count": count}
        for (protocol, direction, reason), count in sorted(reason_counter.items())
    ]

    repository_stats = _repository_stats(repositories, rows, matched_ids)
    status_counts = Counter((row.protocol, row.direction, row.path_status or "") for row in rows)
    identity_kind_counts = Counter(
        (row.protocol, row.direction, row.transport_identity_kind or "") for row in rows
    )

    analysis = {
        "matching_owner": "repository_topology.matching",
        "matching_policy": {
            "http_exact": "exact method + exact resolved single path across different repositories",
            "http_probable": "ambiguous declared config + exact method + terminal path segment + request-field Jaccard threshold",
            "http_probable_request_field_jaccard_threshold": HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD,
            "kafka_exact": "same resolved single literal topic across different repositories",
            "fallback_matching": "forbidden",
        },
        "summary": {
            "repository_count": len(repositories),
            "repository_with_half_wire_count": sum(1 for row in repository_stats if row["half_wire_count"]),
            "repository_without_half_wire_count": sum(1 for row in repository_stats if not row["half_wire_count"]),
            "half_wire_count": len(rows),
            "observed_occurrence_count": sum(row.occurrence_count for row in rows),
            "matched_half_wire_count": len(matched_ids),
            "unmatched_half_wire_count": len(unmatched_details),
            "match_count": len(match_rows),
            "http_half_wire_count": sum(1 for row in rows if row.protocol == "http"),
            "http_inbound_count": sum(1 for row in rows if row.protocol == "http" and row.direction == "inbound"),
            "http_outbound_count": sum(1 for row in rows if row.protocol == "http" and row.direction == "outbound"),
            "http_exact_eligible_inbound_count": sum(1 for row in rows if _http_exact_target_eligible(row)),
            "http_exact_eligible_outbound_count": sum(1 for row in rows if _http_exact_source_eligible(row)),
            "http_probable_eligible_outbound_count": sum(1 for row in rows if _http_probable_source_eligible(row)),
            "kafka_half_wire_count": sum(1 for row in rows if row.protocol == "kafka"),
            "kafka_publish_count": sum(1 for row in rows if row.protocol == "kafka" and row.direction == "publish"),
            "kafka_consume_count": sum(1 for row in rows if row.protocol == "kafka" and row.direction == "consume"),
            "kafka_exact_eligible_publish_count": sum(
                1 for row in rows if row.direction == "publish" and _is_exact_literal_topic(row)
            ),
            "kafka_exact_eligible_consume_count": sum(
                1 for row in rows if row.direction == "consume" and _is_exact_literal_topic(row)
            ),
        },
        "identity_status_counts": [
            {
                "protocol": protocol,
                "direction": direction,
                "identity_status": status,
                "count": count,
            }
            for (protocol, direction, status), count in sorted(status_counts.items())
        ],
        "transport_identity_kind_counts": [
            {
                "protocol": protocol,
                "direction": direction,
                "transport_identity_kind": kind,
                "count": count,
            }
            for (protocol, direction, kind), count in sorted(identity_kind_counts.items())
            if protocol == "kafka"
        ],
        "unmatched_reason_counts": unmatched_reason_counts,
        "repository_stats": repository_stats,
    }
    return analysis, unmatched_details


def _http_exact_source_eligible(source: HalfWire) -> bool:
    return (
        source.protocol == "http"
        and source.direction == "outbound"
        and source.path_status == "resolved"
        and len(source.paths) == 1
    )


def _http_exact_target_eligible(target: HalfWire) -> bool:
    return (
        target.protocol == "http"
        and target.direction == "inbound"
        and target.path_status == "resolved"
        and len(target.paths) == 1
    )


def _http_probable_source_eligible(source: HalfWire) -> bool:
    return (
        source.protocol == "http"
        and source.direction == "outbound"
        and source.path_status == "ambiguous_declared_config"
        and bool(source.paths)
        and bool(source.request_field_names)
    )


def _http_exact_pair(source: HalfWire, target: HalfWire) -> Match | None:
    if not _http_exact_source_eligible(source) or not _http_exact_target_eligible(target):
        return None
    if source.repository_id == target.repository_id:
        return None
    if source.method != target.method:
        return None
    if source.paths[0] != target.paths[0]:
        return None
    return Match(
        source=source,
        target=target,
        classification="exact",
        claim_classification="strongly_supported_inference",
        confidence="high",
        matched_identity=target.paths[0],
        basis=(
            {"kind": "exact_method", "value": source.method},
            {"kind": "exact_path", "value": target.paths[0]},
        ),
    )


def _http_probable_pair(source: HalfWire, target: HalfWire) -> Match | None:
    if not _http_probable_source_eligible(source) or not _http_exact_target_eligible(target):
        return None
    if source.repository_id == target.repository_id:
        return None
    if source.method != target.method or not target.request_field_names:
        return None
    target_path = target.paths[0]
    terminal = _terminal_segment(target_path)
    source_terminal_candidates = [p for p in source.paths if _terminal_segment(p) == terminal]
    if not source_terminal_candidates:
        return None
    overlap = _jaccard(set(source.request_field_names), set(target.request_field_names))
    if overlap < HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD:
        return None
    return Match(
        source=source,
        target=target,
        classification="probable",
        claim_classification="probable_inference",
        confidence="medium_high",
        matched_identity=target_path,
        basis=(
            {"kind": "exact_method", "value": source.method},
            {"kind": "terminal_path_segment", "value": terminal, "source_candidates": source_terminal_candidates},
            {"kind": "request_field_name_overlap", "value": round(overlap, 6)},
            {"kind": "source_path_status", "value": source.path_status},
        ),
    )


def _kafka_exact_pair(source: HalfWire, target: HalfWire) -> Match | None:
    if source.direction != "publish" or target.direction != "consume":
        return None
    if source.repository_id == target.repository_id:
        return None
    if not _is_exact_literal_topic(source) or not _is_exact_literal_topic(target):
        return None
    if source.paths[0] != target.paths[0]:
        return None
    topic = source.paths[0]
    return Match(
        source=source,
        target=target,
        classification="exact",
        claim_classification="strongly_supported_inference",
        confidence="high",
        matched_identity=topic,
        basis=(
            {"kind": "exact_literal_topic", "value": topic},
        ),
    )


def _build_matchability_indexes(rows: list[HalfWire]) -> dict[str, object]:
    http_inbound = [row for row in rows if row.protocol == "http" and row.direction == "inbound"]
    http_outbound = [row for row in rows if row.protocol == "http" and row.direction == "outbound"]
    kafka_publish = [row for row in rows if row.protocol == "kafka" and row.direction == "publish"]
    kafka_consume = [row for row in rows if row.protocol == "kafka" and row.direction == "consume"]

    inbound_by_path: dict[str, list[HalfWire]] = defaultdict(list)
    inbound_by_terminal: dict[str, list[HalfWire]] = defaultdict(list)
    for row in http_inbound:
        if _http_exact_target_eligible(row):
            inbound_by_path[row.paths[0]].append(row)
            inbound_by_terminal[_terminal_segment(row.paths[0])].append(row)

    outbound_resolved_by_path: dict[str, list[HalfWire]] = defaultdict(list)
    outbound_ambiguous_by_terminal: dict[str, list[HalfWire]] = defaultdict(list)
    for row in http_outbound:
        if _http_exact_source_eligible(row):
            outbound_resolved_by_path[row.paths[0]].append(row)
        if row.path_status == "ambiguous_declared_config" and row.paths:
            for terminal in sorted({_terminal_segment(path) for path in row.paths}):
                outbound_ambiguous_by_terminal[terminal].append(row)

    kafka_publish_by_topic: dict[str, list[HalfWire]] = defaultdict(list)
    kafka_consume_by_topic: dict[str, list[HalfWire]] = defaultdict(list)
    for row in kafka_publish:
        if _is_exact_literal_topic(row):
            kafka_publish_by_topic[row.paths[0]].append(row)
    for row in kafka_consume:
        if _is_exact_literal_topic(row):
            kafka_consume_by_topic[row.paths[0]].append(row)

    return {
        "http_inbound": http_inbound,
        "http_outbound": http_outbound,
        "inbound_by_path": inbound_by_path,
        "inbound_by_terminal": inbound_by_terminal,
        "outbound_resolved_by_path": outbound_resolved_by_path,
        "outbound_ambiguous_by_terminal": outbound_ambiguous_by_terminal,
        "kafka_publish": kafka_publish,
        "kafka_consume": kafka_consume,
        "kafka_publish_by_topic": kafka_publish_by_topic,
        "kafka_consume_by_topic": kafka_consume_by_topic,
    }


def _unmatched_detail(row: HalfWire, indexes: dict[str, object]) -> dict[str, object]:
    if row.protocol == "http" and row.direction == "outbound":
        reason, detail = _http_outbound_unmatched_reason(row, indexes)
    elif row.protocol == "http" and row.direction == "inbound":
        reason, detail = _http_inbound_unmatched_reason(row, indexes)
    elif row.protocol == "kafka" and row.direction in {"publish", "consume"}:
        reason, detail = _kafka_unmatched_reason(row, indexes)
    else:
        reason, detail = "unsupported_half_wire_shape", {}

    return {
        "kind": "unmatched_half_wire",
        "repository_id": row.repository_id,
        "observed_identity_id": row.observed_identity_id,
        "protocol": row.protocol,
        "direction": row.direction,
        "method": row.method,
        "identity_status": row.path_status,
        "identities": list(row.paths),
        "transport_identity_kind": row.transport_identity_kind,
        "request_field_count": len(row.request_field_names),
        "response_field_count": len(row.response_field_names),
        "payload_field_count": len(row.payload_field_names),
        "occurrence_count": row.occurrence_count,
        "reason": reason,
        **detail,
    }


def _http_outbound_unmatched_reason(
    source: HalfWire, indexes: dict[str, object]
) -> tuple[str, dict[str, object]]:
    inbound_by_path = indexes["inbound_by_path"]
    inbound_by_terminal = indexes["inbound_by_terminal"]
    assert isinstance(inbound_by_path, defaultdict)
    assert isinstance(inbound_by_terminal, defaultdict)

    if _http_exact_source_eligible(source):
        same_path = list(inbound_by_path.get(source.paths[0], []))
        external_same_path = [row for row in same_path if row.repository_id != source.repository_id]
        external_exact = [row for row in external_same_path if row.method == source.method]
        if external_exact:
            return "internal_consistency_error_expected_exact_match", {"candidate_count": len(external_exact)}
        self_exact = [row for row in same_path if row.repository_id == source.repository_id and row.method == source.method]
        if self_exact:
            return "http_exact_counterpart_only_same_repository", {"candidate_count": len(self_exact)}
        if external_same_path:
            methods = sorted({str(row.method or "") for row in external_same_path})
            return "http_exact_method_mismatch", {
                "candidate_count": len(external_same_path),
                "candidate_methods": methods,
            }
        return "http_exact_no_inbound_same_path", {"candidate_count": 0}

    if source.path_status == "ambiguous_declared_config" and source.paths:
        if not source.request_field_names:
            return "http_probable_source_request_fields_missing", {"candidate_count": 0}
        terminals = sorted({_terminal_segment(path) for path in source.paths})
        terminal_candidates = {
            row.observed_identity_id: row
            for terminal in terminals
            for row in inbound_by_terminal.get(terminal, [])
            if row.repository_id != source.repository_id
        }
        candidates = list(terminal_candidates.values())
        if not candidates:
            return "http_probable_no_inbound_terminal_match", {"candidate_count": 0, "source_terminals": terminals}
        same_method = [row for row in candidates if row.method == source.method]
        if not same_method:
            return "http_probable_method_mismatch", {
                "candidate_count": len(candidates),
                "candidate_methods": sorted({str(row.method or "") for row in candidates}),
                "source_terminals": terminals,
            }
        with_fields = [row for row in same_method if row.request_field_names]
        if not with_fields:
            return "http_probable_target_request_fields_missing", {
                "candidate_count": len(same_method),
                "source_terminals": terminals,
            }
        overlaps = [
            _jaccard(set(source.request_field_names), set(row.request_field_names))
            for row in with_fields
        ]
        max_overlap = max(overlaps, default=0.0)
        if max_overlap < HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD:
            return "http_probable_request_field_overlap_below_threshold", {
                "candidate_count": len(with_fields),
                "max_request_field_overlap": round(max_overlap, 6),
                "required_request_field_overlap": HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD,
                "source_terminals": terminals,
            }
        return "internal_consistency_error_expected_probable_match", {
            "candidate_count": len(with_fields),
            "max_request_field_overlap": round(max_overlap, 6),
        }

    if source.path_status == "resolved" and len(source.paths) != 1:
        return "http_exact_source_not_single_resolved_path", {"candidate_count": 0}
    if source.path_status == "ambiguous_declared_config" and not source.paths:
        return "http_probable_source_has_no_path_candidates", {"candidate_count": 0}
    return "http_outbound_identity_not_matchable", {"candidate_count": 0}


def _http_inbound_unmatched_reason(
    target: HalfWire, indexes: dict[str, object]
) -> tuple[str, dict[str, object]]:
    if not _http_exact_target_eligible(target):
        return "http_inbound_identity_not_single_resolved_path", {"candidate_count": 0}

    outbound_resolved_by_path = indexes["outbound_resolved_by_path"]
    outbound_ambiguous_by_terminal = indexes["outbound_ambiguous_by_terminal"]
    assert isinstance(outbound_resolved_by_path, defaultdict)
    assert isinstance(outbound_ambiguous_by_terminal, defaultdict)

    same_path = list(outbound_resolved_by_path.get(target.paths[0], []))
    external_same_path = [row for row in same_path if row.repository_id != target.repository_id]
    external_exact = [row for row in external_same_path if row.method == target.method]
    if external_exact:
        return "internal_consistency_error_expected_exact_match", {"candidate_count": len(external_exact)}
    self_exact = [row for row in same_path if row.repository_id == target.repository_id and row.method == target.method]
    if self_exact:
        return "http_exact_counterpart_only_same_repository", {"candidate_count": len(self_exact)}
    if external_same_path:
        return "http_inbound_exact_method_mismatch", {
            "candidate_count": len(external_same_path),
            "candidate_methods": sorted({str(row.method or "") for row in external_same_path}),
        }

    terminal = _terminal_segment(target.paths[0])
    ambiguous = [
        row
        for row in outbound_ambiguous_by_terminal.get(terminal, [])
        if row.repository_id != target.repository_id
    ]
    if ambiguous:
        same_method = [row for row in ambiguous if row.method == target.method]
        if not same_method:
            return "http_inbound_probable_method_mismatch", {
                "candidate_count": len(ambiguous),
                "candidate_methods": sorted({str(row.method or "") for row in ambiguous}),
                "target_terminal": terminal,
            }
        source_with_fields = [row for row in same_method if row.request_field_names]
        if not source_with_fields:
            return "http_inbound_probable_source_request_fields_missing", {
                "candidate_count": len(same_method),
                "target_terminal": terminal,
            }
        if not target.request_field_names:
            return "http_inbound_probable_target_request_fields_missing", {
                "candidate_count": len(source_with_fields),
                "target_terminal": terminal,
            }
        overlaps = [
            _jaccard(set(row.request_field_names), set(target.request_field_names))
            for row in source_with_fields
        ]
        max_overlap = max(overlaps, default=0.0)
        if max_overlap < HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD:
            return "http_inbound_probable_request_field_overlap_below_threshold", {
                "candidate_count": len(source_with_fields),
                "max_request_field_overlap": round(max_overlap, 6),
                "required_request_field_overlap": HTTP_PROBABLE_REQUEST_FIELD_JACCARD_THRESHOLD,
                "target_terminal": terminal,
            }
        return "internal_consistency_error_expected_probable_match", {
            "candidate_count": len(source_with_fields),
            "max_request_field_overlap": round(max_overlap, 6),
        }

    return "http_inbound_no_outbound_candidate", {"candidate_count": 0}


def _kafka_unmatched_reason(
    row: HalfWire, indexes: dict[str, object]
) -> tuple[str, dict[str, object]]:
    if row.path_status != "resolved":
        return "kafka_identity_not_resolved", {"candidate_count": 0}
    if row.transport_identity_kind != "literal":
        return "kafka_identity_not_literal", {"candidate_count": 0}
    if len(row.paths) != 1 or not row.paths[0]:
        return "kafka_literal_identity_not_single_topic", {"candidate_count": 0}

    topic = row.paths[0]
    if row.direction == "publish":
        counterpart_index = indexes["kafka_consume_by_topic"]
        no_counterpart_reason = "kafka_publish_no_consumer_same_literal_topic"
    else:
        counterpart_index = indexes["kafka_publish_by_topic"]
        no_counterpart_reason = "kafka_consume_no_publisher_same_literal_topic"
    assert isinstance(counterpart_index, defaultdict)
    candidates = list(counterpart_index.get(topic, []))
    external = [candidate for candidate in candidates if candidate.repository_id != row.repository_id]
    if external:
        return "internal_consistency_error_expected_kafka_match", {"candidate_count": len(external)}
    same_repo = [candidate for candidate in candidates if candidate.repository_id == row.repository_id]
    if same_repo:
        return "kafka_counterpart_only_same_repository", {"candidate_count": len(same_repo)}
    return no_counterpart_reason, {"candidate_count": 0}


def _repository_stats(
    repository_ids: list[str], rows: list[HalfWire], matched_ids: set[str]
) -> list[dict[str, object]]:
    counters: dict[str, Counter[str]] = {repository_id: Counter() for repository_id in repository_ids}
    for row in rows:
        counter = counters.setdefault(row.repository_id, Counter())
        counter["half_wire_count"] += 1
        counter[f"{row.protocol}_{row.direction}_count"] += 1
        if row.observed_identity_id in matched_ids:
            counter["matched_half_wire_count"] += 1
        else:
            counter["unmatched_half_wire_count"] += 1
    return [
        {
            "repository_id": repository_id,
            "half_wire_count": counters[repository_id]["half_wire_count"],
            "http_inbound_count": counters[repository_id]["http_inbound_count"],
            "http_outbound_count": counters[repository_id]["http_outbound_count"],
            "kafka_publish_count": counters[repository_id]["kafka_publish_count"],
            "kafka_consume_count": counters[repository_id]["kafka_consume_count"],
            "matched_half_wire_count": counters[repository_id]["matched_half_wire_count"],
            "unmatched_half_wire_count": counters[repository_id]["unmatched_half_wire_count"],
        }
        for repository_id in repository_ids
    ]


def _is_exact_literal_topic(half_wire: HalfWire) -> bool:
    return (
        half_wire.path_status == "resolved"
        and half_wire.transport_identity_kind == "literal"
        and len(half_wire.paths) == 1
        and bool(half_wire.paths[0])
    )


def _terminal_segment(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _match_sort_key(m: Match):
    return (
        m.source.repository_id,
        m.target.repository_id,
        m.source.protocol,
        m.source.method or "",
        m.matched_identity,
        0 if m.classification == "exact" else 1,
        m.source.observed_identity_id,
        m.target.observed_identity_id,
    )
