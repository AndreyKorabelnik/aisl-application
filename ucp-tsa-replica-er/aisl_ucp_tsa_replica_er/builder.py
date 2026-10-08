from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Any, Iterable, Mapping, Sequence

from .contracts import RevisionBinding


_KEY_ANNOTATIONS: dict[str, tuple[str, str]] = {
    "MetaEntity": ("id", "entity_id"),
    "MetaRootEntity": ("id", "root_entity_id"),
    "MetaVersionedEntity": ("id", "versioned_entity_id"),
    "MetaDictionary": ("code", "dictionary_code"),
    "MetaVersionedDictionary": ("code", "versioned_dictionary_code"),
}

_UNRESOLVED_RELATION_STATUSES = {"", "unresolved", "ambiguous", "not_found", "not_resolved"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else dict(record)


def _annotation_args(annotation: Mapping[str, Any]) -> dict[str, str]:
    raw_args = annotation.get("structured_arguments")
    if raw_args is None:
        raw_args = annotation.get("structured_arguments_json")
    args = _json(raw_args, [])
    result: dict[str, str] = {}
    if not isinstance(args, list):
        return result
    for raw in args:
        if not isinstance(raw, Mapping):
            continue
        name = _text(raw.get("name")) or "value"
        tree = raw.get("expression_tree") if isinstance(raw.get("expression_tree"), Mapping) else {}
        value = _text(tree.get("literal_value"))
        if not value:
            value = _text(raw.get("literal_value"))
        if not value:
            text = _text(raw.get("raw"))
            if len(text) >= 2 and text[0] == text[-1] == '"':
                value = text[1:-1]
        if value:
            result[name] = value
    return result


def _record_provenance(record: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("source_ref", "source_ref_json", "provenance", "provenance_json", "local_id"):
        value = record.get(name)
        if value not in (None, "", [], {}):
            result[name] = _json(value, value)
    payload = record.get("payload")
    if isinstance(payload, Mapping) and payload.get("source_refs"):
        result["source_refs"] = payload.get("source_refs")
    return result


def _unique_payloads(records: Iterable[Mapping[str, Any]], *, status: str = "observed_exact") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        payload = _payload(record)
        if _text(payload.get("mapping_status")) == status:
            result.append({"record": dict(record), "payload": payload})
    return result


def _resolve_root_types(
    roots: Sequence[str],
    *,
    types_by_id: Mapping[str, Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
) -> set[str]:
    if not roots:
        return set(types_by_id)
    by_fqcn: dict[str, list[str]] = defaultdict(list)
    by_simple: dict[str, list[str]] = defaultdict(list)
    for type_id, row in types_by_id.items():
        fqcn = _text(row.get("fully_qualified_name"))
        simple = _text(row.get("simple_name"))
        if fqcn:
            by_fqcn[fqcn.casefold()].append(type_id)
        if simple:
            by_simple[simple.casefold()].append(type_id)
    seeds: list[str] = []
    for root in roots:
        needle = root.strip().casefold()
        matches = by_fqcn.get(needle) or by_simple.get(needle) or []
        if len(matches) != 1:
            raise ValueError(f"root object must resolve exactly once: {root!r}; got {len(matches)}")
        seeds.append(matches[0])
    outgoing: dict[str, list[str]] = defaultdict(list)
    for rel in relationships:
        src = _text(rel.get("source_type_occurrence_id"))
        dst = _text(rel.get("target_type_occurrence_id"))
        if src and dst and _text(rel.get("resolution_status")).casefold() not in _UNRESOLVED_RELATION_STATUSES:
            outgoing[src].append(dst)
    selected: set[str] = set(seeds)
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        for target in outgoing.get(current, ()):
            if target not in selected:
                selected.add(target)
                queue.append(target)
    return selected


def build_replica_model(
    *,
    ucp: RevisionBinding,
    tsa: RevisionBinding,
    ucp_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    tsa_mappings: Mapping[str, Sequence[Mapping[str, Any]]],
    root_objects: Sequence[str] = (),
) -> dict[str, Any]:
    types = [dict(row) for row in ucp_dataset.get("types") or ()]
    fields = [dict(row) for row in ucp_dataset.get("fields") or ()]
    effective_fields = [dict(row) for row in ucp_dataset.get("effective_fields") or ()]
    relationships = [dict(row) for row in ucp_dataset.get("relationships") or ()]
    annotations = [dict(row) for row in ucp_dataset.get("annotations") or ()]

    types_by_id = {
        _text(row.get("type_occurrence_id")): row
        for row in types
        if _text(row.get("type_occurrence_id")) and _text(row.get("fully_qualified_name"))
    }
    selected_type_ids = _resolve_root_types(
        root_objects, types_by_id=types_by_id, relationships=relationships
    )
    fields_by_id = {
        _text(row.get("field_occurrence_id")): row
        for row in fields
        if _text(row.get("field_occurrence_id"))
    }
    effective_names: dict[str, set[str]] = defaultdict(set)
    for row in effective_fields:
        owner = _text(row.get("effective_owner_type_occurrence_id"))
        name = _text(row.get("field_name"))
        if owner and name:
            effective_names[owner].add(name)

    # A public effective-field occurrence is the exact bridge from a replica's
    # logical owner to a declared field, including inherited field declarations.
    effective_by_owner_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in effective_fields:
        owner = _text(row.get("effective_owner_type_occurrence_id"))
        name = _text(row.get("field_name"))
        field_id = _text(row.get("field_occurrence_id"))
        if owner and name and field_id:
            effective_by_owner_name[(owner, name)].add(field_id)
    direct_by_owner_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for field_id, row in fields_by_id.items():
        owner = _text(row.get("owner_type_occurrence_id"))
        name = _text(row.get("name"))
        if owner and name:
            direct_by_owner_name[(owner, name)].add(field_id)

    annotations_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in annotations:
        if _text(row.get("target_kind")) != "type":
            continue
        target = _text(row.get("target_occurrence_id"))
        if target:
            annotations_by_type[target].append(row)

    entity_by_fqcn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for wrapped in _unique_payloads(tsa_mappings.get("entity_mappings") or ()):
        fqcn = _text(wrapped["payload"].get("logical_type_name"))
        if fqcn:
            entity_by_fqcn[fqcn].append(wrapped)

    fields_by_fqcn_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for wrapped in _unique_payloads(tsa_mappings.get("field_mappings") or ()):
        payload = wrapped["payload"]
        fqcn = _text(payload.get("logical_type_name"))
        name = _text(payload.get("logical_field_name"))
        if fqcn and name:
            fields_by_fqcn_name[(fqcn, name)].append(wrapped)

    gaps: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    table_by_type_id: dict[str, dict[str, Any]] = {}
    replica_fields: list[dict[str, Any]] = []

    for type_id in sorted(selected_type_ids, key=lambda value: _text(types_by_id.get(value, {}).get("fully_qualified_name"))):
        type_row = types_by_id.get(type_id)
        if not type_row:
            continue
        fqcn = _text(type_row.get("fully_qualified_name"))
        entity_matches = entity_by_fqcn.get(fqcn, [])
        if len(entity_matches) != 1:
            if entity_matches:
                gaps.append({
                    "kind": "tsa_entity_mapping_ambiguous",
                    "logical_type_fqcn": fqcn,
                    "candidate_count": len(entity_matches),
                })
            continue
        entity = entity_matches[0]
        entity_payload = entity["payload"]
        replica_relation = _text(entity_payload.get("physical_table_name"))
        if not replica_relation:
            gaps.append({"kind": "tsa_entity_mapping_missing_table", "logical_type_fqcn": fqcn})
            continue

        key_annotations = [
            annotation
            for annotation in annotations_by_type.get(type_id, ())
            if _text(annotation.get("annotation_name")) in _KEY_ANNOTATIONS
        ]
        key_kind = ""
        key_annotation = ""
        key_logical_fields: list[str] = []
        key_replica_columns: list[str] = []
        key_status = "gap"
        key_gap = "ucp_identity_annotation_not_observed"
        version_logical_field = ""
        version_replica_column = ""
        collocation_logical_field = ""
        collocation_replica_column = ""
        key_provenance: list[dict[str, Any]] = []

        if len(key_annotations) == 1:
            annotation = key_annotations[0]
            key_annotation = _text(annotation.get("annotation_name"))
            arg_name, key_kind = _KEY_ANNOTATIONS[key_annotation]
            args = _annotation_args(annotation)
            key_field = _text(args.get(arg_name))
            version_logical_field = _text(args.get("version"))
            collocation_logical_field = _text(args.get("collocationId"))
            key_provenance.append({"ucp_annotation": _record_provenance(annotation), "arguments": args})
            if not key_field:
                key_gap = "ucp_identity_annotation_has_no_literal_key_field"
            elif effective_names.get(type_id) and key_field not in effective_names[type_id]:
                key_gap = "ucp_identity_field_not_in_effective_fields"
                key_logical_fields = [key_field]
            else:
                key_logical_fields = [key_field]
                mapping_matches = fields_by_fqcn_name.get((fqcn, key_field), [])
                exact_for_entity = [
                    item for item in mapping_matches
                    if _text(item["payload"].get("entity_mapping_id")) == _text(entity_payload.get("mapping_id"))
                ]
                if len(exact_for_entity) == 1:
                    key_replica_columns = [_text(exact_for_entity[0]["payload"].get("physical_column_name"))]
                    if key_replica_columns[0]:
                        key_status = "confirmed_declared_identity_mapped"
                        key_gap = ""
                        key_provenance.append({"tsa_key_mapping": _record_provenance(exact_for_entity[0]["record"])})
                    else:
                        key_gap = "tsa_identity_mapping_missing_physical_column"
                elif len(exact_for_entity) > 1:
                    key_gap = "tsa_identity_field_mapping_ambiguous"
                else:
                    key_gap = "tsa_identity_field_mapping_not_found"

            for logical_name, target_name in (
                (version_logical_field, "version_replica_column"),
                (collocation_logical_field, "collocation_replica_column"),
            ):
                if not logical_name:
                    continue
                matches = [
                    item for item in fields_by_fqcn_name.get((fqcn, logical_name), [])
                    if _text(item["payload"].get("entity_mapping_id")) == _text(entity_payload.get("mapping_id"))
                ]
                if len(matches) == 1:
                    column = _text(matches[0]["payload"].get("physical_column_name"))
                    if target_name == "version_replica_column":
                        version_replica_column = column
                    else:
                        collocation_replica_column = column
        elif len(key_annotations) > 1:
            key_gap = "multiple_ucp_identity_annotations"

        table = {
            "logical_type_fqcn": fqcn,
            "logical_type_name": _text(type_row.get("simple_name")),
            "replica_relation": replica_relation,
            "key_kind": key_kind,
            "key_annotation": key_annotation,
            "key_logical_fields": key_logical_fields,
            "key_replica_columns": key_replica_columns,
            "key_status": key_status,
            "key_gap": key_gap,
            "version_logical_field": version_logical_field,
            "version_replica_column": version_replica_column,
            "collocation_logical_field": collocation_logical_field,
            "collocation_replica_column": collocation_replica_column,
            "physical_constraint_status": "not_observed",
            "physical_constraint_gap": "database_primary_key_constraint_not_published",
            "provenance": {
                "ucp_type": _record_provenance(type_row),
                "tsa_entity_mapping": _record_provenance(entity["record"]),
                "key": key_provenance,
            },
        }
        # Field list is driven by observed_exact TSA field mappings, not by
        # guessed physical columns or by all UCP fields (which might not be replicated).
        entity_mapping_id = _text(entity_payload.get("mapping_id"))
        mapped_fields = [
            wrapped for wrapped in _unique_payloads(tsa_mappings.get("field_mappings") or ())
            if _text(wrapped["payload"].get("entity_mapping_id")) == entity_mapping_id
            and _text(wrapped["payload"].get("logical_type_name")) == fqcn
        ]
        column_fields: dict[str, set[str]] = defaultdict(set)
        for mapped in mapped_fields:
            column = _text(mapped["payload"].get("physical_column_name"))
            name = _text(mapped["payload"].get("logical_field_name"))
            if column and name:
                column_fields[column].add(name)
        seen_pairs: set[tuple[str, str]] = set()
        for mapped in sorted(mapped_fields, key=lambda item: (
            _text(item["payload"].get("physical_column_name")),
            _text(item["payload"].get("logical_field_name")),
            _text(item["payload"].get("mapping_id")),
        )):
            source = mapped["payload"]
            field_name = _text(source.get("logical_field_name"))
            column = _text(source.get("physical_column_name"))
            if not column or not field_name:
                # Do not invent either physical or logical identity.
                continue
            if (column, field_name) in seen_pairs:
                continue
            seen_pairs.add((column, field_name))
            ambiguous_column = len(column_fields[column]) > 1
            effective_ids = effective_by_owner_name.get((type_id, field_name), set())
            candidate_ids = effective_ids if effective_ids else direct_by_owner_name.get((type_id, field_name), set())
            candidates = [fields_by_id[fid] for fid in sorted(candidate_ids) if fid in fields_by_id]
            field_row = candidates[0] if len(candidates) == 1 else None
            document = field_row.get("documentation") if field_row else None
            if not isinstance(document, Mapping):
                document = _json(field_row.get("documentation_json"), {}) if field_row else {}
            doc = document if isinstance(document, Mapping) else {}
            description = doc.get("description") if isinstance(doc.get("description"), str) else ""
            type_document = type_row.get("documentation")
            if not isinstance(type_document, Mapping):
                type_document = _json(type_row.get("documentation_json"), {})
            type_description = type_document.get("description") if isinstance(type_document, Mapping) else ""
            if not isinstance(type_description, str):
                type_description = ""
            status = "confirmed" if field_row and description.strip() else (
                "ucp_description_not_published" if field_row else
                "ucp_field_ambiguous" if len(candidates) > 1 else "ucp_field_not_found"
            )
            gap = (
                "tsa_column_mapping_ambiguous" if ambiguous_column else
                "" if status == "confirmed" else status
            )
            replica_fields.append({
                "replica_relation": replica_relation,
                "replica_column": column,
                "ucp_type_fqcn": fqcn,
                "ucp_type_description": type_description,
                "ucp_field": field_name,
                "ucp_field_type": _text(field_row.get("declared_type_expression")) if field_row else "",
                "ucp_field_description": description,
                "description_status": status,
                "mapping_status": "ambiguous_multiple_ucp_fields" if ambiguous_column else "observed_exact",
                "gap": gap,
                "provenance": {
                    "ucp_type": _record_provenance(type_row),
                    "ucp_field": _record_provenance(field_row) if field_row else {},
                    "tsa_field_mapping": _record_provenance(mapped["record"]),
                },
            })
        tables.append(table)
        table_by_type_id[type_id] = table

    relation_rows: list[dict[str, Any]] = []
    for relationship in relationships:
        source_id = _text(relationship.get("source_type_occurrence_id"))
        target_id = _text(relationship.get("target_type_occurrence_id"))
        if source_id not in selected_type_ids or target_id not in selected_type_ids:
            continue
        source_table = table_by_type_id.get(source_id)
        target_table = table_by_type_id.get(target_id)
        if not source_table or not target_table:
            continue
        resolution_status = _text(relationship.get("resolution_status"))
        if resolution_status.casefold() in _UNRESOLVED_RELATION_STATUSES:
            continue
        field = fields_by_id.get(_text(relationship.get("field_occurrence_id"))) or {}
        relationship_field = _text(field.get("name"))
        declared_type_expression = _text(field.get("declared_type_expression"))
        source_key_columns = list(source_table.get("key_replica_columns") or ())
        target_key_columns = list(target_table.get("key_replica_columns") or ())
        relation_gap = "physical_fk_join_not_observed"
        relation_rows.append({
            "source_type_fqcn": source_table["logical_type_fqcn"],
            "source_replica_relation": source_table["replica_relation"],
            "source_key_columns": source_key_columns,
            "source_key_status": source_table["key_status"],
            "relationship_field": relationship_field,
            "declared_type_expression": declared_type_expression,
            "relationship_kind": _text(relationship.get("relationship_kind")),
            "ucp_resolution_status": resolution_status,
            "target_type_fqcn": target_table["logical_type_fqcn"],
            "target_replica_relation": target_table["replica_relation"],
            "target_key_columns": target_key_columns,
            "target_key_status": target_table["key_status"],
            "physical_join_status": "not_observed",
            "physical_join_condition": "",
            "status": "confirmed_ucp_relationship_projected_to_replicas",
            "gap": relation_gap,
            "provenance": {
                "ucp_relationship": _record_provenance(relationship),
                "ucp_field": _record_provenance(field),
            },
        })

    tables.sort(key=lambda row: (row["replica_relation"], row["logical_type_fqcn"]))
    replica_fields.sort(key=lambda row: (row["replica_relation"], row["replica_column"], row["ucp_type_fqcn"], row["ucp_field"]))
    relation_rows.sort(key=lambda row: (
        row["source_replica_relation"], row["relationship_field"], row["target_replica_relation"]
    ))
    return {
        "schema_version": "ucp-tsa-replica-er/v1",
        "ucp_binding": {"system_id": ucp.system_id, "revision_id": ucp.revision_id},
        "tsa_binding": {"system_id": tsa.system_id, "revision_id": tsa.revision_id},
        "root_objects": list(root_objects),
        "semantics": {
            "table_identity": "exact TSA entity_mapping with mapping_status=observed_exact",
            "replica_key": "UCP declared identity argument mapped through exact TSA field_mapping; not proof of a database PK constraint",
            "relationship": "resolved UCP declared type relationship whose source and target types both have exact TSA replica mappings",
            "physical_join": "not claimed unless independently published; v1 emits not_observed",
        },
        "counts": {
            "selected_ucp_types": len(selected_type_ids),
            "replica_tables": len(tables),
            "relationships": len(relation_rows),
            "tables_with_confirmed_declared_key_mapping": sum(1 for row in tables if row["key_status"] == "confirmed_declared_identity_mapped"),
            "table_key_gaps": sum(1 for row in tables if row["key_status"] != "confirmed_declared_identity_mapped"),
            "relationships_with_physical_join_gap": sum(1 for row in relation_rows if row["physical_join_status"] == "not_observed"),
            "mapping_gaps": len(gaps),
        },
        "tables": tables,
        "replica_fields": replica_fields,
        "relationships": relation_rows,
        "gaps": gaps,
    }


def mermaid_flowchart(payload: Mapping[str, Any]) -> str:
    tables = [dict(row) for row in payload.get("tables") or () if isinstance(row, Mapping)]
    relationships = [dict(row) for row in payload.get("relationships") or () if isinstance(row, Mapping)]
    ids: dict[str, str] = {}
    lines = ["flowchart LR"]
    for table in tables:
        relation = _text(table.get("replica_relation"))
        if not relation:
            continue
        node_id = "T_" + hashlib.sha1(relation.encode("utf-8")).hexdigest()[:10]
        ids[relation] = node_id
        keys = ", ".join(str(v) for v in table.get("key_replica_columns") or ()) or "?"
        key_state = _text(table.get("key_status"))
        label = f"{relation}\\nUCP key: {keys}\\n{key_state}"
        lines.append(f'  {node_id}["{label.replace(chr(34), chr(39))}"]')
    for row in relationships:
        source = _text(row.get("source_replica_relation"))
        target = _text(row.get("target_replica_relation"))
        if source not in ids or target not in ids:
            continue
        label = _text(row.get("relationship_field")) or _text(row.get("relationship_kind"))
        lines.append(f'  {ids[source]} -->|"{label.replace(chr(34), chr(39))}"| {ids[target]}')
    lines.append("")
    lines.append("%% UCP key = declared UCP identity mapped to TSA column; it is not proof of a DB PK constraint.")
    lines.append("%% Edges are UCP declared relationships projected onto exact TSA replica tables; physical FK join is not asserted.")
    return "\n".join(lines) + "\n"
