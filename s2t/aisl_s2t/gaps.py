from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from .primary_source import PrimarySourceDecision


FRAMEWORK_EVIDENCE_GAP = "FRAMEWORK_EVIDENCE_GAP"
MISSING_RELATION_BRIDGE = "MISSING_RELATION_BRIDGE"
UNRESOLVED_PLACEHOLDER = "UNRESOLVED_PLACEHOLDER"
ENVIRONMENT_AMBIGUITY = "ENVIRONMENT_AMBIGUITY"
BOUNDED_PRODUCER_AMBIGUITY = "BOUNDED_PRODUCER_AMBIGUITY"
CONTROL_DEPENDENCY = "CONTROL_DEPENDENCY"
CONSUMER_CONVENTION = "CONSUMER_CONVENTION"
TARGET_ONLY_NON_TABLE_SOURCE = "TARGET_ONLY_NON_TABLE_SOURCE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

_GAP_TYPES = {
    FRAMEWORK_EVIDENCE_GAP,
    MISSING_RELATION_BRIDGE,
    UNRESOLVED_PLACEHOLDER,
    ENVIRONMENT_AMBIGUITY,
    BOUNDED_PRODUCER_AMBIGUITY,
    CONTROL_DEPENDENCY,
    CONSUMER_CONVENTION,
    TARGET_ONLY_NON_TABLE_SOURCE,
    INSUFFICIENT_EVIDENCE,
}


