from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .contracts import RevisionBinding
from .gateway import LineageGateway


_ALLOWED_VARIANTS = ("base", "hist", "delta")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _relation_leaf(value: Any) -> str:
    text = _text(value).replace('"', "").replace("`", "")
    if not text:
        return ""
    return text.rsplit(".", 1)[-1].casefold()


def _representation_variant(base_relation: str, observed_relation: str) -> str | None:
    base = _relation_leaf(base_relation)
    observed = _relation_leaf(observed_relation)
    if not base or not observed:
        return None
    if observed == base:
        return "base"
    if observed == base + "_hist":
        return "hist"
    if observed == base + "_delta":
        return "delta"
    return None


def _exact_object(candidates: Sequence[Mapping[str, Any]], requested: str) -> dict[str, Any] | None:
    needle = requested.strip().casefold()
    matches = []
    for raw in candidates:
        item = dict(raw)
        names = {_text(item.get("fqcn")).casefold(), _text(item.get("name")).casefold()}
        if needle in names:
            matches.append(item)
    if len(matches) == 1:
        return matches[0]
    return None


def _field(context: Mapping[str, Any], field_name: str) -> dict[str, Any] | None:
    needle = field_name.strip().casefold()
    rows = [row for row in _objects(context.get("fields")) if _text(row.get("name")).casefold() == needle]
    return rows[0] if len(rows) == 1 else None


def _source_attribute_path(
    context: Mapping[str, Any],
    *,
    source_object: Mapping[str, Any],
    source_type: str,
    source_field: str,
) -> str:
    source_name = _text((context.get("object") or {}).get("name")) if isinstance(context.get("object"), Mapping) else ""
    source_name = source_name or source_type.rsplit(".", 1)[-1]
    incoming: list[tuple[str, str]] = []

    # Declared-model search exposes mechanically observed incoming bindings even
    # when the object-context relationship list contains only outgoing edges.
    binding_summary = source_object.get("binding_summary")
    if isinstance(binding_summary, Mapping):
        for relation in _objects(binding_summary.get("incoming_examples")):
            owner = _text(relation.get("source_name")) or _text(relation.get("source_fqcn")).rsplit(".", 1)[-1]
            rel_field = _text(relation.get("source_field"))
            if owner and rel_field:
                incoming.append((owner, rel_field))

    for relation in _objects(context.get("relationships")):
        target = relation.get("target") if isinstance(relation.get("target"), Mapping) else {}
        target_fqcn = _text(target.get("fqcn")).casefold()
        target_name = _text(target.get("name")).casefold()
        if source_type.casefold() not in {target_fqcn, target_name} and source_name.casefold() != target_name:
            continue
        owner = (
            _text(relation.get("source_type_name"))
            or _text(relation.get("source_type_fqcn")).rsplit(".", 1)[-1]
            or _text(relation.get("source_object_name"))
        )
        rel_field = _text(relation.get("source_field"))
        if owner and rel_field:
            incoming.append((owner, rel_field))

    incoming = list(dict.fromkeys(incoming))
    if len(incoming) == 1:
        owner, rel_field = incoming[0]
        return f"{owner}.{rel_field} → {source_name}.{source_field}"
    return f"{source_name}.{source_field}"


