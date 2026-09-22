from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class EnvironmentPolicy:
    """Consumer-owned stand selection policy.

    AISL publishes candidates/scopes but does not choose a preferred stand. The S2T
    consumer selects an explicit environment when supplied; otherwise it uses the
    configured default role. Roles are mapped to observed scope identities by input
    policy/configuration rather than inferred from schema or cluster names.
    """

    environment_scopes: Mapping[str, Sequence[str]]
    default_environment: str = "production"
    explicit_environment: str | None = None

    @property
    def selected_environment(self) -> str:
        return (self.explicit_environment or self.default_environment).strip().lower()

    @property
    def selected_scopes(self) -> frozenset[str]:
        return frozenset(
            str(value).strip()
            for value in self.environment_scopes.get(self.selected_environment, ())
            if str(value).strip()
        )


@dataclass(frozen=True)
class PlaceholderDecision:
    placeholder: str
    status: str
    value: str | None
    basis: str
    environment: str | None
    candidate_values: tuple[str, ...]
    matching_environment_values: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "placeholder": self.placeholder,
            "status": self.status,
            "value": self.value,
            "basis": self.basis,
            "environment": self.environment,
            "candidate_values": list(self.candidate_values),
            "matching_environment_values": list(self.matching_environment_values),
        }


@dataclass(frozen=True)
class GapDecision:
    gap_id: str
    workflow_context_file: str
    target_relation: str
    target_column: str
    source_relation_template: str
    source_column: str
    status: str
    resolved_source_relation: str | None
    basis: str
    placeholder_decisions: tuple[PlaceholderDecision, ...]

    @property
    def semantic_key(self) -> tuple[str, str, str, str]:
        return (
            self.target_relation,
            self.target_column,
            self.source_relation_template,
            self.source_column,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "workflow_context_file": self.workflow_context_file,
            "target_relation": self.target_relation,
            "target_column": self.target_column,
            "source_relation_template": self.source_relation_template,
            "source_column": self.source_column,
            "status": self.status,
            "resolved_source_relation": self.resolved_source_relation,
            "basis": self.basis,
            "placeholder_decisions": [item.to_dict() for item in self.placeholder_decisions],
        }


class EnvironmentEvidenceIndex:
    """Index exact observed placeholder values by observed environment scope."""

    def __init__(self) -> None:
        self._value_scopes: dict[tuple[str, str], set[str]] = defaultdict(set)

    def add(self, *, placeholder: str, value: str, scope: str) -> None:
        placeholder = str(placeholder or "").strip()
        value = str(value or "").strip()
        scope = str(scope or "").strip()
        if not placeholder or not value or not scope or not _is_concrete(value):
            return
        self._value_scopes[(placeholder, value)].add(scope)

    def scopes_for(self, placeholder: str, value: str) -> frozenset[str]:
        return frozenset(self._value_scopes.get((placeholder.strip(), value.strip()), ()))

    def values_for_scopes(self, placeholder: str, scopes: Iterable[str]) -> tuple[str, ...]:
        """Return exact observed concrete values for one placeholder in selected scopes."""
        selected = frozenset(str(scope).strip() for scope in scopes if str(scope).strip())
        if not selected:
            return ()
        key = str(placeholder or "").strip()
        return tuple(sorted({
            value
            for (candidate_placeholder, value), observed_scopes in self._value_scopes.items()
            if candidate_placeholder == key and selected.intersection(observed_scopes)
        }))

    @classmethod
    def from_observations(cls, observations: Iterable[Mapping[str, Any]]) -> "EnvironmentEvidenceIndex":
        index = cls()
        for item in observations:
            index.add(
                placeholder=str(item.get("placeholder") or ""),
                value=str(item.get("value") or item.get("resolved_value") or ""),
                scope=str(item.get("scope") or item.get("selected_scope") or ""),
            )
        return index

    @classmethod
    def from_placeholder_resolution_rows(
        cls, rows: Iterable[Mapping[str, Any]]
    ) -> "EnvironmentEvidenceIndex":
        """Build from public/serialized placeholder-resolution evidence rows.

        The method only consumes structured evidence dictionaries. It does not infer
        environment roles from value text, paths, cluster names, or stand ordering.
        """
        index = cls()
        for row in rows:
            if str(row.get("resolution_status") or "") != "resolved":
                continue
            placeholder = str(row.get("placeholder") or "")
            value = str(row.get("resolved_value") or "")
            evidence = row.get("evidence") or row.get("evidence_json") or ()
            if isinstance(evidence, Mapping):
                evidence = [evidence]
            for item in evidence if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)) else ():
                if not isinstance(item, Mapping):
                    continue
                if str(item.get("evidence_kind") or "") != "sql_environment_scope_observation":
                    continue
                index.add(
                    placeholder=placeholder,
                    value=value,
                    scope=str(item.get("selected_scope") or ""),
                )
        return index


