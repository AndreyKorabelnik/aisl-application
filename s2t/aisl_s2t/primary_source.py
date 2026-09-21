from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_concrete_relation(value: str) -> bool:
    value = _text(value)
    return bool(value) and "${" not in value and "{{" not in value


@dataclass(frozen=True)
class PrimarySourceDecision:
    target_relation: str
    target_column: str
    source_column: str
    source_relation_role: str
    status: str
    source_relation: str | None
    basis: str
    primary_templates: tuple[str, ...]
    terminal_relations: tuple[str, ...]
    mapping_ids: tuple[str, ...]
    workflow_context_files: tuple[str, ...]
    source_sql_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_relation": self.target_relation,
            "target_column": self.target_column,
            "source_column": self.source_column,
            "source_relation_role": self.source_relation_role,
            "status": self.status,
            "source_relation": self.source_relation,
            "basis": self.basis,
            "primary_templates": list(self.primary_templates),
            "terminal_relations": list(self.terminal_relations),
            "mapping_ids": list(self.mapping_ids),
            "workflow_context_files": list(self.workflow_context_files),
            "source_sql_files": list(self.source_sql_files),
        }


class EnvironmentResolutionIndex:
    """Resolve relation templates from deterministic environment decisions only."""

    def __init__(self) -> None:
        self._resolved: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
        self._blocked: set[tuple[str, str, str, str]] = set()

    @classmethod
    def from_semantic_decisions(
        cls, decisions: Iterable[Mapping[str, Any]]
    ) -> "EnvironmentResolutionIndex":
        index = cls()
        for item in decisions:
            key_raw = item.get("semantic_key") or ()
            if not isinstance(key_raw, Sequence) or isinstance(key_raw, (str, bytes)) or len(key_raw) != 4:
                continue
            key = tuple(_text(value) for value in key_raw)
            status = _text(item.get("status"))
            resolved = _text(item.get("resolved_source_relation"))
            if status == "resolved" and resolved:
                index._resolved[key].add(resolved)
            elif status in {"ambiguous", "unresolved"}:
                index._blocked.add(key)
        return index

    def resolve(
        self,
        *,
        target_relation: str,
        target_column: str,
        relation_template: str,
        source_column: str,
    ) -> tuple[str, tuple[str, ...]]:
        relation_template = _text(relation_template)
        if _is_concrete_relation(relation_template):
            return "resolved", (relation_template,)
        key = (
            _text(target_relation),
            _text(target_column),
            relation_template,
            _text(source_column),
        )
        values = tuple(sorted(self._resolved.get(key, ())))
        if len(values) == 1:
            return "resolved", values
        if len(values) > 1:
            return "ambiguous", values
        return ("unresolved" if key in self._blocked else "unresolved"), ()


