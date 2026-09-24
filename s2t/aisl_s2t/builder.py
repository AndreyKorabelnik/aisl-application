from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .gaps import (
    TypedGap,
    classify_consumer_convention_residuals,
    classify_primary_source_residuals,
    classify_public_mapping_gaps,
    combine_typed_gaps,
)
from .primary_source import PrimarySourceDecision, collapse_primary_sources


S2T_COLUMNS = (
    "T-trg-platform",
    "T-trg-instance",
    "T-trg-schema",
    "T-trg",
    "UserName",
    "T-trg-f",
    "target_data_relevance",
    "target_data_hist",
    "target_data_freq",
    "T-src-platform",
    "T-src-instance",
    "T-src-schema",
    "T-src",
    "T-src-main",
    "T-src-f-name",
    "T-src-f",
    "T-src-join",
    "T-src-join-on",
    "T-src-where",
    "T-src-group",
    "T-k",
    "T-hist-type",
    "T-hist-role",
    "codeDatamart",
    "Datamart.description_source",
    "Table.description_source",
)

S2T_DESCRIPTIONS = (
    "Наименование платформы где лежит целевая таблица",
    "Наименование инстанса, где лежит таблица-приемник",
    "Наименование схемы приемника",
    "Наименование таблицы приемника",
    "Ответственный за конкретную таблицу (почта в домене Альфа)",
    "Наименование поля приемника\n*рекомендовано к заполнению, обязательно для заполнения в случае связи 1:1",
    "Актуальность данных(T-N, актуальность данных в таблице)  ",
    "Историчность(дата начала расчета данных в таблице)  ",
    "Частота расчёта таблицы  ",
    "Наименование платформы где лежит таблица-источник",
    "Наименование инстанса, где лежит таблица-источник",
    "Наименование схемы источника",
    "Наименование таблицы источника",
    "Наименование главной таблицы",
    "Наименование поля источника\n*рекомендовано к заполнению, обязательно для заполнения в случае связи 1:1",
    "Трансформация поля источника",
    "Дополнительная таблица-источник",
    "Условия соединения с дополнительной таблицей",
    "Условия фильтрации исходного набора",
    "Группировка",
    "K-таблица",
    "СОД",
    "Роль в истории",
    "ID Витрины",
    "Источник расчёта(Бизнес-описание источников расчета на уровне витрин)  ",
    "Источник расчёта(Бизнес-описание источников расчета на уровне таблиц)  ",
)


@dataclass(frozen=True)
class RowAudit:
    row_id: str
    target_relation: str
    target_column: str
    source_relation: str | None
    source_column: str | None
    basis: str
    mapping_ids: tuple[str, ...]
    primary_templates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "target_relation": self.target_relation,
            "target_column": self.target_column,
            "source_relation": self.source_relation,
            "source_column": self.source_column,
            "basis": self.basis,
            "mapping_ids": list(self.mapping_ids),
            "primary_templates": list(self.primary_templates),
        }


@dataclass(frozen=True)
class BuildResult:
    rows: tuple[tuple[str, ...], ...]
    row_audit: tuple[RowAudit, ...]
    gaps: tuple[TypedGap, ...]
    primary_source_decisions: tuple[PrimarySourceDecision, ...]

    def audit_payload(self, *, system_id: str = "", revision_id: str = "") -> dict[str, Any]:
        counts_by_type: dict[str, int] = {}
        for gap in self.gaps:
            counts_by_type[gap.gap_type] = counts_by_type.get(gap.gap_type, 0) + 1
        return {
            "schema_version": "aisl_s2t_deterministic_audit/v1",
            "system_id": system_id or None,
            "revision_id": revision_id or None,
            "counts": {
                "deterministic_rows": len(self.rows),
                "row_audit_records": len(self.row_audit),
                "typed_gaps": len(self.gaps),
                "typed_gaps_by_type": dict(sorted(counts_by_type.items())),
                "primary_source_decisions": len(self.primary_source_decisions),
                "resolved_primary_source_decisions": sum(1 for item in self.primary_source_decisions if item.status == "resolved"),
                "unresolved_primary_source_decisions": sum(1 for item in self.primary_source_decisions if item.status != "resolved"),
            },
            "row_audit": [item.to_dict() for item in self.row_audit],
            "gaps": [item.to_dict() for item in self.gaps],
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _target_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        _text(row.get("workflow_target_logical_name") or row.get("target_relation") or row.get("target")),
        _text(row.get("target_column") or row.get("target_field")),
    )


def _relation_parts(relation: str) -> tuple[str, str]:
    """Split an already-published relation identity into schema/table presentation.

    This is formatting only. It does not infer a schema: unqualified relations keep
    schema blank, while qualified identities split at the final dot.
    """
    text = _text(relation)
    if not text:
        return "", ""
    if "." not in text:
        return "", text
    schema, table = text.rsplit(".", 1)
    return schema, table