@dataclass(frozen=True)
class TypedGap:
    gap_id: str
    gap_type: str
    target_relation: str
    target_column: str
    basis: str
    candidate_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_gap_ids: tuple[str, ...] = ()
    source_gap_kinds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type,
            "target_relation": self.target_relation,
            "target_column": self.target_column,
            "basis": self.basis,
            "candidate_ids": list(self.candidate_ids),
            "evidence_refs": list(self.evidence_refs),
            "source_gap_ids": list(self.source_gap_ids),
            "source_gap_kinds": list(self.source_gap_kinds),
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_value(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _contains_placeholder(value: Any) -> bool:
    text = _text(value)
    return "${" in text or "{{" in text or "%(" in text


def _candidate_identity(item: Any) -> str:
    if isinstance(item, Mapping):
        for key in ("candidate_id", "producer_id", "relation_id", "id", "relation_name", "table", "name"):
            value = _text(item.get(key))
            if value:
                return value
        return ""
    return _text(item)


def _candidate_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        values: list[Any] = list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
    else:
        return ()
    return tuple(sorted({_candidate_identity(item) for item in values if _candidate_identity(item)}))


def _candidate_ids_from_evidence(evidence: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str, ...]:
    candidate_sets: list[tuple[str, ...]] = []
    for key in ("producer_resolution_candidates", "driver_relation_candidates", "candidate_relations"):
        values = _candidate_values(evidence.get(key))
        if values:
            candidate_sets.append(values)
    for key in ("driver_relation_candidates", "driver_relation_candidates_json"):
        values = _candidate_values(_json_value(row.get(key), row.get(key)))
        if values:
            candidate_sets.append(values)
    if not candidate_sets:
        return ()
    return tuple(sorted({value for group in candidate_sets for value in group}))


def _evidence_refs(row: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[str, ...]:
    refs: set[str] = set()
    for key in (
        "gap_id", "mapping_id", "value_mapping_id", "local_lineage_id", "root_projection_id",
        "source_mapping_id", "frontier_usage_id", "source_producer_id", "source_sql_relation_id",
    ):
        value = _text(row.get(key)) or _text(evidence.get(key))
        if value:
            refs.add(f"{key}:{value}")
    return tuple(sorted(refs))


def _stable_gap_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "s2t-gap-" + hashlib.sha256(encoded).hexdigest()[:24]


def _make_gap(
    *,
    gap_type: str,
    target_relation: str,
    target_column: str,
    basis: str,
    candidate_ids: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    source_gap_ids: Iterable[str] = (),
    source_gap_kinds: Iterable[str] = (),
) -> TypedGap:
    if gap_type not in _GAP_TYPES:
        raise ValueError(f"unsupported gap type: {gap_type}")
    candidates = tuple(sorted({_text(value) for value in candidate_ids if _text(value)}))
    refs = tuple(sorted({_text(value) for value in evidence_refs if _text(value)}))
    gap_ids = tuple(sorted({_text(value) for value in source_gap_ids if _text(value)}))
    gap_kinds = tuple(sorted({_text(value) for value in source_gap_kinds if _text(value)}))
    identity = {
        "gap_type": gap_type,
        "target_relation": _text(target_relation),
        "target_column": _text(target_column),
        "basis": _text(basis),
        "candidate_ids": candidates,
        "source_gap_ids": gap_ids,
    }
    return TypedGap(
        gap_id=_stable_gap_id(identity),
        gap_type=gap_type,
        target_relation=_text(target_relation),
        target_column=_text(target_column),
        basis=_text(basis),
        candidate_ids=candidates,
        evidence_refs=refs,
        source_gap_ids=gap_ids,
        source_gap_kinds=gap_kinds,
    )



def _column_usage_context_index(
    column_usage_contexts: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in column_usage_contexts:
        context = item.get("context") if isinstance(item.get("context"), Mapping) else item
        if not isinstance(context, Mapping):
            continue
        usage = context.get("usage")
        if not isinstance(usage, Mapping):
            continue
        usage_id = _text(usage.get("sql_column_usage_id"))
        if usage_id:
            result[usage_id] = context
    return result


def _ambiguous_usage_survivors(
    context: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return mechanically possible scope relations for one ambiguous usage.

    This is deliberately narrower than source resolution. It mirrors only the
    negative-evidence rule already exposed by public SQL context: a relation can be
    excluded when its output contract is complete and the referenced column is
    absent. Partial/unknown contracts always survive. No surviving relation is
    selected or promoted to an S2T source here.
    """
    usage = context.get("usage")
    if not isinstance(usage, Mapping):
        return (), ()
    if _text(usage.get("resolution_basis")) != "ambiguous_unqualified":
        return (), ()
    if _text(usage.get("relation_id")):
        return (), ()
    column = _text(usage.get("column_name")).casefold()
    scope_id = _text(usage.get("scope_id"))
    if not column or not scope_id:
        return (), ()
    scope = context.get("scope")
    if isinstance(scope, Mapping):
        published_scope_id = _text(scope.get("sql_select_scope_id"))
        if published_scope_id and published_scope_id != scope_id:
            return (), ()

    survivors: set[str] = set()
    excluded: set[str] = set()
    relations = context.get("scope_relations")
    if not isinstance(relations, Sequence) or isinstance(relations, (str, bytes)):
        return (), ()
    for relation in relations:
        if not isinstance(relation, Mapping):
            continue
        relation_id = _text(relation.get("sql_relation_id"))
        if not relation_id:
            continue
        status = _text(relation.get("output_contract_status"))
        outputs_raw = relation.get("output_columns")
        outputs = {
            _text(value).casefold()
            for value in outputs_raw
            if _text(value)
        } if isinstance(outputs_raw, Sequence) and not isinstance(outputs_raw, (str, bytes)) else set()
        if status == "complete" and column not in outputs:
            excluded.add(relation_id)
        else:
            survivors.add(relation_id)
    return tuple(sorted(survivors)), tuple(sorted(excluded))


def _usage_id_for_gap(
    row: Mapping[str, Any],
    evidence: Mapping[str, Any],
    linked_mapping: Mapping[str, Any] | None,
) -> str:
    for source in (evidence, row, linked_mapping or {}):
        for key in (
            "frontier_usage_id",
            "sql_column_usage_id",
            "immediate_source_column_usage_id",
            "source_sql_column_usage_id",
            "source_usage_id",
        ):
            value = _text(source.get(key))
            if value:
                return value
    return ""

def classify_public_mapping_gaps(
    mapping_gaps: Iterable[Mapping[str, Any]],
    *,
    mapping_rows: Iterable[Mapping[str, Any]] = (),
    column_usage_contexts: Iterable[Mapping[str, Any]] = (),
    environment_semantic_decisions: Iterable[Mapping[str, Any]] = (),
    max_bounded_candidates: int = 5,
) -> list[TypedGap]:
    """Classify public AISL mapping gaps without generating or ranking candidates.

    Candidate identities are accepted only from public mapping/gap evidence or from
    a supplied public ``get_sql_column_usage_context`` response. For an unresolved
    ``ambiguous_unqualified`` usage, complete output contracts may exclude relations
    that provably do not expose the referenced column; partial/unknown contracts
    survive. The classifier never selects a survivor and never marks a gap LLM-eligible;
    eligibility is a later Task-23 phase.
    """

    mappings_by_id: dict[str, Mapping[str, Any]] = {}
    for row in mapping_rows:
        for key in ("mapping_id", "value_mapping_id"):
            identity = _text(row.get(key))
            if identity:
                mappings_by_id[identity] = row

    usage_context_by_id = _column_usage_context_index(column_usage_contexts)
    resolved_environment_keys: set[tuple[str, str, str, str]] = set()
    for item in environment_semantic_decisions:
        key = item.get("semantic_key") or ()
        if (
            isinstance(key, Sequence)
            and not isinstance(key, (str, bytes))
            and len(key) == 4
            and _text(item.get("status")) == "resolved"
            and _text(item.get("resolved_source_relation"))
        ):
            resolved_environment_keys.add(tuple(_text(value) for value in key))

    typed: list[TypedGap] = []
    for row in mapping_gaps:
        evidence = _json_value(row.get("evidence_json") or row.get("evidence"), {})
        if not isinstance(evidence, Mapping):
            evidence = {}
        linked_mapping = mappings_by_id.get(_text(evidence.get("source_mapping_id")))
        merged_row: dict[str, Any] = dict(linked_mapping or {})
        merged_row.update(row)
        target_relation = _text(row.get("workflow_target_logical_name") or row.get("target_relation") or merged_row.get("workflow_target_logical_name"))
        target_column = _text(row.get("target_column") or merged_row.get("target_column"))
        gap_kind = _text(row.get("gap_kind") or row.get("type"))
        basis = _text(row.get("mapping_basis") or row.get("basis"))
        candidate_ids = _candidate_ids_from_evidence(evidence, merged_row)
        refs = _evidence_refs(row, evidence)
        usage_id = _usage_id_for_gap(row, evidence, linked_mapping)
        usage_context = usage_context_by_id.get(usage_id) if usage_id else None
        usage_survivors: tuple[str, ...] = ()
        usage_excluded: tuple[str, ...] = ()
        if usage_context is not None:
            usage_survivors, usage_excluded = _ambiguous_usage_survivors(usage_context)
            if usage_id:
                refs = tuple(sorted({*refs, f"sql_column_usage_id:{usage_id}"}))
            refs = tuple(sorted({
                *refs,
                *(f"candidate_relation_id:{value}" for value in usage_survivors),
                *(f"excluded_relation_id:{value}" for value in usage_excluded),
            }))

        serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if gap_kind == "source_relation_placeholder_unresolved":
            environment_key = (
                target_relation,
                target_column,
                _text(evidence.get("source_relation_name")),
                _text(evidence.get("source_column")),
            )
            if all(environment_key) and environment_key in resolved_environment_keys:
                continue
        if "placeholder" in gap_kind.casefold() or _contains_placeholder(serialized):
            gap_type = UNRESOLVED_PLACEHOLDER
            typed_basis = basis or "public_gap_contains_unresolved_placeholder_evidence"
        elif gap_kind == "intermediate_producer_ambiguous":
            concrete_candidates = tuple(value for value in candidate_ids if not _contains_placeholder(value))
            if 2 <= len(concrete_candidates) <= max_bounded_candidates and len(concrete_candidates) == len(candidate_ids):
                gap_type = BOUNDED_PRODUCER_AMBIGUITY
                typed_basis = "public_intermediate_producer_ambiguity_with_bounded_candidate_set"
            else:
                gap_type = INSUFFICIENT_EVIDENCE
                typed_basis = "producer_ambiguity_not_bounded_by_current_public_evidence"
        elif usage_survivors:
            concrete_candidates = tuple(value for value in usage_survivors if not _contains_placeholder(value))
            if 2 <= len(concrete_candidates) <= max_bounded_candidates and len(concrete_candidates) == len(usage_survivors):
                gap_type = BOUNDED_PRODUCER_AMBIGUITY
                candidate_ids = concrete_candidates
                typed_basis = "public_ambiguous_unqualified_usage_with_bounded_surviving_relation_set"
            else:
                gap_type = INSUFFICIENT_EVIDENCE
                candidate_ids = usage_survivors
                typed_basis = "ambiguous_unqualified_usage_not_bounded_by_current_public_context"
        elif gap_kind in {"missing_relation_bridge", "relation_materialization_bridge_missing"}:
            gap_type = MISSING_RELATION_BRIDGE
            typed_basis = basis or "public_gap_explicitly_identifies_missing_relation_bridge"
        elif gap_kind in {"framework_evidence_gap", "mechanically_observable_fact_not_published"}:
            gap_type = FRAMEWORK_EVIDENCE_GAP
            typed_basis = basis or "public_gap_explicitly_identifies_framework_evidence_gap"
        elif gap_kind in {"control_dependency", "query_control_dependency"}:
            gap_type = CONTROL_DEPENDENCY
            typed_basis = basis or "public_gap_identifies_control_dependency"
        elif gap_kind in {"target_only_non_table_source", "non_table_source"}:
            gap_type = TARGET_ONLY_NON_TABLE_SOURCE
            typed_basis = basis or "public_gap_identifies_non_table_source"
        else:
            gap_type = INSUFFICIENT_EVIDENCE
            typed_basis = basis or (f"unclassified_public_gap:{gap_kind}" if gap_kind else "public_gap_without_bounded_resolution_evidence")

        typed.append(_make_gap(
            gap_type=gap_type,
            target_relation=target_relation,
            target_column=target_column,
            basis=typed_basis,
            candidate_ids=candidate_ids,
            evidence_refs=refs,
            source_gap_ids=[_text(row.get("gap_id"))],
            source_gap_kinds=[gap_kind],
        ))
    return _dedupe_gaps(typed)


def classify_primary_source_residuals(
    decisions: Iterable[PrimarySourceDecision],
    *,
    environment_semantic_decisions: Iterable[Mapping[str, Any]] = (),
) -> list[TypedGap]:
    environment_by_key: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for item in environment_semantic_decisions:
        key = item.get("semantic_key") or ()
        if isinstance(key, Sequence) and not isinstance(key, (str, bytes)) and len(key) == 4:
            environment_by_key[tuple(_text(value) for value in key)] = item

    typed: list[TypedGap] = []
    for decision in decisions:
        if decision.status == "resolved":
            continue
        if decision.status == "template":
            typed.append(_make_gap(
                gap_type=UNRESOLVED_PLACEHOLDER,
                target_relation=decision.target_relation,
                target_column=decision.target_column,
                basis="primary_source_relation_template_preserved_literal",
                evidence_refs=[
                    f"mapping_id:{value}" for value in decision.mapping_ids
                ],
            ))
            continue
        env_statuses: set[str] = set()
        env_gap_ids: set[str] = set()
        for template in decision.primary_templates:
            key = (decision.target_relation, decision.target_column, template, decision.source_column)
            item = environment_by_key.get(key)
            if item:
                env_statuses.add(_text(item.get("status")))
                env_gap_ids.update(_text(value) for value in item.get("gap_ids") or () if _text(value))
        if "ambiguous" in env_statuses:
            gap_type = ENVIRONMENT_AMBIGUITY
            basis = "deterministic_environment_policy_left_multiple_matching_candidates"
        elif any(_contains_placeholder(value) for value in decision.primary_templates):
            gap_type = UNRESOLVED_PLACEHOLDER
            basis = "primary_source_relation_template_not_deterministically_resolved"
        else:
            gap_type = INSUFFICIENT_EVIDENCE
            basis = decision.basis or "primary_source_unresolved"
        typed.append(_make_gap(
            gap_type=gap_type,
            target_relation=decision.target_relation,
            target_column=decision.target_column,
            basis=basis,
            evidence_refs=[*(f"mapping_id:{value}" for value in decision.mapping_ids), *(f"environment_gap_id:{value}" for value in env_gap_ids)],
            source_gap_ids=env_gap_ids,
        ))
    return _dedupe_gaps(typed)


def classify_consumer_convention_residuals(
    mapping_rows: Iterable[Mapping[str, Any]],
    *,
    resolved_primary_targets: Iterable[tuple[str, str]],
) -> list[TypedGap]:
    """Classify source-role residuals after primary-source policy has run.

    Lookup/enrichment-only evidence becomes a consumer-convention notice with a blank
    primary T-src. Driver-candidate/unknown evidence stays insufficient rather than
    being promoted to a source.
    """

    resolved = {(_text(a), _text(b)) for a, b in resolved_primary_targets}
    roles_by_target: dict[tuple[str, str], set[str]] = {}
    refs_by_target: dict[tuple[str, str], set[str]] = {}
    for row in mapping_rows:
        target = (
            _text(row.get("workflow_target_logical_name") or row.get("target_relation")),
            _text(row.get("target_column")),
        )
        if not all(target) or target in resolved:
            continue
        roles_by_target.setdefault(target, set()).add(_text(row.get("source_relation_role")) or "unknown")
        identity = _text(row.get("mapping_id") or row.get("value_mapping_id"))
        if identity:
            refs_by_target.setdefault(target, set()).add(f"mapping_id:{identity}")

    typed: list[TypedGap] = []
    for (target_relation, target_column), roles in sorted(roles_by_target.items()):
        nonempty = {role for role in roles if role}
        if nonempty and nonempty.issubset({"enrichment", "lookup"}):
            typed.append(_make_gap(
                gap_type=CONSUMER_CONVENTION,
                target_relation=target_relation,
                target_column=target_column,
                basis="lookup_or_enrichment_observed_without_proven_primary_source",
                evidence_refs=refs_by_target.get((target_relation, target_column), ()),
            ))
        elif "driver_candidate" in nonempty or "unknown" in nonempty:
            typed.append(_make_gap(
                gap_type=INSUFFICIENT_EVIDENCE,
                target_relation=target_relation,
                target_column=target_column,
                basis="candidate_or_unknown_source_role_not_promoted_to_primary_source",
                evidence_refs=refs_by_target.get((target_relation, target_column), ()),
            ))
    return _dedupe_gaps(typed)


def _dedupe_gaps(gaps: Iterable[TypedGap]) -> list[TypedGap]:
    by_identity: dict[tuple[Any, ...], TypedGap] = {}
    for gap in gaps:
        key = (
            gap.gap_type,
            gap.target_relation,
            gap.target_column,
            gap.basis,
            gap.candidate_ids,
        )
        current = by_identity.get(key)
        if current is None:
            by_identity[key] = gap
            continue
        by_identity[key] = _make_gap(
            gap_type=gap.gap_type,
            target_relation=gap.target_relation,
            target_column=gap.target_column,
            basis=gap.basis,
            candidate_ids=gap.candidate_ids,
            evidence_refs=(*current.evidence_refs, *gap.evidence_refs),
            source_gap_ids=(*current.source_gap_ids, *gap.source_gap_ids),
            source_gap_kinds=(*current.source_gap_kinds, *gap.source_gap_kinds),
        )
    return sorted(
        by_identity.values(),
        key=lambda item: (item.target_relation, item.target_column, item.gap_type, item.candidate_ids, item.gap_id),
    )


def combine_typed_gaps(*groups: Iterable[TypedGap]) -> list[TypedGap]:
    return _dedupe_gaps(item for group in groups for item in group)