def _primary_template(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return the current public primary-source identity or literal template.

    Current AISL target-source mapping distinguishes observed branch structure
    (branch_relation_name) from the derived terminal driver relation
    (driver_relation_name). The S2T consumer therefore prefers the driver whenever
    the producer established one and must not promote a branch/staging relation
    when the producer reports an ambiguous or unresolved driver.

    Older serialized inputs that predate the explicit driver contract keep the
    branch fallback for compatibility.
    """

    driver_status = _text(row.get("driver_relation_status"))
    driver = _text(row.get("driver_relation_name"))
    if driver_status in {"resolved", "partial"} and driver:
        return driver, (
            "resolved_driver_relation"
            if driver_status == "resolved"
            else "partial_driver_relation_template"
        )
    if driver_status == "ambiguous":
        return "", "ambiguous_driver_relation"
    if driver_status == "unresolved" and "driver_relation_status" in row:
        return "", "unresolved_driver_relation"

    branch = _text(row.get("branch_relation_name"))
    if branch:
        return branch, "legacy_branch_relation"
    terminal = _text(row.get("source_sql_relation_name") or row.get("immediate_source_relation_name"))
    if terminal:
        return terminal, "terminal_relation_fallback"
    return "", "missing_relation_identity"


def collapse_primary_sources(
    mapping_rows: Iterable[Mapping[str, Any]],
    *,
    environment_resolutions: Iterable[Mapping[str, Any]],
    primary_roles: Sequence[str] = ("driver_path",),
) -> list[PrimarySourceDecision]:
    """Collapse traversal contexts to primary/upstream source decisions.

    Current target-source mapping publishes `driver_relation_name` as the derived
    terminal primary-source relation and `branch_relation_name` as observed branch
    structure. Current driver identity therefore wins; legacy inputs without the
    explicit driver contract may still fall back to branch identity. This function never interprets
    file names such as ``hist``/``backup``/``devops``. Distinct resolved branch
    identities remain distinct decisions, preserving multiple valid value branches.

    Environment/template substitution is accepted only from previously deterministic
    environment decisions. Conflicting or absent template resolution stays fail-closed.
    """

    allowed_roles = {_text(value) for value in primary_roles if _text(value)}
    env = EnvironmentResolutionIndex.from_semantic_decisions(environment_resolutions)

    raw_groups: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in mapping_rows:
        role = _text(row.get("source_relation_role"))
        if allowed_roles and role not in allowed_roles:
            continue
        target_relation = _text(row.get("workflow_target_logical_name") or row.get("target_relation"))
        target_column = _text(row.get("target_column"))
        source_column = _text(row.get("source_sql_column") or row.get("immediate_source_column") or target_column)
        template, template_basis = _primary_template(row)
        status, resolved_values = env.resolve(
            target_relation=target_relation,
            target_column=target_column,
            relation_template=template,
            source_column=source_column,
        ) if template else ("unresolved", ())

        if (
            status == "unresolved"
            and template
            and template_basis == "partial_driver_relation_template"
        ):
            # Preserve the literal producer-published source template while keeping
            # the unresolved environment dimension explicit in the typed gaps.
            status = "template"
            resolved_values = (template,)

        if status in {"resolved", "template"} and len(resolved_values) == 1:
            identity = resolved_values[0]
        else:
            identity = template
        raw_key = (target_relation, target_column, source_column, role, identity, status)
        raw_groups[raw_key].append({
            "row": row,
            "template": template,
            "template_basis": template_basis,
            "resolved_values": resolved_values,
        })

    result: list[PrimarySourceDecision] = []
    for key in sorted(raw_groups):
        target_relation, target_column, source_column, role, identity, status = key
        items = raw_groups[key]
        templates = tuple(sorted({_text(item["template"]) for item in items if _text(item["template"])}))
        terminal_relations = tuple(sorted({
            _text(item["row"].get("source_sql_relation_name") or item["row"].get("immediate_source_relation_name"))
            for item in items
            if _text(item["row"].get("source_sql_relation_name") or item["row"].get("immediate_source_relation_name"))
        }))
        template_bases = {_text(item["template_basis"]) for item in items}
        if status == "resolved" and identity:
            source_relation = identity
            basis = (
                "mechanically_observed_driver_primary_source"
                if template_bases.intersection(
                    {"resolved_driver_relation", "partial_driver_relation_template"}
                )
                else "resolved_primary_source_identity"
            )
        elif status == "template" and identity:
            source_relation = identity
            basis = "mechanically_observed_driver_primary_source_template"
        elif status == "ambiguous":
            source_relation = None
            basis = "ambiguous_primary_source_template_resolution"
        else:
            source_relation = None
            basis = "unresolved_primary_source_template"

        result.append(PrimarySourceDecision(
            target_relation=target_relation,
            target_column=target_column,
            source_column=source_column,
            source_relation_role=role,
            status=status,
            source_relation=source_relation,
            basis=basis,
            primary_templates=templates,
            terminal_relations=terminal_relations,
            mapping_ids=tuple(sorted({_text(item["row"].get("mapping_id")) for item in items if _text(item["row"].get("mapping_id"))})),
            workflow_context_files=tuple(sorted({_text(item["row"].get("workflow_context_file")) for item in items if _text(item["row"].get("workflow_context_file"))})),
            source_sql_files=tuple(sorted({_text(item["row"].get("source_sql_file")) for item in items if _text(item["row"].get("source_sql_file"))})),
        ))
    return result