def _provenance_from_context(context: Mapping[str, Any], field: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("item_ref", "evidence_state", "evidence", "source_fragments"):
        if name in field:
            result[name] = field[name]
    if not result:
        for name in ("evidence", "source_fragments"):
            if name in context:
                result[name] = context[name]
    return result


def _tsa_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _physical_target_state(lineage: Mapping[str, Any]) -> tuple[str, list[str], str]:
    resolution = lineage.get("target_resolution")
    if not isinstance(resolution, Mapping):
        return "", [], ""
    candidates = [str(v) for v in resolution.get("physical_relation_candidates") or () if str(v)]
    recommended = _text(resolution.get("recommended_target_relation")) or _text(
        resolution.get("physical_relation_recommendation")
    )
    status = _text(resolution.get("physical_relation_recommendation_status")) or _text(
        resolution.get("physical_relation_status")
    )
    return recommended, candidates, status




def _candidate_has_exact_source_evidence(
    candidate: Mapping[str, Any], *, replica_relation: str, replica_column: str
) -> bool:
    allowed = {
        _relation_leaf(replica_relation),
        _relation_leaf(replica_relation + "_hist"),
        _relation_leaf(replica_relation + "_delta"),
    }
    relation_rows = [
        row
        for row in _objects(candidate.get("source_relation_matches"))
        if _relation_leaf(row.get("logical_name") or row.get("relation_name")) in allowed
    ]
    if not relation_rows:
        return False

    # Target-candidate discovery is only a broad discovery step.  Requiring an
    # exact source-column match here is unsafe for common SQL identifiers such
    # as ``name``: the candidate endpoint can retain the exact source relation
    # while its source_column_matches list is dominated by unrelated same-name
    # dictionary columns or SQL aliases.
    #
    # The next step is the authoritative precision gate: confirmed target-column
    # lineage must terminate on BOTH the exact replica relation (base/hist/delta)
    # and the exact replica column.  Therefore an exact source relation is
    # sufficient to admit a candidate for that exact downstream check; no field
    # name, alias, target name, or fuzzy inference is introduced here.
    return True

def _path_expressions(item: Mapping[str, Any]) -> list[str]:
    # target-column-lineage is a backward traversal (target -> terminal source).
    # CSV is a consumer projection and presents the same observed transforms in
    # source -> target order; raw structured evidence remains unchanged in
    # path_segments_json/provenance_json.
    expressions: list[str] = []
    for step in reversed(_objects(item.get("transformation_path_json"))):
        expression = _text(step.get("expression"))
        if expression and expression not in expressions:
            expressions.append(expression)
    return expressions


def _gap_row(
    *,
    source: RevisionBinding,
    tsa: RevisionBinding,
    profile: RevisionBinding,
    source_object: str,
    source_field: str,
    status: str,
    gap: str,
) -> dict[str, Any]:
    return {
        "source_system_id": source.system_id,
        "source_revision_id": source.revision_id,
        "source_root_object": source_object,
        "source_attribute_path": f"{source_object}.{source_field}",
        "source_type_fqcn": source_object,
        "source_field": source_field,
        "tsa_system_id": tsa.system_id,
        "tsa_revision_id": tsa.revision_id,
        "tsa_mapping_status": "",
        "tsa_mapping_basis": "",
        "replica_relation": "",
        "replica_column": "",
        "profile_system_id": profile.system_id,
        "profile_revision_id": profile.revision_id,
        "profile_source_relation": "",
        "profile_source_column": "",
        "profile_representation_variant": "",
        "target_relation": "",
        "target_column": "",
        "relation_path": "",
        "lineage_depth": "",
        "transformation_path": "",
        "path_segments_json": json.dumps([], ensure_ascii=False, separators=(",", ":")),
        "status": status,
        "gap": gap,
        "provenance_json": json.dumps({}, ensure_ascii=False, separators=(",", ":")),
    }


def _materialization_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        materialization_id = _text(row.get("materialization_id"))
        if materialization_id:
            result[materialization_id] = row
    return result


def _query_stage_name(query_file: Any) -> str:
    text = _text(query_file)
    if not text:
        return ""
    return PurePosixPath(text).stem


def _resolved_relation_path(
    item: Mapping[str, Any],
    *,
    materializations: Mapping[str, Mapping[str, Any]],
    target_relation: str,
    target_column: str,
) -> tuple[str, list[dict[str, Any]]]:
    terminal_relation = _text(item.get("terminal_relation_name"))
    terminal_column = _text(item.get("terminal_column"))
    display: list[str] = []
    resolved: list[dict[str, Any]] = []
    if terminal_relation:
        display.append(terminal_relation + (f".{terminal_column}" if terminal_column else ""))

    branch_steps = _objects(item.get("branch_path_json"))
    materialization_steps = [
        step for step in branch_steps
        if _text(step.get("kind")) == "observed_relation_materialization"
    ]
    for step in reversed(materialization_steps):
        materialization_id = _text(step.get("materialization_id"))
        record = dict(materializations.get(materialization_id) or {})
        if not record:
            resolved.append({"materialization_id": materialization_id, "resolution_status": "not_found"})
            continue
        query_stage = _query_stage_name(record.get("query_file"))
        output_table = _text(record.get("output_table_name"))
        if query_stage and (not display or _relation_leaf(display[-1]) != query_stage.casefold()):
            if query_stage.casefold() != output_table.casefold():
                display.append(query_stage)
        if output_table and (not display or _relation_leaf(display[-1]) != output_table.casefold()):
            display.append(output_table)
        resolved.append({
            "materialization_id": materialization_id,
            "query_stage": query_stage or None,
            "output_table_name": output_table or None,
            "query_file": record.get("query_file"),
            "workflow_context_file": record.get("workflow_context_file"),
            "resolution_status": record.get("resolution_status"),
            "mapping_basis": record.get("mapping_basis"),
        })

    target_display = target_relation + (f".{target_column}" if target_column else "")
    if target_relation and (not display or display[-1].casefold() != target_display.casefold()):
        display.append(target_display)
    return " → ".join(display), resolved


def list_source_fields(
    *,
    gateway: LineageGateway,
    source: RevisionBinding,
    source_object: str,
) -> list[str]:
    candidates = gateway.search_declared_objects(source, search=source_object, include_fields=True)
    source_obj = _exact_object(candidates, source_object)
    if source_obj is None:
        return []
    object_id = _text(source_obj.get("object_id")) or _text(source_obj.get("id"))
    if not object_id:
        return []
    context = gateway.get_data_model_object_context(source, object_id=object_id)
    names = [_text(row.get("name")) for row in _objects(context.get("fields"))]
    return list(dict.fromkeys(name for name in names if name))


def build_lineage(
    *,
    gateway: LineageGateway,
    source: RevisionBinding,
    tsa: RevisionBinding,
    profile: RevisionBinding,
    source_object: str,
    source_field: str,
) -> list[dict[str, Any]]:
    candidates = gateway.search_declared_objects(source, search=source_object, include_fields=True)
    source_obj = _exact_object(candidates, source_object)
    if source_obj is None:
        return [_gap_row(
            source=source, tsa=tsa, profile=profile,
            source_object=source_object, source_field=source_field,
            status="gap", gap="source_object_not_exactly_resolved",
        )]
    object_id = _text(source_obj.get("object_id")) or _text(source_obj.get("id"))
    source_fqcn = _text(source_obj.get("fqcn"))
    if not object_id or not source_fqcn:
        return [_gap_row(
            source=source, tsa=tsa, profile=profile,
            source_object=source_object, source_field=source_field,
            status="gap", gap="source_object_missing_identity",
        )]
    context = gateway.get_data_model_object_context(source, object_id=object_id)
    field = _field(context, source_field)
    if field is None:
        return [_gap_row(
            source=source, tsa=tsa, profile=profile,
            source_object=source_fqcn, source_field=source_field,
            status="gap", gap="source_field_not_exactly_resolved",
        )]
    source_path = _source_attribute_path(
        context, source_object=source_obj, source_type=source_fqcn, source_field=source_field
    )

    mapping_records = list(gateway.find_tsa_field_mappings(
        tsa,
        logical_type_name=source_fqcn,
        logical_field_name=source_field,
    ))
    if len(mapping_records) != 1:
        return [_gap_row(
            source=source, tsa=tsa, profile=profile,
            source_object=source_fqcn, source_field=source_field,
            status="ambiguity" if len(mapping_records) > 1 else "gap",
            gap="tsa_field_mapping_ambiguous" if len(mapping_records) > 1 else "tsa_field_mapping_not_found",
        )]
    tsa_record = dict(mapping_records[0])
    tsa_payload = _tsa_payload(tsa_record)
    replica_relation = _text(tsa_payload.get("physical_table_name"))
    replica_column = _text(tsa_payload.get("physical_column_name"))
    mapping_status = _text(tsa_payload.get("mapping_status"))
    mapping_basis = _text(tsa_payload.get("mapping_basis"))
    if not replica_relation or not replica_column or mapping_status != "observed_exact":
        return [_gap_row(
            source=source, tsa=tsa, profile=profile,
            source_object=source_fqcn, source_field=source_field,
            status="gap", gap="tsa_mapping_not_observed_exact",
        )]

    relation_hints = [replica_relation, replica_relation + "_hist", replica_relation + "_delta"]
    target_payload = gateway.find_sql_target_candidates(
        profile,
        source_relations=relation_hints,
        source_column=replica_column,
    )
    target_candidates = _objects(target_payload.get("candidates"))
    if not target_candidates:
        return [_gap_row(
            source=source, tsa=tsa, profile=profile,
            source_object=source_fqcn, source_field=source_field,
            status="gap", gap="profile_target_candidate_not_found",
        )]

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    source_provenance = _provenance_from_context(context, field)
    materializations = _materialization_index(gateway.list_sql_relation_materializations(profile))
    for target_candidate in target_candidates:
        if not _candidate_has_exact_source_evidence(
            target_candidate, replica_relation=replica_relation, replica_column=replica_column
        ):
            continue
        logical_target = _text(target_candidate.get("logical_target_name"))
        if not logical_target:
            continue
        repo_id = _text(target_candidate.get("repo_id")) or None
        lineage = gateway.get_sql_target_column_lineage(
            profile,
            target_relation=logical_target,
            repo_id=repo_id,
        )
        lineage_items = _objects(lineage.get("items"))
        matching: list[tuple[dict[str, Any], str]] = []
        has_base_anchor = False
        for item in lineage_items:
            if _text(item.get("lineage_status")).casefold() != "confirmed":
                continue
            if _text(item.get("terminal_column")).casefold() != replica_column.casefold():
                continue
            variant = _representation_variant(replica_relation, _text(item.get("terminal_relation_name")))
            if variant is None:
                continue
            if variant == "base":
                has_base_anchor = True
            matching.append((item, variant))
        if not matching:
            continue
        recommended_target, physical_candidates, physical_status = _physical_target_state(lineage)
        target_resolution_gap = ""
        if physical_candidates and len(set(physical_candidates)) > 1:
            target_resolution_gap = "physical_target_relation_ambiguous"
        elif physical_status and physical_status not in {"confirmed_unique", "resolved", "confirmed"}:
            target_resolution_gap = f"physical_target_relation_{physical_status}"

        for item, variant in matching:
            if variant in {"hist", "delta"} and not has_base_anchor:
                continue
            target_column = _text(item.get("target_column"))
            logical_target_relation = (
                _text(item.get("target_relation_name"))
                or _text(item.get("workflow_target_logical_name"))
                or logical_target
            )
            # Preserve the public resolver's ranked physical recommendation as
            # the consumer-visible destination, but never silently upgrade its
            # epistemic status: ambiguity remains explicit in status/gap and the
            # full candidate set remains in provenance.
            target_relation = recommended_target or logical_target_relation
            terminal_relation = _text(item.get("terminal_relation_name"))
            lineage_id = _text(item.get("sql_recursive_column_lineage_id"))
            branch_identity = lineage_id or json.dumps(
                item.get("branch_path_json") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            key = (
                target_relation.casefold(), target_column.casefold(), terminal_relation.casefold(), variant, branch_identity
            )
            if key in seen:
                continue
            seen.add(key)
            transformations = _path_expressions(item)
            relation_path, resolved_materializations = _resolved_relation_path(
                item,
                materializations=materializations,
                target_relation=target_relation,
                target_column=target_column,
            )
            path_segments = [
                {
                    "kind": "ucp_declared_field",
                    "system_id": source.system_id,
                    "revision_id": source.revision_id,
                    "type_fqcn": source_fqcn,
                    "field": source_field,
                    "attribute_path": source_path,
                },
                {
                    "kind": "ucp_to_tsa_exact_mapping",
                    "system_id": tsa.system_id,
                    "revision_id": tsa.revision_id,
                    "logical_type_name": source_fqcn,
                    "logical_field_name": source_field,
                    "physical_table_name": replica_relation,
                    "physical_column_name": replica_column,
                    "mapping_status": mapping_status,
                    "mapping_basis": mapping_basis,
                },
                {
                    "kind": "profile_sql_lineage",
                    "system_id": profile.system_id,
                    "revision_id": profile.revision_id,
                    "logical_target": logical_target,
                    "logical_target_relation": logical_target_relation,
                    "target_relation": target_relation,
                    "target_column": target_column,
                    "terminal_relation": terminal_relation,
                    "terminal_column": replica_column,
                    "representation_variant": variant,
                    "recursion_depth": item.get("recursion_depth"),
                    "branch_path": item.get("branch_path_json") or [],
                    "resolved_materializations": resolved_materializations,
                    "relation_path": relation_path,
                    "transformation_path": item.get("transformation_path_json") or [],
                    "lineage_status": item.get("lineage_status"),
                    "lineage_id": lineage_id or None,
                },
            ]
            provenance = {
                "ucp": source_provenance,
                "tsa": {
                    "local_id": tsa_record.get("local_id"),
                    "source_refs": tsa_payload.get("source_refs") or tsa_payload.get("source_refs_json") or [],
                    "record": tsa_record,
                },
                "profile": {
                    "repo_id": repo_id,
                    "evidence": item.get("evidence_json") or [],
                    "mapping_basis": item.get("mapping_basis"),
                    "target_resolution": lineage.get("target_resolution") or {},
                    "target_candidate": {
                        "rank": target_candidate.get("rank"),
                        "score": target_candidate.get("score"),
                        "reasons": target_candidate.get("reasons") or [],
                        "consumer_surface": target_candidate.get("consumer_surface") or {},
                    },
                    "recommended_target_relation": recommended_target,
                    "physical_relation_candidates": physical_candidates,
                    "materializations": resolved_materializations,
                },
            }
            rows.append({
                "source_system_id": source.system_id,
                "source_revision_id": source.revision_id,
                "source_root_object": source_object,
                "source_attribute_path": source_path,
                "source_type_fqcn": source_fqcn,
                "source_field": source_field,
                "tsa_system_id": tsa.system_id,
                "tsa_revision_id": tsa.revision_id,
                "tsa_mapping_status": mapping_status,
                "tsa_mapping_basis": mapping_basis,
                "replica_relation": replica_relation,
                "replica_column": replica_column,
                "profile_system_id": profile.system_id,
                "profile_revision_id": profile.revision_id,
                "profile_source_relation": terminal_relation,
                "profile_source_column": replica_column,
                "profile_representation_variant": variant,
                "target_relation": target_relation,
                "target_column": target_column,
                "relation_path": relation_path,
                "lineage_depth": item.get("recursion_depth") or "",
                "transformation_path": " → ".join(transformations),
                "path_segments_json": json.dumps(path_segments, ensure_ascii=False, separators=(",", ":")),
                "status": "confirmed" if not target_resolution_gap else "confirmed_lineage_target_relation_ambiguous",
                "gap": target_resolution_gap,
                "provenance_json": json.dumps(provenance, ensure_ascii=False, separators=(",", ":")),
            })

    if rows:
        return sorted(rows, key=lambda row: (
            row["target_relation"].casefold(),
            row["target_column"].casefold(),
            _ALLOWED_VARIANTS.index(row["profile_representation_variant"]),
            row["profile_source_relation"].casefold(),
        ))
    return [_gap_row(
        source=source, tsa=tsa, profile=profile,
        source_object=source_fqcn, source_field=source_field,
        status="gap", gap="profile_confirmed_lineage_not_found",
    )]