def _metadata_index(target_fields: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in target_fields:
        key = _target_key(item)
        if all(key):
            result[key] = item
    return result


def _exact_linked_expressions(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return only explicitly linked, resolved, non-direct target expressions.

    The builder deliberately does not reinterpret raw SQL text or guess whether a
    root expression is direct. Callers may pass compact public-tool expression rows
    through ``linked_target_expressions``/``target_expressions`` or exact single
    ``target_expression`` + ``target_expression_kind`` fields.
    """
    candidates: list[Mapping[str, Any]] = []
    for key in ("linked_target_expressions", "target_expressions"):
        value = row.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            candidates.extend(item for item in value if isinstance(item, Mapping))
    if row.get("target_expression") not in (None, ""):
        candidates.append({
            "expression": row.get("target_expression"),
            "expression_kind": row.get("target_expression_kind"),
            "resolution_status": row.get("target_expression_status") or "resolved",
        })

    expressions: set[str] = set()
    for item in candidates:
        expression = _text(item.get("expression"))
        kind = _text(item.get("expression_kind"))
        status = _text(item.get("resolution_status") or item.get("status") or "resolved")
        if expression and status == "resolved" and kind and kind != "direct_column":
            expressions.add(expression)
    return tuple(sorted(expressions))


def _expressions_for_decision(
    decision: PrimarySourceDecision,
    mapping_rows_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    expressions: set[str] = set()
    for mapping_id in decision.mapping_ids:
        row = mapping_rows_by_id.get(mapping_id)
        if row:
            expressions.update(_exact_linked_expressions(row))
    return tuple(sorted(expressions))




def _observed_source_column_for_decision(
    decision: PrimarySourceDecision,
    mapping_rows_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    columns = {
        _text(row.get("source_sql_column") or row.get("immediate_source_column"))
        for mapping_id in decision.mapping_ids
        for row in [mapping_rows_by_id.get(mapping_id) or {}]
        if _text(row.get("source_sql_column") or row.get("immediate_source_column"))
    }
    if len(columns) == 1:
        return next(iter(columns))
    return ""

def _base_row(target_relation: str, target_column: str, metadata: Mapping[str, Any] | None) -> list[str]:
    row = ["" for _ in S2T_COLUMNS]
    target_schema, target_table = _relation_parts(target_relation)
    values = {
        "T-trg-schema": target_schema,
        "T-trg": target_table,
        "T-trg-f": target_column,
    }
    if metadata:
        allowed_metadata_columns = {
            "T-trg-platform", "T-trg-instance", "T-trg-schema", "T-trg", "UserName", "T-trg-f",
            "target_data_relevance", "target_data_hist", "target_data_freq", "T-k", "T-hist-type",
            "T-hist-role", "codeDatamart", "Datamart.description_source", "Table.description_source",
        }
        for column in allowed_metadata_columns:
            if column in metadata and metadata.get(column) not in (None, ""):
                values[column] = _text(metadata.get(column))
    for column, value in values.items():
        row[S2T_COLUMNS.index(column)] = value
    return row


def _row_id(row: Sequence[str]) -> str:
    encoded = json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "s2t-row-" + hashlib.sha256(encoded).hexdigest()[:24]


def _row_sort_key(row: Sequence[str]) -> tuple[str, ...]:
    indices = [
        S2T_COLUMNS.index("T-trg-schema"),
        S2T_COLUMNS.index("T-trg"),
        S2T_COLUMNS.index("T-trg-f"),
        S2T_COLUMNS.index("T-src-schema"),
        S2T_COLUMNS.index("T-src"),
        S2T_COLUMNS.index("T-src-f-name"),
    ]
    prefix = tuple(row[index] for index in indices)
    return (*prefix, *tuple(row))


def build_deterministic_s2t(
    mapping_rows: Iterable[Mapping[str, Any]],
    *,
    mapping_gaps: Iterable[Mapping[str, Any]] = (),
    environment_resolutions: Iterable[Mapping[str, Any]] = (),
    target_fields: Iterable[Mapping[str, Any]] = (),
    column_usage_contexts: Iterable[Mapping[str, Any]] = (),
) -> BuildResult:
    """Build canonical deterministic S2T rows from serialized public AISL evidence.

    No target names, file paths, platform names or corpus-specific literals are
    interpreted. Candidate producer sets remain owned by AISL public evidence.
    """
    mapping_rows = [dict(item) for item in mapping_rows]
    mapping_gaps = [dict(item) for item in mapping_gaps]
    environment_resolutions = [dict(item) for item in environment_resolutions]
    target_fields = [dict(item) for item in target_fields]
    column_usage_contexts = [dict(item) for item in column_usage_contexts]

    primary = collapse_primary_sources(
        mapping_rows,
        environment_resolutions=environment_resolutions,
    )
    metadata = _metadata_index(target_fields)
    mappings_by_id = {
        _text(row.get("mapping_id")): row
        for row in mapping_rows
        if _text(row.get("mapping_id"))
    }

    observed_targets: set[tuple[str, str]] = set(metadata)
    observed_targets.update(key for key in (_target_key(row) for row in mapping_rows) if all(key))
    observed_targets.update(key for key in (_target_key(row) for row in mapping_gaps) if all(key))

    rows_with_audit: list[tuple[tuple[str, ...], RowAudit]] = []
    resolved_targets: set[tuple[str, str]] = set()
    for decision in primary:
        target_key = (decision.target_relation, decision.target_column)
        if decision.status not in {"resolved", "template"} or not decision.source_relation:
            continue
        resolved_targets.add(target_key)
        base = _base_row(decision.target_relation, decision.target_column, metadata.get(target_key))
        source_schema, source_table = _relation_parts(decision.source_relation)
        base[S2T_COLUMNS.index("T-src-schema")] = source_schema
        base[S2T_COLUMNS.index("T-src")] = source_table
        observed_source_column = _observed_source_column_for_decision(decision, mappings_by_id)
        base[S2T_COLUMNS.index("T-src-f-name")] = observed_source_column
        expressions = _expressions_for_decision(decision, mappings_by_id) or ("",)
        for expression in expressions:
            row = list(base)
            row[S2T_COLUMNS.index("T-src-f")] = expression
            frozen = tuple(row)
            rows_with_audit.append((
                frozen,
                RowAudit(
                    row_id=_row_id(frozen),
                    target_relation=decision.target_relation,
                    target_column=decision.target_column,
                    source_relation=decision.source_relation,
                    source_column=observed_source_column or None,
                    basis=decision.basis,
                    mapping_ids=decision.mapping_ids,
                    primary_templates=decision.primary_templates,
                ),
            ))

    # Preserve every observed target field even when source evidence is absent,
    # ambiguous, lookup-only or otherwise insufficient. Exact row dedupe below
    # prevents diagnostic multiplicity from duplicating target-only CSV rows.
    for target_relation, target_column in sorted(observed_targets - resolved_targets):
        row = tuple(_base_row(target_relation, target_column, metadata.get((target_relation, target_column))))
        rows_with_audit.append((
            row,
            RowAudit(
                row_id=_row_id(row),
                target_relation=target_relation,
                target_column=target_column,
                source_relation=None,
                source_column=None,
                basis="target_observed_primary_source_not_resolved",
                mapping_ids=tuple(sorted({
                    _text(item.get("mapping_id"))
                    for item in mapping_rows
                    if _target_key(item) == (target_relation, target_column) and _text(item.get("mapping_id"))
                })),
                primary_templates=(),
            ),
        ))

    # Exact canonical row dedupe. Merge provenance for duplicate visible rows.
    audit_by_row: dict[tuple[str, ...], list[RowAudit]] = {}
    for row, audit in rows_with_audit:
        audit_by_row.setdefault(row, []).append(audit)
    rows = tuple(sorted(audit_by_row, key=_row_sort_key))
    merged_audit: list[RowAudit] = []
    for row in rows:
        items = audit_by_row[row]
        merged_audit.append(RowAudit(
            row_id=_row_id(row),
            target_relation=items[0].target_relation,
            target_column=items[0].target_column,
            source_relation=items[0].source_relation,
            source_column=items[0].source_column,
            basis="+".join(sorted({item.basis for item in items})),
            mapping_ids=tuple(sorted({value for item in items for value in item.mapping_ids})),
            primary_templates=tuple(sorted({value for item in items for value in item.primary_templates})),
        ))

    public_gaps = classify_public_mapping_gaps(
        mapping_gaps,
        mapping_rows=mapping_rows,
        column_usage_contexts=column_usage_contexts,
        environment_semantic_decisions=environment_resolutions,
    )
    primary_gaps = classify_primary_source_residuals(
        primary,
        environment_semantic_decisions=environment_resolutions,
    )
    convention_gaps = classify_consumer_convention_residuals(
        mapping_rows,
        resolved_primary_targets=resolved_targets,
    )
    gaps = tuple(combine_typed_gaps(public_gaps, primary_gaps, convention_gaps))

    return BuildResult(
        rows=rows,
        row_audit=tuple(merged_audit),
        gaps=gaps,
        primary_source_decisions=tuple(primary),
    )


def render_s2t_csv(rows: Iterable[Sequence[str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(S2T_COLUMNS)
    writer.writerow(S2T_DESCRIPTIONS)
    for row in rows:
        values = tuple(_text(value) for value in row)
        if len(values) != len(S2T_COLUMNS):
            raise ValueError(f"S2T row has {len(values)} fields; expected {len(S2T_COLUMNS)}")
        writer.writerow(values)
    return buffer.getvalue()


def write_build_outputs(
    result: BuildResult,
    *,
    csv_path: str | Path,
    audit_path: str | Path,
    system_id: str = "",
    revision_id: str = "",
) -> None:
    Path(csv_path).write_text(render_s2t_csv(result.rows), encoding="utf-8", newline="")
    Path(audit_path).write_text(
        json.dumps(result.audit_payload(system_id=system_id, revision_id=revision_id), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