def _is_concrete(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value) and "{{" not in value and "${" not in value


def _concrete_candidates(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if _is_concrete(str(value))}))


def _exact_placeholder_reference(value: Any) -> str | None:
    """Return one exact placeholder identity without evaluating template expressions."""
    text = str(value or "").strip()
    if not (text.startswith("${") and text.endswith("}")):
        return None
    inner = text[2:-1].strip()
    if inner.startswith("$"):
        inner = inner[1:].strip()
    if not inner or "${" in inner or "{{" in inner or "}" in inner:
        return None
    return inner


def _environment_expanded_candidates(
    values: Iterable[Any],
    *,
    index: EnvironmentEvidenceIndex,
    selected_scopes: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Expand only exact placeholder-to-concrete bindings observed in selected scopes.

    Candidate templates are public evidence, not source text. A nested candidate is
    composed only when it is exactly one placeholder token and the environment index
    publishes concrete values for that nested placeholder in the already selected
    environment scope. Prefix/suffix templates and arbitrary expression evaluation are
    deliberately out of scope and remain unresolved.
    """
    concrete = set(_concrete_candidates(values))
    environment_values: set[str] = set()
    for raw in values:
        nested = _exact_placeholder_reference(raw)
        if not nested:
            continue
        observed = index.values_for_scopes(nested, selected_scopes)
        concrete.update(observed)
        environment_values.update(observed)
    return tuple(sorted(concrete)), tuple(sorted(environment_values))


def resolve_placeholder(
    item: Mapping[str, Any],
    *,
    index: EnvironmentEvidenceIndex,
    policy: EnvironmentPolicy,
) -> PlaceholderDecision:
    placeholder = str(item.get("placeholder") or "").strip()
    raw_values = tuple(item.get("candidate_values") or ())
    direct_candidates = _concrete_candidates(raw_values)
    selected_scopes = policy.selected_scopes
    candidates, nested_environment_values = _environment_expanded_candidates(
        raw_values, index=index, selected_scopes=selected_scopes
    )

    if len(candidates) == 1 and not nested_environment_values:
        return PlaceholderDecision(
            placeholder=placeholder,
            status="resolved",
            value=candidates[0],
            basis="unique_concrete_candidate",
            environment=None,
            candidate_values=candidates,
            matching_environment_values=(),
        )

    matching = tuple(sorted({
        *nested_environment_values,
        *(
            value
            for value in direct_candidates
            if selected_scopes.intersection(index.scopes_for(placeholder, value))
        ),
    }))
    basis_prefix = "explicit_environment" if policy.explicit_environment else "default_environment"

    if len(matching) == 1:
        return PlaceholderDecision(
            placeholder=placeholder,
            status="resolved",
            value=matching[0],
            basis=f"{basis_prefix}:{policy.selected_environment}",
            environment=policy.selected_environment,
            candidate_values=candidates,
            matching_environment_values=matching,
        )
    if len(matching) > 1:
        return PlaceholderDecision(
            placeholder=placeholder,
            status="ambiguous",
            value=None,
            basis=f"multiple_candidates_for_environment:{policy.selected_environment}",
            environment=policy.selected_environment,
            candidate_values=candidates,
            matching_environment_values=matching,
        )
    return PlaceholderDecision(
        placeholder=placeholder,
        status="unresolved",
        value=None,
        basis=f"no_candidate_for_environment:{policy.selected_environment}",
        environment=policy.selected_environment,
        candidate_values=candidates,
        matching_environment_values=(),
    )


def _substitute_relation_template(template: str, bindings: Mapping[str, str]) -> str:
    result = str(template or "")
    for placeholder, value in sorted(bindings.items()):
        result = result.replace("${$" + placeholder + "}", value)
    return result


def resolve_environment_gap(
    gap: Mapping[str, Any],
    *,
    index: EnvironmentEvidenceIndex,
    policy: EnvironmentPolicy,
) -> GapDecision:
    evidence = gap.get("evidence") or {}
    placeholder_items = evidence.get("placeholder_resolution") or ()
    decisions = tuple(
        resolve_placeholder(item, index=index, policy=policy)
        for item in placeholder_items
        if isinstance(item, Mapping)
    )
    resolved_bindings = {
        item.placeholder: item.value
        for item in decisions
        if item.status == "resolved" and item.value is not None
    }
    all_resolved = bool(decisions) and all(item.status == "resolved" for item in decisions)
    template = str(evidence.get("source_relation_name") or "")
    resolved_relation = _substitute_relation_template(template, resolved_bindings) if all_resolved else None
    status = "resolved" if all_resolved and resolved_relation and "${$" not in resolved_relation else "unresolved"
    basis = (
        "deterministic_placeholder_policy"
        if status == "resolved"
        else "placeholder_policy_incomplete"
    )
    return GapDecision(
        gap_id=str(gap.get("gap_id") or ""),
        workflow_context_file=str(gap.get("workflow_context_file") or ""),
        target_relation=str(gap.get("workflow_target_logical_name") or gap.get("target_relation") or ""),
        target_column=str(gap.get("target_column") or ""),
        source_relation_template=template,
        source_column=str(evidence.get("source_column") or ""),
        status=status,
        resolved_source_relation=resolved_relation if status == "resolved" else None,
        basis=basis,
        placeholder_decisions=decisions,
    )


def collapse_semantic_decisions(decisions: Iterable[GapDecision]) -> list[dict[str, Any]]:
    """Deduplicate workflow-context diagnostics into fail-closed S2T decisions.

    One semantic source decision may appear through several workflow contexts. A
    group is resolved only when every resolved context agrees on one exact source
    relation identity. Unresolved sibling contexts do not defeat that consistent
    exact identity; conflicting resolved identities keep the group ambiguous.
    """
    grouped: dict[tuple[str, str, str, str], list[GapDecision]] = defaultdict(list)
    for decision in decisions:
        grouped[decision.semantic_key].append(decision)

    result: list[dict[str, Any]] = []
    for key in sorted(grouped):
        items = grouped[key]
        resolved_values = sorted({
            item.resolved_source_relation
            for item in items
            if item.status == "resolved" and item.resolved_source_relation
        })
        if len(resolved_values) == 1:
            status = "resolved"
            resolved_source_relation = resolved_values[0]
            basis = "consistent_resolved_workflow_contexts"
        elif len(resolved_values) > 1:
            status = "ambiguous"
            resolved_source_relation = None
            basis = "conflicting_resolved_workflow_contexts"
        else:
            status = "unresolved"
            resolved_source_relation = None
            basis = "no_resolved_workflow_context"
        result.append({
            "semantic_key": list(key),
            "status": status,
            "resolved_source_relation": resolved_source_relation,
            "basis": basis,
            "gap_ids": sorted(item.gap_id for item in items),
            "workflow_context_files": sorted({item.workflow_context_file for item in items}),
        })
    return result
