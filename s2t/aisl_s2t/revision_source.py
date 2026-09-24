from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping, Sequence


SQL_ANALYSIS_PROFILE_ID = "sql-analysis/v1"
REQUIRED_CAPABILITIES = frozenset({
    "common.sql-target-resolution",
    "common.sql-target-value-source-mapping",
})
DEFAULT_AISL_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_AISL_TIMEOUT_SECONDS = 30.0
_TARGET_PAGE_SIZE = 100
_MAPPING_PAGE_SIZE = 10
_MAX_GAPS_PER_PAGE = 500


class RevisionSourceError(RuntimeError):
    """Pinned AISL revision cannot satisfy the deterministic S2T input contract."""


@dataclass(frozen=True)
class RevisionBuildInputs:
    mapping_rows: tuple[dict[str, Any], ...]
    mapping_gaps: tuple[dict[str, Any], ...]
    target_fields: tuple[dict[str, Any], ...]
    retrieval: dict[str, Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _objects(value: Any, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RevisionSourceError(f"{name} must be an array")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RevisionSourceError(f"{name} must contain objects only")
        result.append(dict(item))
    return result


def _page_total(payload: Mapping[str, Any], *, name: str) -> int:
    page = payload.get("page")
    if not isinstance(page, Mapping):
        raise RevisionSourceError(f"{name} response has no page object")
    try:
        total = int(page.get("total") or 0)
    except (TypeError, ValueError) as exc:
        raise RevisionSourceError(f"{name} response has invalid page.total") from exc
    if total < 0:
        raise RevisionSourceError(f"{name} response has negative page.total")
    return total


def _validate_revision_identity(
    payload: Mapping[str, Any], *, system_id: str, revision_id: str, tool_name: str
) -> None:
    actual_system = _text(payload.get("system_id"))
    actual_revision = _text(payload.get("revision_id"))
    if actual_system != system_id or actual_revision != revision_id:
        raise RevisionSourceError(
            f"{tool_name} returned {actual_system or '<empty>'}/{actual_revision or '<empty>'}; "
            f"expected pinned revision {system_id}/{revision_id}"
        )


def _execute(integration: Any, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    try:
        execution = integration.execute_tool(name, arguments)
    except Exception as exc:  # SDK owns transport/API exception taxonomy.
        raise RevisionSourceError(f"AISL tool {name} failed: {exc}") from exc
    payload = getattr(execution, "result", None)
    if not isinstance(payload, Mapping):
        raise RevisionSourceError(f"AISL tool {name} returned a non-object result")
    return dict(payload)


def _path_has_disabled_context(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = [part.strip().casefold() for part in normalized.split("/") if part.strip()]
    return "__off__" in parts


def _candidate_disabled(candidate: Mapping[str, Any]) -> bool:
    for key in ("workflow_status", "target_status", "activation_status"):
        status = _text(candidate.get(key)).casefold()
        if status in {"disabled", "off", "__off__"}:
            return True
    contexts = [
        _text(item)
        for item in candidate.get("workflow_contexts") or ()
        if _text(item)
    ]
    return bool(contexts) and all(_path_has_disabled_context(item) for item in contexts)


def _candidate_identity(candidate: Mapping[str, Any]) -> tuple[str, str]:
    return (_text(candidate.get("repo_id")), _text(candidate.get("logical_target_name")))


def _target_display_relation(candidate: Mapping[str, Any]) -> str:
    logical = _text(candidate.get("logical_target_name"))
    recommended = _text(candidate.get("recommended_target_relation"))
    recommendation_status = _text(candidate.get("target_relation_recommendation_status"))
    if recommended and recommendation_status == "confirmed_unique":
        return recommended
    return logical


def _discover_targets(
    integration: Any, *, system_id: str, revision_id: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    offset = 0
    candidates: list[dict[str, Any]] = []
    total: int | None = None
    pages = 0
    while total is None or offset < total:
        payload = _execute(
            integration,
            "find_sql_target_candidates",
            {"offset": offset, "limit": _TARGET_PAGE_SIZE},
        )
        _validate_revision_identity(
            payload, system_id=system_id, revision_id=revision_id,
            tool_name="find_sql_target_candidates",
        )
        page_items = _objects(payload.get("candidates"), "find_sql_target_candidates.candidates")
        try:
            response_total = int(payload.get("candidate_count") or 0)
        except (TypeError, ValueError) as exc:
            raise RevisionSourceError("find_sql_target_candidates returned invalid candidate_count") from exc
        if response_total < 0:
            raise RevisionSourceError("find_sql_target_candidates returned negative candidate_count")
        if total is None:
            total = response_total
        elif total != response_total:
            raise RevisionSourceError("find_sql_target_candidates candidate_count changed during pagination")
        if not page_items:
            if offset < total:
                raise RevisionSourceError("find_sql_target_candidates pagination stalled before candidate_count")
            break
        candidates.extend(page_items)
        offset += len(page_items)
        pages += 1
        if offset > total:
            raise RevisionSourceError("find_sql_target_candidates returned more candidates than candidate_count")

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    skipped_intermediate = 0
    skipped_disabled = 0
    skipped_unknown_kind = 0
    for candidate in candidates:
        repo_id, logical_target = _candidate_identity(candidate)
        if not logical_target:
            raise RevisionSourceError("find_sql_target_candidates returned candidate without logical_target_name")
        target_kind = _text(candidate.get("target_kind"))
        if target_kind == "intermediate":
            skipped_intermediate += 1
            continue
        if target_kind not in {"published_or_terminal", "workflow_target"}:
            skipped_unknown_kind += 1
            continue
        if _candidate_disabled(candidate):
            skipped_disabled += 1
            continue
        key = (repo_id, logical_target.casefold())
        previous = selected.get(key)
        if previous is not None and previous != candidate:
            raise RevisionSourceError(
                f"find_sql_target_candidates returned conflicting duplicates for {repo_id or '<default>'}/{logical_target}"
            )
        selected[key] = candidate

    ordered = sorted(
        selected.values(),
        key=lambda item: (
            _text(item.get("repo_id")).casefold(),
            _text(item.get("logical_target_name")).casefold(),
            _text(item.get("logical_target_name")),
        ),
    )
    return ordered, {
        "target_candidate_pages": pages,
        "target_candidates_seen": len(candidates),
        "eligible_targets": len(ordered),
        "skipped_intermediate_targets": skipped_intermediate,
        "skipped_disabled_targets": skipped_disabled,
        "skipped_unknown_target_kind": skipped_unknown_kind,
    }


def _driver_status(source: Mapping[str, Any]) -> str:
    status = _text(source.get("status")).casefold()
    if status in {"resolved", "complete", "confirmed"}:
        return "resolved"
    if status == "partial":
        return "partial"
    if status == "ambiguous":
        return "ambiguous"
    return "unresolved"


def _linked_expressions(
    source: Mapping[str, Any], target_expressions: Sequence[Mapping[str, Any]], *, target_column: str
) -> list[dict[str, Any]]:
    raw_refs = source.get("target_expression_refs") or ()
    if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes)):
        raise RevisionSourceError("source.target_expression_refs must be an array")
    linked: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw_ref in raw_refs:
        if isinstance(raw_ref, bool):
            raise RevisionSourceError("target_expression_ref must be an integer")
        try:
            ref = int(raw_ref)
        except (TypeError, ValueError) as exc:
            raise RevisionSourceError("target_expression_ref must be an integer") from exc
        if ref < 0 or ref >= len(target_expressions):
            raise RevisionSourceError(f"target_expression_ref {ref} is outside target_expressions")
        item = dict(target_expressions[ref])
        output_name = _text(item.get("output_name"))
        if output_name and output_name.casefold() != target_column.casefold():
            raise RevisionSourceError(
                f"target_expression_ref {ref} points to {output_name!r}, expected target column {target_column!r}"
            )
        key = (
            _text(item.get("expression")),
            _text(item.get("expression_kind")),
            output_name,
            _text(item.get("resolution_status")),
        )
        if key not in seen:
            seen.add(key)
            linked.append(item)
    return linked


def _normalize_gap(gap: Mapping[str, Any], *, target_relation: str) -> dict[str, Any]:
    details = gap.get("details") if isinstance(gap.get("details"), Mapping) else {}
    evidence = details.get("evidence") if isinstance(details.get("evidence"), Mapping) else {}
    return {
        "gap_id": _text(gap.get("gap_id")) or _text(gap.get("owner_id")),
        "workflow_context_file": _text(details.get("workflow_context_file")),
        "workflow_target_logical_name": target_relation,
        "target_column": _text(details.get("target_column")),
        "gap_kind": _text(gap.get("gap_kind")) or "unresolved",
        "impact": _text(details.get("impact")) or _text(gap.get("severity")),
        "mapping_basis": _text(details.get("mapping_basis")) or _text(gap.get("message")),
        "evidence": dict(evidence),
    }


def _collect_target(
    integration: Any,
    *,
    system_id: str,
    revision_id: str,
    candidate: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    repo_id = _text(candidate.get("repo_id")) or None
    logical_target = _text(candidate.get("logical_target_name"))
    target_relation = _target_display_relation(candidate)
    if not target_relation:
        raise RevisionSourceError("eligible target candidate has no target identity")

    offset = 0
    total: int | None = None
    pages = 0
    mapping_rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    target_fields: dict[tuple[str, str], dict[str, Any]] = {}
    gaps_truncated = False

    while total is None or offset < total:
        args: dict[str, Any] = {
            "target_relation": logical_target,
            "include_gaps": True,
            "max_gaps": _MAX_GAPS_PER_PAGE,
            "offset": offset,
            "limit": _MAPPING_PAGE_SIZE,
        }
        if repo_id is not None:
            args["repo_id"] = repo_id
        payload = _execute(integration, "list_sql_target_value_sources", args)
        _validate_revision_identity(
            payload, system_id=system_id, revision_id=revision_id,
            tool_name="list_sql_target_value_sources",
        )
        if _text(payload.get("mapping_schema_version")) != "target-source-mapping/v4":
            raise RevisionSourceError(
                "list_sql_target_value_sources returned unsupported mapping_schema_version: "
                f"{_text(payload.get('mapping_schema_version')) or '<empty>'}"
            )
        page_total = _page_total(payload, name="list_sql_target_value_sources")
        if total is None:
            total = page_total
        elif total != page_total:
            raise RevisionSourceError(
                f"list_sql_target_value_sources page.total changed for target {logical_target}"
            )
        page_mappings = _objects(payload.get("mappings"), "list_sql_target_value_sources.mappings")
        expressions = _objects(payload.get("target_expressions"), "list_sql_target_value_sources.target_expressions")
        page_gaps = _objects(payload.get("gaps"), "list_sql_target_value_sources.gaps")
        gaps_truncated = gaps_truncated or bool(payload.get("gaps_truncated"))

        for mapping in page_mappings:
            target_column = _text(mapping.get("target_column"))
            if not target_column:
                raise RevisionSourceError("list_sql_target_value_sources returned mapping without target_column")
            target_fields.setdefault(
                (target_relation, target_column),
                {"target_relation": target_relation, "target_column": target_column},
            )
            sources = _objects(mapping.get("sources"), "mapping.sources")
            expected_source_count = mapping.get("source_count")
            if expected_source_count is not None:
                try:
                    expected = int(expected_source_count)
                except (TypeError, ValueError) as exc:
                    raise RevisionSourceError("mapping.source_count must be an integer") from exc
                if expected != len(sources):
                    raise RevisionSourceError(
                        f"mapping.source_count mismatch for {target_relation}.{target_column}: "
                        f"declared {expected}, received {len(sources)}"
                    )
            for source in sources:
                relation = _text(source.get("relation"))
                column = _text(source.get("column"))
                mapping_id = _text(source.get("value_mapping_id"))
                if not relation or not column or not mapping_id:
                    raise RevisionSourceError(
                        f"source endpoint for {target_relation}.{target_column} lacks relation/column/value_mapping_id"
                    )
                status = _driver_status(source)
                mapping_rows.append({
                    "mapping_id": mapping_id,
                    "repo_id": repo_id or "",
                    "workflow_target_logical_name": target_relation,
                    "target_column": target_column,
                    "source_branch": source.get("source_branch"),
                    "source_branch_scope_id": source.get("source_branch_scope_id"),
                    "source_branch_ordinal": source.get("source_branch_ordinal"),
                    "branch_relation_name": relation,
                    "driver_relation_name": relation if status in {"resolved", "partial"} else "",
                    "driver_relation_status": status,
                    "driver_relation_basis": _text(source.get("mapping_basis")) or "public_target_value_source_endpoint",
                    "source_relation_role": _text(source.get("source_relation_role")) or "unknown",
                    "source_sql_relation_name": relation,
                    "source_sql_column": column,
                    "mapping_status": _text(source.get("status")),
                    "linked_target_expressions": _linked_expressions(
                        source, expressions, target_column=target_column
                    ),
                    "value_mapping_id": mapping_id,
                    "contribution_roles": list(source.get("contribution_roles") or ()),
                    "normalization_kind": source.get("normalization_kind"),
                    "mapping_basis": source.get("mapping_basis"),
                    "provenance": dict(source.get("provenance") or {}) if isinstance(source.get("provenance"), Mapping) else {},
                })

        for gap in page_gaps:
            normalized = _normalize_gap(gap, target_relation=target_relation)
            if normalized["target_column"]:
                target_fields.setdefault(
                    (target_relation, normalized["target_column"]),
                    {"target_relation": target_relation, "target_column": normalized["target_column"]},
                )
            gaps.append(normalized)

        consumed_columns = len(page_mappings)
        if consumed_columns == 0:
            if offset < total:
                raise RevisionSourceError(
                    f"list_sql_target_value_sources pagination stalled for target {logical_target}"
                )
            break
        offset += consumed_columns
        pages += 1
        if offset > total:
            raise RevisionSourceError(
                f"list_sql_target_value_sources returned more target columns than page.total for {logical_target}"
            )

    return mapping_rows, gaps, list(target_fields.values()), {
        "repo_id": repo_id,
        "logical_target_name": logical_target,
        "target_relation": target_relation,
        "target_kind": _text(candidate.get("target_kind")),
        "target_relation_recommendation_status": _text(candidate.get("target_relation_recommendation_status")),
        "pages": pages,
        "target_columns": total or 0,
        "mapping_rows": len(mapping_rows),
        "gaps": len(gaps),
        "gaps_truncated": gaps_truncated,
    }


def collect_revision_inputs(client: Any, *, system_id: str, revision_id: str) -> RevisionBuildInputs:
    system_id = _text(system_id)
    revision_id = _text(revision_id)
    if not system_id:
        raise RevisionSourceError("system_id must not be empty")
    if not revision_id:
        raise RevisionSourceError("revision_id must not be empty")

    try:
        pinned = client.revision(system_id, revision_id)
        capabilities = set(pinned.get_capabilities())
    except Exception as exc:
        raise RevisionSourceError(
            f"cannot pin AISL revision {system_id}/{revision_id}: {exc}"
        ) from exc

    missing = sorted(REQUIRED_CAPABILITIES - capabilities)
    if missing:
        raise RevisionSourceError(
            f"AISL revision {system_id}/{revision_id} is not S2T-ready; missing capabilities: "
            + ", ".join(missing)
        )
    try:
        integration = pinned.integration(SQL_ANALYSIS_PROFILE_ID)
    except Exception as exc:
        raise RevisionSourceError(
            f"cannot load Integration Profile {SQL_ANALYSIS_PROFILE_ID} for {system_id}/{revision_id}: {exc}"
        ) from exc

    targets, target_stats = _discover_targets(
        integration, system_id=system_id, revision_id=revision_id
    )
    mapping_rows: list[dict[str, Any]] = []
    mapping_gaps: list[dict[str, Any]] = []
    target_fields: list[dict[str, Any]] = []
    target_details: list[dict[str, Any]] = []
    for target in targets:
        rows, gaps, fields, detail = _collect_target(
            integration,
            system_id=system_id,
            revision_id=revision_id,
            candidate=target,
        )
        mapping_rows.extend(rows)
        mapping_gaps.extend(gaps)
        target_fields.extend(fields)
        target_details.append(detail)

    # Stable de-duplication at the public evidence boundary. Conflicting duplicates
    # are not merged: mapping ids are expected to be globally stable in one revision.
    mappings_by_id: dict[str, dict[str, Any]] = {}
    for row in mapping_rows:
        mapping_id = _text(row.get("mapping_id"))
        previous = mappings_by_id.get(mapping_id)
        if previous is not None and previous != row:
            raise RevisionSourceError(f"conflicting public value mapping id: {mapping_id}")
        mappings_by_id[mapping_id] = row

    gaps_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for gap in mapping_gaps:
        key = (
            _text(gap.get("gap_id")),
            _text(gap.get("workflow_target_logical_name")),
            _text(gap.get("target_column")),
            _text(gap.get("gap_kind")),
        )
        gaps_by_key.setdefault(key, gap)

    fields_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for field in target_fields:
        key = (_text(field.get("target_relation")), _text(field.get("target_column")))
        if all(key):
            fields_by_key.setdefault(key, field)

    if (
        int(target_stats.get("eligible_targets") or 0) > 0
        and not mappings_by_id
        and not gaps_by_key
        and not fields_by_key
    ):
        raise RevisionSourceError(
            f"AISL revision {system_id}/{revision_id} discovered "
            f"{target_stats['eligible_targets']} eligible SQL targets, but public "
            "target-value-source evidence contains 0 target fields, 0 mappings and 0 gaps"
        )

    retrieval = {
        "schema_version": "aisl_s2t_revision_retrieval/v1",
        "system_id": system_id,
        "revision_id": revision_id,
        "integration_profile_id": SQL_ANALYSIS_PROFILE_ID,
        "required_capabilities": sorted(REQUIRED_CAPABILITIES),
        "published_capability_count": len(capabilities),
        **target_stats,
        "mapping_rows": len(mappings_by_id),
        "mapping_gaps": len(gaps_by_key),
        "target_fields": len(fields_by_key),
        "targets": target_details,
        "any_gap_page_truncated": any(bool(item.get("gaps_truncated")) for item in target_details),
    }
    return RevisionBuildInputs(
        mapping_rows=tuple(mappings_by_id[key] for key in sorted(mappings_by_id)),
        mapping_gaps=tuple(
            gaps_by_key[key]
            for key in sorted(gaps_by_key)
        ),
        target_fields=tuple(
            fields_by_key[key]
            for key in sorted(fields_by_key)
        ),
        retrieval=retrieval,
    )


def _sdk_client_factory(*, base_url: str, timeout_seconds: float) -> Any:
    try:
        from aisl_sdk import AislClient
    except ImportError as exc:
        raise RevisionSourceError(
            "aisl-sdk is required for revision-backed S2T; install the declared runtime dependencies"
        ) from exc
    return AislClient(base_url, timeout_sec=timeout_seconds)


def load_revision_inputs(
    *,
    system_id: str,
    revision_id: str,
    client_factory: Callable[..., Any] | None = None,
) -> RevisionBuildInputs:
    base_url = _text(os.getenv("AISL_BASE_URL", DEFAULT_AISL_BASE_URL)).rstrip("/")
    if not base_url:
        raise RevisionSourceError("AISL_BASE_URL must not be empty")
    raw_timeout = _text(os.getenv("AISL_TIMEOUT_SECONDS", str(DEFAULT_AISL_TIMEOUT_SECONDS)))
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise RevisionSourceError("AISL_TIMEOUT_SECONDS must be a positive number") from exc
    if timeout_seconds <= 0:
        raise RevisionSourceError("AISL_TIMEOUT_SECONDS must be a positive number")
    factory = client_factory or _sdk_client_factory
    client = factory(base_url=base_url, timeout_seconds=timeout_seconds)
    try:
        return collect_revision_inputs(client, system_id=system_id, revision_id=revision_id)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
