from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from .aisl import AislPathGateway
from .contracts import BindingIndex, OUTPUT_FORMAT
from .topology import (
    BoundaryField,
    boundary_fields,
    expected_interface_direction,
    local_payload_binding_symbols,
    route_boundary_ref,
    select_edge,
    wire_display_ref,
)


def _fingerprint(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("result")
    return value if isinstance(value, Mapping) else payload


def _candidate_rows(result: Mapping[str, Any], *, repository_id: str) -> list[Mapping[str, Any]]:
    rows = result.get("source_candidates")
    if not isinstance(rows, list):
        return []
    return [
        item for item in rows
        if isinstance(item, Mapping) and str(item.get("repo_id") or "") == repository_id
    ]


def _anchor_candidate_by_interface(
    result: Mapping[str, Any],
    *,
    repository_id: str,
    interface_ids: Sequence[str],
) -> Mapping[str, Any] | None:
    allowed = set(interface_ids)
    matches = [item for item in _candidate_rows(result, repository_id=repository_id) if str(item.get("owner_ref") or "") in allowed]
    return matches[0] if len(matches) == 1 else None


def _anchor_candidate_by_transport(
    result: Mapping[str, Any],
    *,
    edge: Mapping[str, Any],
    repository_id: str,
    transport_role: str,
) -> Mapping[str, Any] | None:
    protocol = str(edge.get("protocol") or "").strip().casefold()
    endpoint = str(edge.get("matched_identity") or "").strip()
    method = str(edge.get("method") or "").strip().upper()
    role = str(transport_role or "").strip().casefold()
    interface_direction = expected_interface_direction(edge, repository_id)
    if not protocol or not endpoint or role not in {"request", "response"} or interface_direction is None:
        return None

    matches: list[Mapping[str, Any]] = []
    for item in _candidate_rows(result, repository_id=repository_id):
        transport = item.get("transport")
        if not isinstance(transport, Mapping):
            continue
        if str(transport.get("protocol") or "").strip().casefold() != protocol:
            continue
        if str(transport.get("endpoint") or "").strip() != endpoint:
            continue
        if str(transport.get("payload_role") or "").strip().casefold() != role:
            continue
        if str(transport.get("interface_direction") or "").strip().casefold() != interface_direction:
            continue
        if protocol == "http" and method and str(transport.get("http_method") or "").strip().upper() != method:
            continue
        matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _operation_owner(item: Mapping[str, Any]) -> str:
    return str(item.get("operation") or "").split(".", 1)[0]


def _bean_accessors(payload_identity: str, field_path: str) -> set[str]:
    leaf = str(field_path or "").split(".")[-1]
    if not leaf:
        return set()
    suffix = leaf[0].upper() + leaf[1:]
    return {f"{payload_identity}.get{suffix}", f"{payload_identity}.is{suffix}"}


def _anchor_candidate_by_payload_owner(
    result: Mapping[str, Any],
    *,
    repository_id: str,
    payload_identity: str | None,
    field_path: str,
    direction: str,
) -> Mapping[str, Any] | None:
    payload = str(payload_identity or "").strip()
    if not payload:
        return None
    matches = [item for item in _candidate_rows(result, repository_id=repository_id) if _operation_owner(item) == payload]
    if len(matches) == 1:
        return matches[0]
    if direction == "forward" and matches:
        accessors = _bean_accessors(payload, field_path)
        getter_matches = [item for item in matches if str(item.get("operation") or "") in accessors]
        if len(getter_matches) == 1:
            return getter_matches[0]
    return None


def _iter_query_nodes(result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("source", "target"):
        value = result.get(key)
        if isinstance(value, Mapping):
            yield value
    for path in result.get("paths") or ():
        if not isinstance(path, Mapping):
            continue
        for key in ("start", "end"):
            value = path.get(key)
            if isinstance(value, Mapping):
                yield value
        for step in path.get("steps") or ():
            if not isinstance(step, Mapping):
                continue
            for key in ("source", "target"):
                value = step.get(key)
                if isinstance(value, Mapping):
                    yield value



_COLLECTION_DECLARED_TYPES = {
    "ArrayDeque",
    "ArrayList",
    "Collection",
    "ConcurrentHashMap",
    "CopyOnWriteArrayList",
    "Deque",
    "Entry",
    "HashMap",
    "HashSet",
    "Iterable",
    "LinkedHashMap",
    "LinkedHashSet",
    "LinkedList",
    "List",
    "Map",
    "Optional",
    "Queue",
    "Set",
    "Stream",
    "TreeMap",
    "TreeSet",
}


def _is_collection_declared_type(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    raw = text.split("<", 1)[0].strip()
    simple = raw.rsplit(".", 1)[-1]
    return simple in _COLLECTION_DECLARED_TYPES


def _plain_field_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith("new "):
        return False
    if any(marker in text for marker in ("(", ")", "\n", "\r", "?", ":", " ")):
        return False
    return all(part for part in text.split("."))


def _lower_initial(value: str) -> str:
    text = str(value or "")
    return text[:1].lower() + text[1:] if text else text


def _semantic_ref_parts(value: str) -> tuple[str, ...]:
    parts: list[str] = []
    for raw in str(value or "").split("."):
        part = raw.strip()
        if not part:
            continue
        if part.endswith("[]"):
            part = part[:-2]
        parts.append(_lower_initial(part))
    return tuple(parts)


def _common_suffix_parts(values: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    if not values:
        return ()
    shortest = min(len(value) for value in values)
    common = 0
    for size in range(1, shortest + 1):
        suffix = values[0][-size:]
        if all(value[-size:] == suffix for value in values[1:]):
            common = size
        else:
            break
    return values[0][-common:] if common else ()


def _target_semantic_projection(
    side: Mapping[str, Any],
    *,
    catalog: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Compose a human-facing semantic target chain from already-published paths.

    Repository value-flow may expose dozens of technically distinct continuations
    (handler calls, stream pipelines, return aliases) for the same nested data
    shape.  This consumer projection preserves the mechanically observed semantic
    nesting instead of flattening every terminal path into an OR-list.

    No new value-flow edge is created: every milestone below is backed by a node
    already present in at least one published target path and, where a type name
    is rendered, by the exact declared type of that node's observed object.
    """
    if str(side.get("anchor_status") or "") != "resolved":
        return None
    query = side.get("query") if isinstance(side.get("query"), Mapping) else {}
    result = _result(query)
    paths = [item for item in result.get("paths") or () if isinstance(item, Mapping)]
    if not paths:
        return None

    by_id = {
        str(item.get("value_node_id") or ""): item
        for item in catalog
        if str(item.get("value_node_id") or "")
    }
    by_occurrence: dict[str, list[Mapping[str, Any]]] = {}
    for item in catalog:
        occurrence_id = str(item.get("occurrence_id") or "")
        if occurrence_id:
            by_occurrence.setdefault(occurrence_id, []).append(item)

    def semantic_candidate(node: Mapping[str, Any]) -> dict[str, Any] | None:
        node_id = str(node.get("value_node_id") or "")
        catalog_node = by_id.get(node_id, node)
        if str(catalog_node.get("node_kind") or node.get("node_kind") or "") != "field":
            return None
        display_ref = str(catalog_node.get("display_ref") or node.get("display_ref") or "").strip()
        if not display_ref:
            return None
        occurrence = _source_occurrence(catalog_node)
        object_occurrence_id = str(occurrence.get("object_occurrence_id") or "")
        object_nodes = by_occurrence.get(object_occurrence_id, []) if object_occurrence_id else []
        typed_object_nodes = [
            item for item in object_nodes
            if _observed_type(item.get("type_ref") or _source_occurrence(item).get("declared_type"))
        ]
        object_node = typed_object_nodes[0] if len(typed_object_nodes) == 1 else None
        object_type = _observed_type(
            occurrence.get("object_declared_type")
            or (object_node.get("type_ref") if object_node is not None else "")
            or (_source_occurrence(object_node).get("declared_type") if object_node is not None else "")
        )
        object_display = str(object_node.get("display_ref") or "").strip() if object_node is not None else ""
        projected_tail = str(occurrence.get("projected_field_tail") or occurrence.get("property_name") or "").strip()

        semantic_ref = ""
        is_collection = _is_collection_declared_type(object_type)
        if object_type and object_display and display_ref.startswith(object_display + "."):
            suffix = display_ref[len(object_display) + 1 :]
            if is_collection:
                semantic_ref = f"{object_display}[].{suffix}"
            else:
                semantic_ref = f"{object_type}.{suffix}"
        elif object_type and display_ref.startswith(f"new {object_type}."):
            semantic_ref = display_ref[len("new ") :]
        elif object_type and projected_tail and "." not in display_ref:
            semantic_ref = f"{object_type}.{projected_tail}"
        elif _plain_field_path(display_ref):
            semantic_ref = display_ref

        if not semantic_ref or not _plain_field_path(semantic_ref.replace("[]", "")):
            return None
        return {
            "value_node_id": node_id,
            "display_ref": display_ref,
            "semantic_ref": semantic_ref,
            "object_declared_type": object_type,
            "collection": is_collection,
            "operation": str(catalog_node.get("operation") or node.get("operation") or ""),
            "source_path": str(catalog_node.get("source_path") or node.get("source_path") or ""),
        }

    path_candidates: list[list[dict[str, Any]]] = []
    all_candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for path in paths:
        nodes: list[Mapping[str, Any]] = []
        start = path.get("start")
        if isinstance(start, Mapping):
            nodes.append(start)
        for step in path.get("steps") or ():
            if not isinstance(step, Mapping):
                continue
            target = step.get("target")
            if isinstance(target, Mapping):
                nodes.append(target)
        end = path.get("end")
        if isinstance(end, Mapping):
            nodes.append(end)

        semantic_nodes: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for node in nodes:
            candidate = semantic_candidate(node)
            if candidate is None:
                continue
            ref = str(candidate["semantic_ref"])
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            semantic_nodes.append(candidate)
            all_candidates[(ref, str(candidate.get("value_node_id") or ""))] = candidate
        if semantic_nodes:
            path_candidates.append(semantic_nodes)

    if not path_candidates:
        return None

    anchor_ref = str((side.get("resolved_anchor") or {}).get("display_ref") or "").strip()
    entry_refs: list[str] = []
    entry_candidates: dict[str, dict[str, Any]] = {}
    for candidates in path_candidates:
        # Technical/local aliases immediately after the interaction boundary may
        # be untyped (for example ``identifications.documentNumber``).  They must
        # not prevent us from preserving a later, mechanically typed semantic
        # consumer such as ``IdentityCard.idNum``.  Select the first *typed*
        # non-collection field per observed path and require all such paths to
        # agree on the same semantic entry point.
        entry = next(
            (
                item for item in candidates
                if str(item.get("display_ref") or "") != anchor_ref
                and str(item.get("semantic_ref") or "") != anchor_ref
                and str(item.get("object_declared_type") or "").strip()
                and not bool(item.get("collection"))
            ),
            None,
        )
        if entry is None:
            continue
        ref = str(entry["semantic_ref"])
        entry_refs.append(ref)
        entry_candidates.setdefault(ref, entry)
    unique_entry = sorted(set(entry_refs))
    if len(unique_entry) != 1:
        return None
    consumer_ref = unique_entry[0]
    consumer = entry_candidates[consumer_ref]

    # Build the longest exact structural nesting ladder.  Collection/container
    # aliases are excluded from the ladder so technical processing lists do not
    # masquerade as domain nesting.
    semantic_unique: dict[str, dict[str, Any]] = {}
    for candidate in all_candidates.values():
        ref = str(candidate["semantic_ref"])
        current = semantic_unique.get(ref)
        if current is None or (
            bool(current.get("object_declared_type")) is False
            and bool(candidate.get("object_declared_type")) is True
        ):
            semantic_unique[ref] = candidate

    chain: list[dict[str, Any]] = [consumer]
    current_ref = consumer_ref
    current_parts = _semantic_ref_parts(current_ref)
    while current_parts:
        seen_chain = {str(item.get("semantic_ref") or "") for item in chain}
        matches = []
        for candidate in semantic_unique.values():
            ref = str(candidate.get("semantic_ref") or "")
            if bool(candidate.get("collection")) or ref in seen_chain:
                continue
            parts = _semantic_ref_parts(ref)
            if len(parts) <= len(current_parts):
                continue
            if parts[-len(current_parts):] != current_parts:
                continue
            matches.append(candidate)
        if not matches:
            break
        # Prefer the closest *observed* deeper suffix.  This permits projection
        # to skip an unpublished intermediate presentation node (e.g. no typed
        # CardAcctId node) without inventing a value-flow edge.
        min_depth = min(len(_semantic_ref_parts(str(item.get("semantic_ref") or ""))) for item in matches)
        matches = [
            item for item in matches
            if len(_semantic_ref_parts(str(item.get("semantic_ref") or ""))) == min_depth
        ]
        matches.sort(
            key=lambda item: (
                0 if str(item.get("object_declared_type") or "") else 1,
                len(str(item.get("semantic_ref") or "")),
                str(item.get("semantic_ref") or ""),
            )
        )
        best = matches[0]
        # If two different semantic refs have the same structural rank and the
        # ranking cannot distinguish them mechanically, stop rather than guess.
        best_key = (
            0 if str(best.get("object_declared_type") or "") else 1,
            len(str(best.get("semantic_ref") or "")),
        )
        tied = [
            item for item in matches
            if (
                0 if str(item.get("object_declared_type") or "") else 1,
                len(str(item.get("semantic_ref") or "")),
            ) == best_key
        ]
        if len({str(item.get("semantic_ref") or "") for item in tied}) > 1:
            break
        chain.append(best)
        current_ref = str(best["semantic_ref"])
        current_parts = _semantic_ref_parts(current_ref)

    deepest = chain[-1]
    deepest_parts = _semantic_ref_parts(str(deepest.get("semantic_ref") or ""))
    if len(deepest_parts) >= 2:
        deepest_tail = deepest_parts[1:]
        # Preserve an observed same-shape type transition (for example a proxy
        # DTO mapping) only when exactly one typed alternative is present.
        typed_alternatives = [
            candidate for candidate in semantic_unique.values()
            if not bool(candidate.get("collection"))
            and candidate.get("object_declared_type")
            and _semantic_ref_parts(str(candidate.get("semantic_ref") or ""))[1:] == deepest_tail
            and len(_semantic_ref_parts(str(candidate.get("semantic_ref") or ""))) == len(deepest_parts)
            and _semantic_ref_parts(str(candidate.get("semantic_ref") or ""))[0] != deepest_parts[0]
        ]
        alt_refs = sorted({str(item.get("semantic_ref") or "") for item in typed_alternatives})
        if len(alt_refs) == 1:
            chain.append(next(item for item in typed_alternatives if str(item.get("semantic_ref") or "") == alt_refs[0]))

        collection_candidates = []
        for candidate in semantic_unique.values():
            if not bool(candidate.get("collection")):
                continue
            parts = _semantic_ref_parts(str(candidate.get("semantic_ref") or ""))
            if len(parts) < len(deepest_parts):
                continue
            # Same-shape collection alias (records[]....) or the closest
            # deeper observed collection wrapper whose suffix is the semantic
            # chain already proven above.
            if len(parts) == len(deepest_parts):
                if parts[1:] != deepest_tail:
                    continue
            elif parts[-len(deepest_parts):] != deepest_parts:
                continue
            collection_candidates.append(candidate)
        if collection_candidates:
            min_collection_depth = min(
                len(_semantic_ref_parts(str(item.get("semantic_ref") or "")))
                for item in collection_candidates
            )
            nearest = [
                item for item in collection_candidates
                if len(_semantic_ref_parts(str(item.get("semantic_ref") or ""))) == min_collection_depth
            ]
            collection_refs = sorted({str(item.get("semantic_ref") or "") for item in nearest})
            if len(collection_refs) == 1:
                chain.append(next(item for item in nearest if str(item.get("semantic_ref") or "") == collection_refs[0]))
            elif collection_refs:
                # Several local collection variables may carry the same nested
                # payload under different aliases. Choosing
                # one variable would be arbitrary, but stopping before their
                # common payload would discard already-published semantic
                # knowledge.  Use the common structural suffix only when the
                # repository catalog independently contains exactly one typed,
                # non-collection field with that exact semantic shape.
                common_suffix = _common_suffix_parts([
                    _semantic_ref_parts(ref) for ref in collection_refs
                ])
                if (
                    len(common_suffix) > len(deepest_parts)
                    and common_suffix[-len(deepest_parts):] == deepest_parts
                ):
                    typed_catalog_matches: dict[str, dict[str, Any]] = {}
                    for raw_node in catalog:
                        candidate = semantic_candidate(raw_node)
                        if candidate is None or bool(candidate.get("collection")):
                            continue
                        if not str(candidate.get("object_declared_type") or "").strip():
                            continue
                        ref = str(candidate.get("semantic_ref") or "")
                        if _semantic_ref_parts(ref) != common_suffix:
                            continue
                        typed_catalog_matches.setdefault(ref, candidate)
                    if len(typed_catalog_matches) == 1:
                        chain.append(next(iter(typed_catalog_matches.values())))

    rendered_chain: list[dict[str, Any]] = []
    seen_semantic: set[str] = set()
    for item in chain:
        ref = str(item.get("semantic_ref") or "")
        if not ref or ref in seen_semantic:
            continue
        seen_semantic.add(ref)
        rendered_chain.append(dict(item))
    # Do not replace the canonical consumer for a lone typed alias.  The
    # projection is only material when published evidence proves an actual
    # semantic nesting continuation beyond that entry point.
    if len(rendered_chain) < 2:
        return None
    deepest_consumer_ref = str(rendered_chain[-1].get("semantic_ref") or "").strip()
    return {
        "consumer_attribute": deepest_consumer_ref or consumer_ref,
        "entry_consumer_attribute": consumer_ref,
        "chain": rendered_chain,
        "basis": "published_target_paths_semantic_nesting_projection",
    }


def _query_proves_topology_field(result: Mapping[str, Any], field_path: str) -> bool:
    expected = str(field_path or "").strip()
    if not expected:
        return False
    suffix = "." + expected
    return any(
        str(node.get("display_ref") or "") == expected
        or str(node.get("display_ref") or "").endswith(suffix)
        for node in _iter_query_nodes(result)
    )


def _run_selected(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    selected: Mapping[str, Any],
    direction: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    query_ref = str(selected.get("value_node_id") or "")
    response = gateway.resolve_attribute_paths(
        binding,
        source=query_ref,
        selected_repo_ids=binding.query_repo_ids(repository_id),
        direction=direction,
    )
    return response, _result(response)


def _attempt_ref(
    gateway: AislPathGateway,
    *,
    binding,
    edge: Mapping[str, Any],
    transport_role: str,
    repository_id: str,
    interface_ids: Sequence[str],
    payload_identity: str | None,
    field_path: str,
    source_ref: str,
    direction: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str]:
    response = gateway.resolve_attribute_paths(
        binding,
        source=source_ref,
        selected_repo_ids=binding.query_repo_ids(repository_id),
        direction=direction,
    )
    result = _result(response)
    if str(result.get("status") or "") != "source_ambiguous":
        return response, result, None, "unique_exact_display_ref"

    selected = _anchor_candidate_by_interface(result, repository_id=repository_id, interface_ids=interface_ids)
    basis = "exact_topology_interface_id"
    if selected is None:
        selected = _anchor_candidate_by_transport(
            result,
            edge=edge,
            repository_id=repository_id,
            transport_role=transport_role,
        )
        basis = "exact_topology_transport_identity"
    if selected is None:
        selected = _anchor_candidate_by_payload_owner(
            result,
            repository_id=repository_id,
            payload_identity=payload_identity,
            field_path=field_path,
            direction=direction,
        )
        basis = "exact_payload_owner_accessor"
    if selected is None:
        return response, result, None, "ambiguous_exact_anchor"
    second, second_result = _run_selected(
        gateway,
        binding=binding,
        repository_id=repository_id,
        selected=selected,
        direction=direction,
    )
    return second, second_result, selected, basis


def _exact_topology_suffix_refs(field_path: str) -> tuple[str, ...]:
    parts = [part for part in str(field_path or "").strip().split(".") if part]
    # Keep at least two exact structural segments. A one-segment leaf is handled
    # separately by reverse proof because it is too weak to establish ownership.
    return tuple(".".join(parts[index:]) for index in range(1, max(1, len(parts) - 1)))


def _resolve_leaf_by_reverse_proof(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    field_path: str,
    direction: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None:
    if "." not in field_path:
        return None
    leaf = field_path.rsplit(".", 1)[-1]
    first = gateway.resolve_attribute_paths(
        binding,
        source=leaf,
        selected_repo_ids=binding.query_repo_ids(repository_id),
        direction="reverse",
    )
    first_result = _result(first)
    candidates: list[Mapping[str, Any]] = []
    status = str(first_result.get("status") or "")
    if status == "source_ambiguous":
        candidates = _candidate_rows(first_result, repository_id=repository_id)
    else:
        source = first_result.get("source")
        if isinstance(source, Mapping):
            candidates = [source]

    proven: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for candidate in candidates:
        proof_response, proof_result = _run_selected(
            gateway,
            binding=binding,
            repository_id=repository_id,
            selected=candidate,
            direction="reverse",
        )
        if _query_proves_topology_field(proof_result, field_path):
            proven.append((candidate, proof_response))
    if len(proven) != 1:
        return None
    selected, proof_response = proven[0]
    if direction == "reverse":
        return proof_response, _result(proof_response), selected, "exact_reverse_path_to_topology_field"
    response, result = _run_selected(
        gateway,
        binding=binding,
        repository_id=repository_id,
        selected=selected,
        direction=direction,
    )
    return response, result, selected, "exact_reverse_path_to_topology_field"


_NODE_PAGE_SIZE = 500
_STRUCTURAL_NODE_KINDS = {"field", "derivation"}


def _filtered_node_catalog(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
    node_kind: str | None = None,
    operation: str | None = None,
) -> tuple[list[Mapping[str, Any]], bool]:
    key = (
        str(binding.system_id), str(binding.revision_id), repository_id,
        str(node_kind or ""), str(operation or ""),
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    items: list[Mapping[str, Any]] = []
    page_token = ""
    seen_tokens: set[str] = set()
    complete = True
    while True:
        listing = gateway.list_repository_value_nodes(
            binding,
            repository_id=repository_id,
            node_kind=node_kind,
            operation=operation,
            max_results=_NODE_PAGE_SIZE,
            page_token=page_token,
        )
        result = _result(listing)
        rows = result.get("items")
        if not isinstance(rows, list):
            complete = False
            break
        items.extend(item for item in rows if isinstance(item, Mapping))
        next_token = str(result.get("next_token") or "")
        truncated = bool(result.get("truncated"))
        if not truncated:
            break
        if not next_token or next_token in seen_tokens:
            complete = False
            break
        seen_tokens.add(next_token)
        page_token = next_token

    value = (items, complete)
    cache[key] = value
    return value


def _repository_node_catalog(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
) -> tuple[list[Mapping[str, Any]], bool]:
    return _filtered_node_catalog(
        gateway, binding=binding, repository_id=repository_id, cache=cache,
    )


def _node_payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("payload_json")
    return value if isinstance(value, Mapping) else {}


def _source_occurrence(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _node_payload(item).get("source_occurrence")
    return value if isinstance(value, Mapping) else {}


def _projected_property_name(
    occurrence: Mapping[str, Any],
    item: Mapping[str, Any],
) -> str:
    """Return the exact terminal property already present in published evidence.

    ``projected_object_field`` records from older revisions do not always carry
    ``property_name`` separately.  Their observed ``field_path``/``display_ref``
    still contains the structural terminal.  Taking its final segment is a
    deterministic projection of that published occurrence, not a source-name
    guess.
    """
    direct = str(occurrence.get("property_name") or "").strip()
    if direct:
        return direct
    observed_path = str(
        occurrence.get("field_path") or item.get("display_ref") or ""
    ).strip()
    if "." not in observed_path:
        return ""
    terminal = observed_path.rsplit(".", 1)[-1].strip()
    if not terminal or any(token in terminal for token in ("(", ")", "[", "]")):
        return ""
    return terminal


def _material_source_origin_gap(
    side: Mapping[str, Any],
    *,
    catalog: Sequence[Mapping[str, Any]],
    catalog_complete: bool,
) -> Mapping[str, Any] | None:
    """Classify only mechanically observed external source-origin loss.

    A resolved transport/local anchor can still end in a partial reverse path.
    That is not automatically a product gap: ordinary literals, locals, fields,
    or deliberate structural terminals remain useful observed endpoints.  The
    narrow material case handled here is a projected child whose exact object
    occurrence is an external/unresolved method result.  Public value-node
    payload already preserves both occurrence identities, so this classification
    adds no source inference and does not guess an external owner/artifact.
    """
    if not catalog_complete or str(side.get("anchor_status") or "") != "resolved":
        return None

    result = _result(side.get("query") if isinstance(side.get("query"), Mapping) else {})
    paths = [item for item in result.get("paths") or () if isinstance(item, Mapping)]
    if not paths:
        return None

    by_value_node_id = {
        str(item.get("value_node_id") or ""): item
        for item in catalog
        if str(item.get("value_node_id") or "")
    }
    by_occurrence_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in catalog:
        occurrence_id = str(_source_occurrence(item).get("occurrence_id") or "")
        if occurrence_id:
            by_occurrence_id.setdefault(occurrence_id, []).append(item)

    evidence: list[dict[str, Any]] = []
    for path in paths:
        end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
        terminal_id = str(end.get("value_node_id") or "")
        terminal_item = by_value_node_id.get(terminal_id)
        if terminal_item is None:
            continue
        terminal_occurrence = _source_occurrence(terminal_item)
        if str(terminal_occurrence.get("occurrence_kind") or "") != "projected_object_field":
            continue
        object_occurrence_id = str(terminal_occurrence.get("object_occurrence_id") or "")
        if not object_occurrence_id:
            continue
        parent_items = by_occurrence_id.get(object_occurrence_id, [])
        if len(parent_items) != 1:
            continue
        parent_occurrence = _source_occurrence(parent_items[0])
        if str(parent_occurrence.get("occurrence_kind") or "") != "method_invocation":
            continue
        if str(parent_occurrence.get("resolution_status") or "") != "external_or_unresolved":
            continue
        # ``external_or_unresolved`` is deliberately not an assertion that the
        # invocation is external.  Without a mechanically observed result type
        # there is no external-owner anchor to preserve or prepare.  Promoting
        # such an untyped local return/projection stop to a MATERIAL_SEMANTIC_GAP
        # would turn ordinary async/builder plumbing into a false external
        # dependency requirement.  The underlying path remains partial and its
        # published ``no_observed_incoming_value_flow`` gap stays visible.
        parent_declared_type = str(parent_occurrence.get("declared_type") or "").strip()
        if not parent_declared_type:
            continue
        evidence.append({
            "terminal_value_node_id": terminal_id,
            "terminal_display_ref": str(terminal_item.get("display_ref") or end.get("display_ref") or ""),
            "terminal_property_name": _projected_property_name(terminal_occurrence, terminal_item),
            "parent_occurrence_id": object_occurrence_id,
            "parent_display_ref": str(parent_items[0].get("display_ref") or parent_occurrence.get("field_path") or ""),
            "parent_declared_type": parent_declared_type,
            "parent_method_name": str(parent_occurrence.get("method_name") or ""),
            "classification_basis": "published_projected_field_parent_external_method_result",
        })

    if not evidence:
        return None
    unique = {
        (item["terminal_value_node_id"], item["parent_occurrence_id"]): item
        for item in evidence
    }
    ordered = [unique[key] for key in sorted(unique)]
    return {
        "reason": "source_external_origin_unresolved",
        "evidence": ordered,
    }


def _observed_type(value: Any) -> str:
    """Return the mechanically observed declared type text without inventing ownership."""
    return str(value or "").strip()


def _relative_external_property_path(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the observed projected property path below the unresolved parent.

    The path is derived only from already-published display refs.  No source
    syntax is reparsed here.  For example::

        parent:   converter.convert()
        terminal: converter.convert().identifications.individualIdentifications

    becomes ``("identifications", "individualIdentifications")``.
    """
    terminal = str(evidence.get("terminal_display_ref") or "").strip()
    parent = str(evidence.get("parent_display_ref") or "").strip()
    if terminal and parent and terminal.startswith(parent + "."):
        suffix = terminal[len(parent) + 1 :]
        parts = tuple(part for part in suffix.split(".") if part)
        if parts:
            return parts
    property_name = str(evidence.get("terminal_property_name") or "").strip()
    return (property_name,) if property_name else ()



def _node_declared_type(item: Mapping[str, Any]) -> str:
    occurrence = _source_occurrence(item)
    return _observed_type(item.get("type_ref") or occurrence.get("declared_type"))


def _node_symbol(item: Mapping[str, Any]) -> str:
    occurrence = _source_occurrence(item)
    symbol = str(occurrence.get("symbol") or "").strip()
    if symbol:
        return symbol
    display_ref = str(item.get("display_ref") or "").strip()
    if display_ref and "." not in display_ref and "(" not in display_ref and "[" not in display_ref:
        return display_ref
    return ""


def _local_external_continuations(
    resolved_side: Mapping[str, Any] | None,
    *,
    catalog: Sequence[Mapping[str, Any]],
    catalog_complete: bool,
) -> list[dict[str, Any]]:
    """Return typed local field terminals that materially consume external objects.

    These are not guessed child fields.  They are exact endpoints of already
    published reverse paths for the current consumer attribute.  A continuation
    is retained only when the field root resolves to one unique typed local
    value/parameter in the same operation.  This lets consumer composition ask
    external evidence for the exact scalar property that the local code actually
    consumes (for example ``details.id`` on an ``ExternalDetails`` parameter).
    """
    if not resolved_side or not catalog_complete:
        return []
    query = resolved_side.get("query") if isinstance(resolved_side.get("query"), Mapping) else {}
    result = _result(query)
    paths = [item for item in result.get("paths") or () if isinstance(item, Mapping)]
    if not paths:
        return []

    by_value_node_id = {
        str(item.get("value_node_id") or ""): item
        for item in catalog
        if str(item.get("value_node_id") or "")
    }
    by_operation: dict[str, list[Mapping[str, Any]]] = {}
    for item in catalog:
        operation = str(item.get("operation") or _source_occurrence(item).get("operation") or "").strip()
        if operation:
            by_operation.setdefault(operation, []).append(item)

    requirements: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in paths:
        end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
        value_node_id = str(end.get("value_node_id") or "")
        item = by_value_node_id.get(value_node_id)
        if item is None or str(item.get("node_kind") or end.get("node_kind") or "") != "field":
            continue
        occurrence = _source_occurrence(item)
        property_name = _projected_property_name(occurrence, item)
        display_ref = str(item.get("display_ref") or end.get("display_ref") or "").strip()
        operation = str(item.get("operation") or end.get("operation") or occurrence.get("operation") or "").strip()
        if not property_name or not operation or "." not in display_ref:
            continue
        root_symbol, suffix = display_ref.split(".", 1)
        root_symbol = root_symbol.strip()
        relative_path = tuple(part for part in suffix.split(".") if part)
        if not root_symbol or not relative_path or relative_path[-1] != property_name:
            continue

        owners: dict[str, Mapping[str, Any]] = {}
        for candidate in by_operation.get(operation, ()):
            if _node_symbol(candidate) != root_symbol:
                continue
            declared_type = _node_declared_type(candidate)
            if not declared_type:
                continue
            if str(_source_occurrence(candidate).get("occurrence_kind") or "") not in {
                "method_parameter", "local_variable", "field", "object_field",
            }:
                continue
            candidate_id = str(candidate.get("value_node_id") or "")
            if candidate_id:
                owners[candidate_id] = candidate
        if len(owners) != 1:
            continue
        owner = next(iter(owners.values()))
        owner_type = _node_declared_type(owner)
        if not owner_type:
            continue
        key = (owner_type, property_name, value_node_id)
        requirements[key] = {
            "local_value_node_id": value_node_id,
            "local_display_ref": display_ref,
            "local_operation": operation,
            "owner_symbol": root_symbol,
            "owner_declared_type": owner_type,
            "property_name": property_name,
            "relative_property_path": list(relative_path),
            "path_confidence": str(path.get("confidence") or ""),
            "path_hop_count": int(path.get("hop_count") or 0),
        }
    return [requirements[key] for key in sorted(requirements)]


def _segment_composed_origins(
    parent_segment: Mapping[str, Any],
    *,
    nested_origins: Mapping[str, Mapping[str, Any]],
    parameter_symbols: set[str],
) -> list[dict[str, Any]]:
    """Project an exact callee-parameter child onto an observed caller object.

    This is structural consumer composition, not a synthetic value-flow edge.
    It is allowed only for a single observed parent origin and an exact resolved
    callee method.  ``mapped.details`` + method-parameter ``details.id`` can
    therefore be projected as ``mapped.details.id`` while the repository
    bridge remains explicitly unobserved elsewhere in the result.
    """
    parent_origins = [item for item in parent_segment.get("origins") or () if isinstance(item, Mapping)]
    if len(parent_origins) != 1:
        return []
    parent_ref = str(parent_origins[0].get("display_ref") or "").strip()
    if not parent_ref:
        return []
    composed: dict[str, dict[str, Any]] = {}
    for origin in nested_origins.values():
        display_ref = str(origin.get("display_ref") or "").strip()
        if "." not in display_ref:
            continue
        root, suffix = display_ref.split(".", 1)
        if root not in parameter_symbols or not suffix:
            continue
        projected = f"{parent_ref}.{suffix}"
        composed[projected] = {
            "display_ref": projected,
            "source_value_node_id": str(parent_origins[0].get("value_node_id") or ""),
            "nested_origin_value_node_id": str(origin.get("value_node_id") or ""),
            "basis": "exact_resolved_callee_parameter_property_projection",
        }
    return [composed[key] for key in sorted(composed)]



def _unresolved_callee_semantic_evidence(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    transformation: Mapping[str, Any],
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
) -> Mapping[str, Any] | None:
    """Return a separate method-body segment for one unresolved invocation.

    This never asserts that the invocation calls the candidate method.  It is
    exposed only when the selected external repository contains exactly one
    observed method definition with the same method name and that definition
    has a mechanically observed parameter -> method-body -> return path.  The
    missing call binding remains explicit in ``bridge_status``.
    """
    if str(transformation.get("resolution_status") or "") == "resolved":
        return None
    method_name = str(transformation.get("method_name") or "").strip()
    if not method_name:
        return None
    catalog, complete = _repository_node_catalog(
        gateway, binding=binding, repository_id=repository_id, cache=cache,
    )
    if not complete:
        return None

    method_ids_by_operation: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for node in catalog:
        occurrence = _source_occurrence(node)
        operation = str(node.get("operation") or occurrence.get("operation") or "").strip()
        method_id = str(occurrence.get("method_id") or "").strip()
        if not operation or not method_id or operation.rsplit(".", 1)[-1] != method_name:
            continue
        method_ids_by_operation.setdefault((operation, method_id), []).append(node)
    if len(method_ids_by_operation) != 1:
        return None
    (operation, method_id), method_nodes = next(iter(method_ids_by_operation.items()))

    return_nodes = [
        node for node in method_nodes
        if str(node.get("node_kind") or "") == "return_value"
        and str(_source_occurrence(node).get("occurrence_kind") or "") == "method_return"
    ]
    parameters = [
        node for node in method_nodes
        if str(_source_occurrence(node).get("occurrence_kind") or "") == "method_parameter"
    ]
    parameter_ids = {str(node.get("value_node_id") or "") for node in parameters if str(node.get("value_node_id") or "")}
    if len(return_nodes) != 1 or not parameter_ids:
        return None
    return_node = return_nodes[0]
    return_id = str(return_node.get("value_node_id") or "")
    if not return_id:
        return None

    query = gateway.resolve_attribute_paths(
        binding,
        source=return_id,
        selected_repo_ids=(repository_id,),
        direction="reverse",
    )
    result = _result(query)
    paths = [
        path for path in result.get("paths") or ()
        if isinstance(path, Mapping)
        and str((path.get("end") or {}).get("value_node_id") or "") in parameter_ids
        and int(path.get("hop_count") or 0) > 0
        and str(path.get("confidence") or "") in {"confirmed", "high", "probable"}
    ]
    if not paths:
        return None
    paths.sort(key=lambda path: (int(path.get("hop_count") or 0), str((path.get("end") or {}).get("value_node_id") or "")))
    min_hops = int(paths[0].get("hop_count") or 0)
    shortest = [path for path in paths if int(path.get("hop_count") or 0) == min_hops]
    if len(shortest) != 1:
        return None
    path = shortest[0]

    by_id = {
        str(node.get("value_node_id") or ""): node
        for node in method_nodes
        if str(node.get("value_node_id") or "")
    }
    invocations: dict[str, dict[str, Any]] = {}
    edge_ids: set[str] = set()
    for step in path.get("steps") or ():
        if not isinstance(step, Mapping):
            continue
        edge_id = str(step.get("value_flow_edge_id") or "")
        if edge_id:
            edge_ids.add(edge_id)
        for node_key in ("source", "target"):
            node = step.get(node_key)
            if not isinstance(node, Mapping):
                continue
            node_id = str(node.get("value_node_id") or "")
            catalog_node = by_id.get(node_id)
            occurrence = _source_occurrence(catalog_node) if catalog_node is not None else {}
            if str(occurrence.get("occurrence_kind") or "") != "method_invocation":
                continue
            display_ref = str(node.get("display_ref") or "").strip()
            if not node_id or not display_ref:
                continue
            invocations[node_id] = {
                "value_node_id": node_id,
                "display_ref": display_ref,
                "method_name": str(occurrence.get("method_name") or ""),
                "source_path": str(node.get("source_path") or (catalog_node or {}).get("source_path") or ""),
            }
    if not invocations:
        return None
    end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
    return {
        "operation": operation,
        "method_id": method_id,
        "method_name": method_name,
        "origin": {
            "value_node_id": str(end.get("value_node_id") or ""),
            "display_ref": str(end.get("display_ref") or ""),
        },
        "transformations": [invocations[key] for key in sorted(invocations)],
        "target": {
            "value_node_id": return_id,
            "display_ref": str(return_node.get("display_ref") or ""),
        },
        "value_flow_edge_ids": sorted(edge_ids),
        "bridge_status": "invocation_to_unique_method_candidate_not_observed",
        "basis": "unique_selected_repo_method_name_with_observed_parameter_to_return_path",
    }


def _external_scalar_continuation_segments(
    gateway: AislPathGateway,
    *,
    binding,
    external_repo_ids: Sequence[str],
    direct_segments: Sequence[Mapping[str, Any]],
    local_continuations: Sequence[Mapping[str, Any]],
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
) -> list[dict[str, Any]]:
    """Expand exact object mappings to scalar properties consumed locally.

    Expansion is deliberately bounded.  It only follows a direct external
    transformation whose invocation has an exact resolved ``callee_method_id``
    and declared result type.  A local reverse-path endpoint must consume the
    same declared type/property, and the external scalar target must live in the
    exact callee method.  No schema-only child discovery or cross-repository
    value-flow edge is introduced.
    """
    if not direct_segments or not local_continuations:
        return []

    continuation_by_type: dict[str, list[Mapping[str, Any]]] = {}
    for item in local_continuations:
        owner_type = _observed_type(item.get("owner_declared_type"))
        if owner_type:
            continuation_by_type.setdefault(owner_type, []).append(item)

    nested_segments: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for parent_segment in direct_segments:
        if int(parent_segment.get("semantic_depth") or 0) != 0:
            continue
        parent_target = parent_segment.get("target") if isinstance(parent_segment.get("target"), Mapping) else {}
        parent_target_id = str(parent_target.get("value_node_id") or "")
        parent_relative = [str(value) for value in parent_segment.get("relative_property_path") or () if str(value)]
        for transformation in parent_segment.get("transformations") or ():
            if not isinstance(transformation, Mapping):
                continue
            callee_method_id = str(transformation.get("callee_method_id") or "").strip()
            result_type = _observed_type(transformation.get("type_ref"))
            if (
                not callee_method_id
                or not result_type
                or str(transformation.get("resolution_status") or "") != "resolved"
            ):
                continue
            requirements = continuation_by_type.get(result_type, ())
            if not requirements:
                continue

            for external_repo_id in external_repo_ids:
                field_catalog, fields_complete = _filtered_node_catalog(
                    gateway, binding=binding, repository_id=external_repo_id,
                    cache=cache, node_kind="field",
                )
                if not fields_complete:
                    continue
                for requirement in requirements:
                    property_name = str(requirement.get("property_name") or "").strip()
                    if not property_name:
                        continue
                    target_candidates = [
                        node for node in field_catalog
                        if str(_source_occurrence(node).get("property_name") or "").strip() == property_name
                        and str(_source_occurrence(node).get("method_id") or "").strip() == callee_method_id
                        and "." in str(node.get("display_ref") or "")
                    ]
                    for target_node in target_candidates:
                        operation = str(target_node.get("operation") or _source_occurrence(target_node).get("operation") or "").strip()
                        if not operation:
                            continue
                        operation_catalog, operation_complete = _filtered_node_catalog(
                            gateway, binding=binding, repository_id=external_repo_id,
                            cache=cache, operation=operation,
                        )
                        if not operation_complete:
                            continue
                        method_catalog = [
                            node for node in operation_catalog
                            if str(_source_occurrence(node).get("method_id") or "").strip() == callee_method_id
                        ]
                        by_id = {
                            str(node.get("value_node_id") or ""): node
                            for node in method_catalog
                            if str(node.get("value_node_id") or "")
                        }
                        display_ref = str(target_node.get("display_ref") or "").strip()
                        owner_symbol = display_ref.split(".", 1)[0].strip()
                        owners = [
                            node for node in method_catalog
                            if _node_symbol(node) == owner_symbol
                            and _node_declared_type(node) == result_type
                            and str(_source_occurrence(node).get("occurrence_kind") or "") in {
                                "local_variable", "method_parameter", "field", "object_field",
                            }
                        ]
                        unique_owners = {
                            str(node.get("value_node_id") or ""): node for node in owners
                            if str(node.get("value_node_id") or "")
                        }
                        if len(unique_owners) != 1:
                            continue
                        owner = next(iter(unique_owners.values()))
                        parameters = [
                            node for node in method_catalog
                            if str(_source_occurrence(node).get("occurrence_kind") or "") == "method_parameter"
                        ]
                        parameter_symbols = {_node_symbol(node) for node in parameters if _node_symbol(node)}
                        if not parameter_symbols:
                            continue

                        value_node_id = str(target_node.get("value_node_id") or "").strip()
                        if not value_node_id:
                            continue
                        query = gateway.resolve_attribute_paths(
                            binding,
                            source=value_node_id,
                            selected_repo_ids=(external_repo_id,),
                            direction="reverse",
                        )
                        result = _result(query)
                        paths = [
                            path for path in result.get("paths") or ()
                            if isinstance(path, Mapping)
                            and int(path.get("hop_count") or 0) > 0
                            and str(path.get("confidence") or "") in {"confirmed", "high", "probable"}
                        ]
                        if not paths:
                            continue

                        origins: dict[str, dict[str, Any]] = {}
                        transformations: dict[str, dict[str, Any]] = {}
                        edge_ids: set[str] = set()
                        for path in paths:
                            end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
                            end_id = str(end.get("value_node_id") or "")
                            end_item = by_id.get(end_id)
                            end_occurrence = _source_occurrence(end_item) if end_item is not None else {}
                            end_ref = str(end.get("display_ref") or "").strip()
                            end_root = end_ref.split(".", 1)[0].strip() if "." in end_ref else ""
                            if (
                                end_id
                                and end_id != value_node_id
                                and end_item is not None
                                and str(end_item.get("node_kind") or end.get("node_kind") or "") == "field"
                                and str(end_occurrence.get("property_name") or "").strip() == property_name
                                and end_root in parameter_symbols
                            ):
                                origins[end_id] = {
                                    "value_node_id": end_id,
                                    "display_ref": end_ref,
                                    "node_kind": str(end.get("node_kind") or end_item.get("node_kind") or ""),
                                    "source_path": str(end.get("source_path") or end_item.get("source_path") or ""),
                                }
                            for step in path.get("steps") or ():
                                if not isinstance(step, Mapping):
                                    continue
                                edge_id = str(step.get("value_flow_edge_id") or "")
                                if edge_id:
                                    edge_ids.add(edge_id)
                                for node_key in ("source", "target"):
                                    node = step.get(node_key)
                                    if not isinstance(node, Mapping) or str(node.get("node_kind") or "") != "derivation":
                                        continue
                                    node_id = str(node.get("value_node_id") or "")
                                    catalog_node = by_id.get(node_id)
                                    occurrence = _source_occurrence(catalog_node) if catalog_node is not None else {}
                                    if node_id:
                                        transformations[node_id] = {
                                            "value_node_id": node_id,
                                            "display_ref": str(node.get("display_ref") or ""),
                                            "source_path": str(node.get("source_path") or ""),
                                            "type_ref": _node_declared_type(catalog_node) if catalog_node is not None else _observed_type(node.get("type_ref")),
                                            "callee_method_id": str(occurrence.get("callee_method_id") or ""),
                                            "resolution_status": str(occurrence.get("resolution_status") or ""),
                                            "method_name": str(occurrence.get("method_name") or ""),
                                        }
                        if not origins:
                            continue
                        composed_origins = _segment_composed_origins(
                            parent_segment,
                            nested_origins=origins,
                            parameter_symbols=parameter_symbols,
                        )
                        if not composed_origins:
                            continue
                        key = (external_repo_id, parent_target_id, value_node_id, str(requirement.get("local_value_node_id") or ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        rendered_transformations: list[dict[str, Any]] = []
                        for item in [transformations[key] for key in sorted(transformations)]:
                            rendered = dict(item)
                            supplemental = _unresolved_callee_semantic_evidence(
                                gateway,
                                binding=binding,
                                repository_id=external_repo_id,
                                transformation=item,
                                cache=cache,
                            )
                            if supplemental is not None:
                                rendered["unresolved_callee_semantic_evidence"] = dict(supplemental)
                            rendered_transformations.append(rendered)
                        nested_segments.append({
                            "repository_id": external_repo_id,
                            "system_id": str(binding.system_id),
                            "revision_id": str(binding.revision_id),
                            "target_declared_type": result_type,
                            "root_declared_type": str(parent_segment.get("root_declared_type") or ""),
                            "property_name": property_name,
                            "relative_property_path": [*parent_relative, *[str(v) for v in requirement.get("relative_property_path") or () if str(v)]],
                            "semantic_depth": 1,
                            "parent_segment_target_value_node_id": parent_target_id,
                            "parent_transformation_value_node_id": str(transformation.get("value_node_id") or ""),
                            "parent_transformation_display_ref": str(transformation.get("display_ref") or ""),
                            "callee_method_id": callee_method_id,
                            "local_consumer": dict(requirement),
                            "owner": {
                                "value_node_id": str(owner.get("value_node_id") or ""),
                                "display_ref": str(owner.get("display_ref") or ""),
                                "type_ref": result_type,
                                "operation": operation,
                            },
                            "target": {
                                "value_node_id": value_node_id,
                                "display_ref": display_ref,
                                "source_path": str(target_node.get("source_path") or ""),
                            },
                            "origins": [origins[key] for key in sorted(origins)],
                            "composed_origins": composed_origins,
                            "transformations": rendered_transformations,
                            "value_flow_edge_ids": sorted(edge_ids),
                            "path_status": str(result.get("status") or ""),
                            "basis": "exact_resolved_external_callee_scalar_property_consumed_by_local_path",
                        })
    nested_segments.sort(
        key=lambda item: (
            item["repository_id"],
            item.get("parent_segment_target_value_node_id") or "",
            item["target"]["value_node_id"],
        )
    )
    return nested_segments



def _source_semantic_projection(
    side: Mapping[str, Any],
    *,
    external_evidence: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Project the exact local path that consumes the deepest external scalar.

    Reverse source queries may expose several legitimate origins.  Once external
    composition proves a deeper scalar and records the exact local consumer node,
    prefer the reverse path that terminates at that node.  This is a projection
    of already-published repository-local flow, not a new cross-repository edge.
    """
    segments = [
        item for item in external_evidence.get("segments") or ()
        if isinstance(item, Mapping) and isinstance(item.get("local_consumer"), Mapping)
    ]
    if not segments:
        return None
    max_depth = max(int(item.get("semantic_depth") or 0) for item in segments)
    deepest = [item for item in segments if int(item.get("semantic_depth") or 0) == max_depth]
    local_ids = {
        str(item["local_consumer"].get("local_value_node_id") or "")
        for item in deepest
        if str(item["local_consumer"].get("local_value_node_id") or "")
    }
    if len(local_ids) != 1:
        return None
    local_id = next(iter(local_ids))

    query = side.get("query") if isinstance(side.get("query"), Mapping) else {}
    result = _result(query)
    candidate_paths = [
        path for path in result.get("paths") or ()
        if isinstance(path, Mapping)
        and str((path.get("end") or {}).get("value_node_id") or "") == local_id
        and str(path.get("confidence") or "") in {"confirmed", "high", "probable"}
    ]
    if not candidate_paths:
        return None
    candidate_paths.sort(key=lambda path: (int(path.get("hop_count") or 0), str((path.get("end") or {}).get("display_ref") or "")))
    shortest_hops = int(candidate_paths[0].get("hop_count") or 0)
    shortest = [path for path in candidate_paths if int(path.get("hop_count") or 0) == shortest_hops]
    if len(shortest) != 1:
        return None
    path = shortest[0]

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_node(node: Mapping[str, Any]) -> None:
        kind = str(node.get("node_kind") or "")
        if kind not in {"field", "derivation", "wire_field"}:
            return
        ref = str(node.get("display_ref") or "").strip()
        if not ref or ref in seen:
            return
        seen.add(ref)
        refs.append({
            "value_node_id": str(node.get("value_node_id") or ""),
            "display_ref": ref,
            "node_kind": kind,
            "operation": str(node.get("operation") or ""),
            "source_path": str(node.get("source_path") or ""),
        })

    end = path.get("end")
    if isinstance(end, Mapping):
        append_node(end)
    for step in reversed([item for item in path.get("steps") or () if isinstance(item, Mapping)]):
        source = step.get("source")
        target = step.get("target")
        if isinstance(source, Mapping):
            append_node(source)
        if isinstance(target, Mapping):
            append_node(target)
    start = path.get("start")
    if isinstance(start, Mapping):
        append_node(start)

    if len(refs) < 2:
        return None
    return {
        "chain": refs,
        "local_external_consumer_value_node_id": local_id,
        "basis": "deepest_external_scalar_exact_local_reverse_path",
    }


def _external_origin_evidence(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    material_gap: Mapping[str, Any],
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
    resolved_side: Mapping[str, Any] | None = None,
    local_catalog: Sequence[Mapping[str, Any]] = (),
    local_catalog_complete: bool = False,
) -> Mapping[str, Any] | None:
    """Find separate observed external semantic segments for a source gap.

    No cross-repository value-flow edge is created.  Direct projected fields
    are accepted only when the selected external repository contains the exact
    declared result type/property and an observed non-zero reverse value-flow
    path.

    A nested projected field may have a different mechanically observed owner
    type (for example a field inside a nested value object).  Such a field is
    accepted only after its direct ancestor has already been proven on the
    original result type *and* the nested field has an observed reverse path to
    at least one of the exact same external origin value nodes.  This keeps the
    composition evidence-based while avoiding the false requirement that every
    nested field be owned directly by the top-level result type.

    The bridge from the local unresolved method result to the external segments
    remains explicitly unproven and is reported as such by the caller.
    """
    external_repo_ids = [
        value for value in binding.query_repo_ids(repository_id)
        if value != repository_id
    ]
    evidence_rows = [
        item for item in material_gap.get("evidence") or ()
        if isinstance(item, Mapping)
    ]
    if not external_repo_ids or not evidence_rows:
        return None

    evidence_rows.sort(key=lambda item: (len(_relative_external_property_path(item)), str(item.get("terminal_value_node_id") or "")))
    all_segments: list[dict[str, Any]] = []
    covered_terminals: set[str] = set()
    direct_origin_ids_by_property: dict[str, set[str]] = {}

    for evidence in evidence_rows:
        terminal_id = str(evidence.get("terminal_value_node_id") or "")
        root_target_type = _observed_type(evidence.get("parent_declared_type"))
        property_name = str(evidence.get("terminal_property_name") or "").strip()
        relative_path = _relative_external_property_path(evidence)
        if not root_target_type or not property_name or not relative_path:
            continue

        is_nested = len(relative_path) > 1
        root_property = relative_path[0]
        shared_ancestor_origins = direct_origin_ids_by_property.get(root_property, set()) if is_nested else set()
        if is_nested and not shared_ancestor_origins:
            continue

        terminal_segments: list[dict[str, Any]] = []
        terminal_origin_ids: set[str] = set()
        for external_repo_id in external_repo_ids:
            # Property discovery is bounded to public field nodes.  Only the
            # operation(s) containing an exact property candidate are expanded
            # further to verify the owner's mechanically observed declared type.
            field_catalog, fields_complete = _filtered_node_catalog(
                gateway, binding=binding, repository_id=external_repo_id,
                cache=cache, node_kind="field",
            )
            if not fields_complete:
                continue
            property_candidates = [
                node for node in field_catalog
                if str(_source_occurrence(node).get("property_name") or "").strip() == property_name
                and "." in str(node.get("display_ref") or "")
            ]

            for target_node in property_candidates:
                occurrence = _source_occurrence(target_node)
                operation = str(target_node.get("operation") or occurrence.get("operation") or "").strip()
                display_ref = str(target_node.get("display_ref") or "").strip()
                if not operation:
                    continue
                owner_symbol = display_ref.split(".", 1)[0].strip()
                operation_catalog, operation_complete = _filtered_node_catalog(
                    gateway, binding=binding, repository_id=external_repo_id,
                    cache=cache, operation=operation,
                )
                if not operation_complete:
                    continue
                owners: list[Mapping[str, Any]] = []
                for node in operation_catalog:
                    owner_occurrence = _source_occurrence(node)
                    symbol = str(owner_occurrence.get("symbol") or "").strip()
                    declared_type = _observed_type(
                        node.get("type_ref") or owner_occurrence.get("declared_type")
                    )
                    if symbol != owner_symbol or not declared_type:
                        continue
                    if not is_nested and declared_type != root_target_type:
                        continue
                    if str(owner_occurrence.get("occurrence_kind") or "") not in {
                        "local_variable", "method_parameter", "field", "object_field",
                    }:
                        continue
                    owners.append(node)
                if len(owners) != 1:
                    continue
                value_node_id = str(target_node.get("value_node_id") or "").strip()
                if not value_node_id:
                    continue

                query = gateway.resolve_attribute_paths(
                    binding,
                    source=value_node_id,
                    selected_repo_ids=(external_repo_id,),
                    direction="reverse",
                )
                result = _result(query)
                paths = [
                    path for path in result.get("paths") or ()
                    if isinstance(path, Mapping)
                    and int(path.get("hop_count") or 0) > 0
                    and str(path.get("confidence") or "") in {"confirmed", "high", "probable"}
                ]
                if not paths:
                    continue

                operation_by_id = {
                    str(node.get("value_node_id") or ""): node
                    for node in operation_catalog
                    if str(node.get("value_node_id") or "")
                }
                origins: dict[str, dict[str, Any]] = {}
                transformations: dict[str, dict[str, Any]] = {}
                edge_ids: set[str] = set()
                for path in paths:
                    end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
                    end_id = str(end.get("value_node_id") or "")
                    if end_id and end_id != value_node_id:
                        origins[end_id] = {
                            "value_node_id": end_id,
                            "display_ref": str(end.get("display_ref") or ""),
                            "node_kind": str(end.get("node_kind") or ""),
                            "source_path": str(end.get("source_path") or ""),
                        }
                    for step in path.get("steps") or ():
                        if not isinstance(step, Mapping):
                            continue
                        edge_id = str(step.get("value_flow_edge_id") or "")
                        if edge_id:
                            edge_ids.add(edge_id)
                        for node_key in ("source", "target"):
                            node = step.get(node_key)
                            if not isinstance(node, Mapping) or str(node.get("node_kind") or "") != "derivation":
                                continue
                            node_id = str(node.get("value_node_id") or "")
                            if node_id:
                                catalog_node = operation_by_id.get(node_id)
                                derivation_occurrence = (
                                    _source_occurrence(catalog_node) if catalog_node is not None else {}
                                )
                                transformations[node_id] = {
                                    "value_node_id": node_id,
                                    "display_ref": str(node.get("display_ref") or ""),
                                    "source_path": str(node.get("source_path") or ""),
                                    "type_ref": (
                                        _node_declared_type(catalog_node)
                                        if catalog_node is not None else _observed_type(node.get("type_ref"))
                                    ),
                                    "callee_method_id": str(derivation_occurrence.get("callee_method_id") or ""),
                                    "resolution_status": str(derivation_occurrence.get("resolution_status") or ""),
                                    "method_name": str(derivation_occurrence.get("method_name") or ""),
                                }
                if not origins:
                    continue
                # Prefer observed data fields over construction/literal terminals
                # when the same reverse query exposes both.  Nested composition
                # also keys on these field origins, so a construction-only path
                # cannot accidentally satisfy the shared-origin gate.
                field_origins = {
                    key: value for key, value in origins.items()
                    if value.get("node_kind") == "field"
                }
                projected_origins = field_origins or origins
                projected_origin_ids = set(projected_origins)
                if is_nested and not (projected_origin_ids & shared_ancestor_origins):
                    continue

                owner = owners[0]
                observed_owner_type = _observed_type(
                    owner.get("type_ref") or _source_occurrence(owner).get("declared_type")
                )
                terminal_segments.append({
                    "repository_id": external_repo_id,
                    "system_id": str(binding.system_id),
                    "revision_id": str(binding.revision_id),
                    "target_declared_type": observed_owner_type,
                    "root_declared_type": root_target_type,
                    "property_name": property_name,
                    "relative_property_path": list(relative_path),
                    "semantic_depth": 0 if not is_nested else len(relative_path) - 1,
                    "owner": {
                        "value_node_id": str(owner.get("value_node_id") or ""),
                        "display_ref": str(owner.get("display_ref") or ""),
                        "type_ref": observed_owner_type,
                        "operation": operation,
                    },
                    "target": {
                        "value_node_id": value_node_id,
                        "display_ref": display_ref,
                        "source_path": str(target_node.get("source_path") or ""),
                    },
                    "origins": [projected_origins[key] for key in sorted(projected_origins)],
                    "transformations": [transformations[key] for key in sorted(transformations)],
                    "value_flow_edge_ids": sorted(edge_ids),
                    "path_status": str(result.get("status") or ""),
                    "basis": (
                        "selected_external_repo_nested_property_shares_observed_origin_with_exact_typed_ancestor"
                        if is_nested
                        else "selected_external_repo_exact_typed_owner_property_with_observed_reverse_path"
                    ),
                })
                terminal_origin_ids.update(projected_origin_ids)

        if terminal_segments:
            covered_terminals.add(terminal_id)
            if not is_nested:
                direct_origin_ids_by_property.setdefault(root_property, set()).update(terminal_origin_ids)
            terminal_segments.sort(
                key=lambda item: (
                    item["repository_id"],
                    item["target"]["value_node_id"],
                    tuple(origin["value_node_id"] for origin in item["origins"]),
                )
            )
            all_segments.extend(terminal_segments)

    required_terminals = {
        str(item.get("terminal_value_node_id") or "")
        for item in evidence_rows
        if str(item.get("terminal_value_node_id") or "")
    }
    if not required_terminals or covered_terminals != required_terminals:
        return None

    local_continuations = _local_external_continuations(
        resolved_side, catalog=local_catalog, catalog_complete=local_catalog_complete,
    )
    nested_segments = _external_scalar_continuation_segments(
        gateway,
        binding=binding,
        external_repo_ids=external_repo_ids,
        direct_segments=all_segments,
        local_continuations=local_continuations,
        cache=cache,
    )
    if nested_segments:
        all_segments.extend(nested_segments)
        all_segments.sort(
            key=lambda item: (
                item.get("repository_id") or "",
                int(item.get("semantic_depth") or 0),
                item.get("parent_segment_target_value_node_id") or "",
                (item.get("target") or {}).get("value_node_id") or "",
            )
        )

    return {
        "status": "semantically_covered",
        "basis": "separate_selected_external_repository_evidence_segments",
        "bridge_status": "cross_repository_link_not_observed",
        "segments": all_segments,
    }


def _route_wire_candidates(
    catalog: Sequence[Mapping[str, Any]],
    *,
    edge: Mapping[str, Any],
    repository_id: str,
    transport_role: str,
    field_path: str | None = None,
) -> list[Mapping[str, Any]]:
    protocol = str(edge.get("protocol") or "").strip().casefold()
    endpoint = str(edge.get("matched_identity") or "").strip()
    method = str(edge.get("method") or "").strip().upper()
    role = str(transport_role or "").strip().casefold()
    expected_field = str(field_path or "").strip()
    if not protocol or not endpoint or role not in {"request", "response"}:
        return []

    matches: list[Mapping[str, Any]] = []
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") != "wire_field":
            continue
        if expected_field and str(item.get("wire_path") or "").strip() != expected_field:
            continue
        transport = _node_payload(item).get("transport")
        if not isinstance(transport, Mapping):
            continue
        if str(transport.get("protocol") or "").strip().casefold() != protocol:
            continue
        if str(transport.get("endpoint") or "").strip() != endpoint:
            continue
        if str(transport.get("payload_role") or "").strip().casefold() != role:
            continue
        if str(transport.get("interface_direction") or "").strip().casefold() != "outbound":
            continue
        if protocol == "http" and method and str(transport.get("http_method") or "").strip().upper() != method:
            continue
        matches.append(item)

    unique: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in matches:
        signature = (
            str(item.get("operation") or ""),
            str(item.get("wire_path") or ""),
            str(item.get("owner_ref") or ""),
        )
        current = unique.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            unique[signature] = item
    return [unique[key] for key in sorted(unique)]


def _source_counterpart_shape_proof(
    edge: Mapping[str, Any],
    *,
    field: BoundaryField,
) -> list[Mapping[str, Any]]:
    if not field.source_payload_identity or field.source_payload_identity != field.target_payload_identity:
        return []
    if "." in field.field_path:
        return []

    rows: list[Mapping[str, Any]] = []
    for flow in edge.get("attribute_flows") or ():
        if not isinstance(flow, Mapping):
            continue
        if str(flow.get("transport_role") or "").strip().casefold() != field.transport_role:
            continue
        if str(flow.get("source_repository_id") or "") != field.source_repository_id:
            continue
        if str(flow.get("target_repository_id") or "") != field.target_repository_id:
            continue
        for basis in flow.get("basis") or ():
            if not isinstance(basis, Mapping):
                continue
            if str(basis.get("attribute_name") or "") != field.field_path:
                continue
            rows.append(basis)
    if not rows:
        return []

    source_interfaces = set(field.source_interface_ids)
    target_interfaces = set(field.target_interface_ids)
    payload = field.source_payload_identity
    for item in rows:
        if str(item.get("evidence_mode") or "") != "exact_payload_identity_counterpart_shape":
            return []
        if str(item.get("payload_identity") or "") != payload:
            return []
        if str(item.get("source_shape_status") or "") != "unavailable_external_declaration":
            return []
        if str(item.get("target_shape_status") or "") != "available_local_declaration":
            return []
        source_interface = str(item.get("edge_source_interface_id") or "")
        target_interface = str(item.get("edge_target_interface_id") or "")
        if source_interface and source_interface not in source_interfaces:
            return []
        if target_interface and target_interface not in target_interfaces:
            return []
    return rows


def _published_route_wire_side(
    *,
    repository_id: str,
    binding,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": [*attempted_anchors, str(selected.get("value_node_id") or "")],
        "resolved_anchor": dict(selected),
        "anchor_status": "resolved",
        "anchor_selection_basis": "published_route_wire_field:exact_transport_and_field",
        "query": {
            "result": {
                "status": "resolved_terminal",
                "source": dict(selected),
                "paths": [],
                "gaps": [],
            }
        },
        "terminal_proof": {
            "published_wire_field": True,
            "exact_transport_context": True,
        },
    }


def _operation_accepts_payload(
    catalog: Sequence[Mapping[str, Any]],
    *,
    operation: str,
    payload_identity: str,
) -> bool:
    return any(
        str(item.get("operation") or "") == operation
        and str(item.get("type_ref") or "") == payload_identity
        and str(item.get("node_kind") or "") in {"parameter", "return_value"}
        for item in catalog
    )


def _payload_scoped_structural_candidates(
    catalog: Sequence[Mapping[str, Any]],
    *,
    repository_id: str,
    payload_identity: str,
    field_path: str,
) -> list[Mapping[str, Any]]:
    nested = "." in field_path
    suffix = "." + field_path
    candidates: list[Mapping[str, Any]] = []
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") not in _STRUCTURAL_NODE_KINDS:
            continue
        display_ref = str(item.get("display_ref") or "")
        if display_ref != field_path and not (nested and display_ref.endswith(suffix)):
            continue
        operation = str(item.get("operation") or "")
        if not operation or not _operation_accepts_payload(
            catalog,
            operation=operation,
            payload_identity=payload_identity,
        ):
            continue
        candidates.append(item)

    # Multiple source occurrences of the same structural expression are equivalent
    # for anchor selection. Keep one stable representative per semantic signature.
    unique: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for item in candidates:
        signature = (
            str(item.get("operation") or ""),
            str(item.get("display_ref") or ""),
            str(item.get("node_kind") or ""),
            str(item.get("source_path") or ""),
        )
        current = unique.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            unique[signature] = item
    return [unique[key] for key in sorted(unique)]


def _payload_instance_scoped_structural_candidates(
    catalog: Sequence[Mapping[str, Any]],
    *,
    repository_id: str,
    payload_identity: str,
    field_path: str,
) -> list[Mapping[str, Any]]:
    payload_instances: dict[str, set[str]] = {}
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("type_ref") or "") != payload_identity:
            continue
        if str(item.get("node_kind") or "") not in {"parameter", "local_value", "return_value"}:
            continue
        operation = str(item.get("operation") or "")
        display_ref = str(item.get("display_ref") or "")
        if operation and display_ref:
            payload_instances.setdefault(operation, set()).add(display_ref)

    candidates: list[Mapping[str, Any]] = []
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") not in _STRUCTURAL_NODE_KINDS:
            continue
        operation = str(item.get("operation") or "")
        display_ref = str(item.get("display_ref") or "")
        if not operation or not display_ref:
            continue
        if any(display_ref == f"{payload_ref}.{field_path}" for payload_ref in payload_instances.get(operation, ())):
            candidates.append(item)

    unique: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for item in candidates:
        signature = (
            str(item.get("operation") or ""),
            str(item.get("display_ref") or ""),
            str(item.get("node_kind") or ""),
            str(item.get("source_path") or ""),
        )
        current = unique.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            unique[signature] = item
    return [unique[key] for key in sorted(unique)]


def _source_published_fallback(
    gateway: AislPathGateway,
    *,
    edge: Mapping[str, Any],
    field: BoundaryField,
    binding,
    repository_id: str,
    payload_identity: str | None,
    field_path: str,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
) -> dict[str, Any] | None:
    payload = str(payload_identity or "").strip()
    if direction != "reverse" or not payload or not field_path:
        return None
    catalog, complete = _repository_node_catalog(
        gateway,
        binding=binding,
        repository_id=repository_id,
        cache=cache,
    )
    if not complete:
        return None
    candidates = _payload_instance_scoped_structural_candidates(
        catalog,
        repository_id=repository_id,
        payload_identity=payload,
        field_path=field_path,
    )
    if len(candidates) > 1:
        return None
    if len(candidates) == 1:
        selected = candidates[0]
        response, result = _run_selected(
            gateway,
            binding=binding,
            repository_id=repository_id,
            selected=selected,
            direction=direction,
        )
        status = str(result.get("status") or "")
        source = result.get("source")
        if not isinstance(source, Mapping) or status.startswith("source_") or status == "unavailable":
            return None
        attempted = [*attempted_anchors, str(selected.get("value_node_id") or "")]
        return _resolved_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=requested_anchor,
            attempted_anchors=attempted,
            response=response,
            result=result,
            selected=selected,
            basis="published_payload_instance_structural_candidate:unique_semantic_node",
        )

    wire_candidates = _route_wire_candidates(
        catalog,
        edge=edge,
        repository_id=repository_id,
        transport_role=field.transport_role,
        field_path=field.field_path,
    )
    if len(wire_candidates) == 1:
        return _published_route_wire_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=requested_anchor,
            attempted_anchors=attempted_anchors,
            selected=wire_candidates[0],
        )
    if wire_candidates:
        return None

    counterpart_proof = _source_counterpart_shape_proof(edge, field=field)
    if not counterpart_proof:
        return None
    route_nodes = _route_wire_candidates(
        catalog,
        edge=edge,
        repository_id=repository_id,
        transport_role=field.transport_role,
    )
    route_interfaces = {
        (
            str(item.get("operation") or "").strip(),
            str(item.get("owner_ref") or "").strip(),
        )
        for item in route_nodes
        if str(item.get("operation") or "").strip() and str(item.get("owner_ref") or "").strip()
    }
    if len(route_interfaces) != 1:
        return None
    operation, route_owner_ref = next(iter(route_interfaces))
    payload_instances = [
        item
        for item in catalog
        if str(item.get("repo_id") or "") == repository_id
        and str(item.get("operation") or "") == operation
        and str(item.get("type_ref") or "") == payload
        and str(item.get("node_kind") or "") in {"parameter", "local_value", "return_value"}
        and str(item.get("display_ref") or "").strip()
    ]
    semantic_instances: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in payload_instances:
        signature = (
            str(item.get("node_kind") or ""),
            str(item.get("display_ref") or ""),
            str(item.get("source_path") or ""),
        )
        current = semantic_instances.get(signature)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            semantic_instances[signature] = item
    if len(semantic_instances) != 1:
        return None
    selected_payload = next(iter(semantic_instances.values()))
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": [*attempted_anchors, str(selected_payload.get("value_node_id") or "")],
        "resolved_anchor": dict(selected_payload),
        "anchor_status": "terminal",
        "anchor_selection_basis": "topology_counterpart_shape_with_unique_published_payload_instance:resolved_terminal",
        "query": {
            "result": {
                "status": "resolved_terminal",
                "source": dict(selected_payload),
                "paths": [],
                "gaps": [],
            }
        },
        "terminal_proof": {
            "payload_identity": payload,
            "field_path": field.field_path,
            "operation": operation,
            "repository_value_node_scan_complete": True,
            "exact_route_interface_count": 1,
            "route_owner_ref": route_owner_ref,
            "exact_payload_instance_count": 1,
            "topology_basis": [dict(item) for item in counterpart_proof],
        },
    }


def _target_published_fallback(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    payload_identity: str | None,
    field_path: str,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]],
) -> dict[str, Any] | None:
    payload = str(payload_identity or "").strip()
    if direction != "forward" or not payload or not field_path:
        return None
    catalog, complete = _repository_node_catalog(
        gateway,
        binding=binding,
        repository_id=repository_id,
        cache=cache,
    )
    if not complete:
        return None
    candidates = _payload_scoped_structural_candidates(
        catalog,
        repository_id=repository_id,
        payload_identity=payload,
        field_path=field_path,
    )
    if len(candidates) == 1:
        selected = candidates[0]
        response, result = _run_selected(
            gateway,
            binding=binding,
            repository_id=repository_id,
            selected=selected,
            direction=direction,
        )
        status = str(result.get("status") or "")
        source = result.get("source")
        if isinstance(source, Mapping) and not status.startswith("source_") and status != "unavailable":
            attempted = [*attempted_anchors, str(selected.get("value_node_id") or "")]
            return _resolved_side(
                repository_id=repository_id,
                binding=binding,
                direction=direction,
                requested_anchor=requested_anchor,
                attempted_anchors=attempted,
                response=response,
                result=result,
                selected=selected,
                basis="published_payload_structural_candidate:unique_semantic_node",
            )
    if candidates:
        return None

    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": list(attempted_anchors),
        "resolved_anchor": None,
        "anchor_status": "terminal",
        "anchor_selection_basis": "complete_published_value_node_scan:no_payload_scoped_field_specific_use",
        "query": {
            "result": {
                "status": "resolved_terminal",
                "paths": [],
                "gaps": [],
            }
        },
        "terminal_proof": {
            "payload_identity": payload,
            "field_path": field_path,
            "repository_value_node_scan_complete": True,
            "payload_scoped_structural_candidate_count": 0,
        },
    }


def _resolved_side(
    *,
    repository_id: str,
    binding,
    direction: str,
    requested_anchor: str,
    attempted_anchors: list[str],
    response: Mapping[str, Any],
    result: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
    basis: str,
) -> dict[str, Any]:
    status = str(result.get("status") or "")
    anchor = result.get("source") if isinstance(result.get("source"), Mapping) else selected
    anchor_resolved = bool(anchor) and not status.startswith("source_") and status != "unavailable"
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": requested_anchor,
        "attempted_anchors": attempted_anchors,
        "resolved_anchor": dict(anchor) if isinstance(anchor, Mapping) else None,
        "anchor_status": "resolved" if anchor_resolved else "unresolved",
        "anchor_selection_basis": basis,
        "query": dict(response),
    }


def _local_continuation_score(
    result: Mapping[str, Any],
    *,
    anchor: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    """Rank only exact deterministic anchors by observed local continuation.

    Different exact aliases can identify the same transport field.  A wire alias
    often resolves only to itself while an exact local payload alias reaches the
    already-published repository-local value-flow.  Prefer the alias that exposes
    more observed continuation; never use names, fuzzy matching, or semantic
    inference.  Stable attempt order remains the tie-breaker.
    """
    paths = [item for item in result.get("paths") or () if isinstance(item, Mapping)]
    anchor_id = str(anchor.get("value_node_id") or "")
    anchor_ref = str(anchor.get("display_ref") or "")
    max_steps = 0
    non_self_paths = 0
    transformed_paths = 0
    for path in paths:
        steps = [item for item in path.get("steps") or () if isinstance(item, Mapping)]
        max_steps = max(max_steps, len(steps))
        if steps:
            transformed_paths += 1
        end = path.get("end") if isinstance(path.get("end"), Mapping) else {}
        end_id = str(end.get("value_node_id") or "")
        end_ref = str(end.get("display_ref") or "")
        if (anchor_id and end_id and end_id != anchor_id) or (anchor_ref and end_ref and end_ref != anchor_ref):
            non_self_paths += 1
    return (max_steps, non_self_paths, transformed_paths, len(paths))


def _resolve_side(
    gateway: AislPathGateway,
    *,
    edge: Mapping[str, Any],
    field: BoundaryField,
    side: str,
    binding,
    repository_id: str,
    interface_ids: Sequence[str],
    payload_identity: str | None,
    source_ref: str,
    direction: str,
    node_catalog_cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]] | None = None,
) -> dict[str, Any]:
    attempted: list[str] = []
    attempts: list[tuple[str, str]] = [(source_ref, "canonical_wire_display_ref")]
    route_ref = route_boundary_ref(edge, field.transport_role, field.field_path)
    if route_ref:
        attempts.append((route_ref, "exact_topology_route_boundary"))

    for symbol in local_payload_binding_symbols(
        edge,
        repository_id=repository_id,
        payload_identity=payload_identity,
    ):
        attempts.append((f"{symbol}.{field.field_path}", "exact_topology_local_payload_binding"))

    attempts.append((field.field_path, "exact_topology_field_path"))
    for suffix_ref in _exact_topology_suffix_refs(field.field_path):
        attempts.append((suffix_ref, "exact_topology_structural_suffix"))
    if "." not in field.field_path:
        attempts.append((f"this.{field.field_path}", "exact_payload_field"))

    seen: set[str] = set()
    last: tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None = None
    best: tuple[tuple[int, int, int, int], int, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None, str] | None = None
    for attempt_index, (ref, strategy) in enumerate(attempts):
        if not ref or ref in seen:
            continue
        seen.add(ref)
        attempted.append(ref)
        response, result, selected, basis = _attempt_ref(
            gateway,
            binding=binding,
            edge=edge,
            transport_role=field.transport_role,
            repository_id=repository_id,
            interface_ids=interface_ids,
            payload_identity=payload_identity,
            field_path=field.field_path,
            source_ref=ref,
            direction=direction,
        )
        resolved_basis = f"{strategy}:{basis}"
        last = (response, result, selected, resolved_basis)
        status = str(result.get("status") or "")
        anchor = result.get("source") if isinstance(result.get("source"), Mapping) else selected
        if anchor is not None and not status.startswith("source_") and status != "unavailable":
            score = _local_continuation_score(result, anchor=anchor)
            candidate = (score, -attempt_index, response, result, selected, resolved_basis)
            if best is None or candidate[:2] > best[:2]:
                best = candidate

    if best is not None:
        _score, _order, response, result, selected, basis = best
        return _resolved_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            response=response,
            result=result,
            selected=selected,
            basis=basis,
        )

    if side == "source":
        fallback = _source_published_fallback(
            gateway,
            edge=edge,
            field=field,
            binding=binding,
            repository_id=repository_id,
            payload_identity=payload_identity,
            field_path=field.field_path,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            cache=node_catalog_cache if node_catalog_cache is not None else {},
        )
        if fallback is not None:
            return fallback

    if side == "target":
        fallback = _target_published_fallback(
            gateway,
            binding=binding,
            repository_id=repository_id,
            payload_identity=payload_identity,
            field_path=field.field_path,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            cache=node_catalog_cache if node_catalog_cache is not None else {},
        )
        if fallback is not None:
            return fallback

    leaf = _resolve_leaf_by_reverse_proof(
        gateway,
        binding=binding,
        repository_id=repository_id,
        field_path=field.field_path,
        direction=direction,
    )
    if leaf is not None:
        response, result, selected, basis = leaf
        attempted.append(field.field_path.rsplit(".", 1)[-1])
        return _resolved_side(
            repository_id=repository_id,
            binding=binding,
            direction=direction,
            requested_anchor=source_ref,
            attempted_anchors=attempted,
            response=response,
            result=result,
            selected=selected,
            basis=basis,
        )

    if last is None:
        response: Mapping[str, Any] = {"result": {"status": "source_not_found", "paths": [], "gaps": []}}
        result = _result(response)
        selected = None
        basis = "no_deterministic_anchor_candidate"
    else:
        response, result, selected, basis = last
    return _resolved_side(
        repository_id=repository_id,
        binding=binding,
        direction=direction,
        requested_anchor=source_ref,
        attempted_anchors=attempted,
        response=response,
        result=result,
        selected=selected,
        basis=basis,
    )


def _observed_child_expansion(
    gateway: AislPathGateway,
    *,
    binding,
    repository_id: str,
    side: Mapping[str, Any],
) -> dict[str, Any] | None:
    anchor = side.get("resolved_anchor")
    if not isinstance(anchor, Mapping):
        return None
    operation = str(anchor.get("operation") or "").strip()
    parent_ref = str(anchor.get("display_ref") or "").strip()
    if not operation or not parent_ref:
        return None
    listing = gateway.list_repository_value_nodes(
        binding,
        repository_id=repository_id,
        node_kind="field",
        operation=operation,
        max_results=500,
    )
    listing_result = _result(listing)
    prefix = parent_ref + "."
    children: list[dict[str, Any]] = []
    for node in listing_result.get("items") or ():
        if not isinstance(node, Mapping):
            continue
        display_ref = str(node.get("display_ref") or "")
        if not display_ref.startswith(prefix):
            continue
        remainder = display_ref[len(prefix):]
        if not remainder or "." in remainder:
            continue
        value_node_id = str(node.get("value_node_id") or "")
        if not value_node_id:
            continue
        query = gateway.resolve_attribute_paths(
            binding,
            source=value_node_id,
            selected_repo_ids=binding.query_repo_ids(repository_id),
            direction="forward",
        )
        children.append({
            "field": remainder,
            "node": dict(node),
            "query": dict(query),
        })
    if not children:
        return None
    children.sort(key=lambda item: (item["field"], str(item["node"].get("value_node_id") or "")))
    return {
        "basis": "exact_operation_local_field_prefix",
        "operation": operation,
        "parent_display_ref": parent_ref,
        "children": children,
        "listing_truncated": bool(listing_result.get("truncated")),
        "next_token": listing_result.get("next_token"),
    }



def _side_has_observed_continuation(side: Mapping[str, Any]) -> bool:
    if str(side.get("anchor_status") or "") != "resolved":
        return False
    anchor = side.get("resolved_anchor")
    query = side.get("query")
    if not isinstance(anchor, Mapping) or not isinstance(query, Mapping):
        return False
    result = _result(query)
    score = _local_continuation_score(result, anchor=anchor)
    return score[0] > 0 or score[1] > 0


def _is_collection_type(type_ref: str) -> bool:
    text = str(type_ref or "").replace(" ", "")
    return text.endswith("[]") or any(
        marker in text for marker in ("List<", "Set<", "Collection<", "Iterable<")
    )


def _source_boundary_shape_fields(
    catalog: Sequence[Mapping[str, Any]],
    *,
    edge: Mapping[str, Any],
    parent_fields: Sequence[BoundaryField],
    expandable_parents: set[str],
) -> list[BoundaryField]:
    """Project exact published source boundary structure under used topology branches.

    Topology remains the transport owner: this only extends an already matched edge
    under a published topology parent.  Structure comes from the exact route/payload
    boundary facts already published by AISL.  The most-specific published topology
    parent gates each descendant, so an unused sibling branch cannot expand merely
    because its schema exists.
    """
    if not parent_fields:
        return []
    exemplar = parent_fields[0]
    endpoint = str(edge.get("matched_identity") or "").strip()
    role = exemplar.transport_role
    payload_identity = str(exemplar.source_payload_identity or "").strip()
    repository_id = exemplar.source_repository_id

    raw_nodes: dict[str, Mapping[str, Any]] = {}
    for item in catalog:
        if str(item.get("repo_id") or "") != repository_id:
            continue
        if str(item.get("node_kind") or "") != "field":
            continue
        payload = _node_payload(item)
        occurrence = payload.get("source_occurrence")
        if not isinstance(occurrence, Mapping):
            continue
        boundary_kind = str(occurrence.get("boundary_kind") or "").strip().casefold()
        edge_protocol = str(edge.get("protocol") or "").strip().casefold()
        if edge_protocol == "http":
            if boundary_kind not in {"http", "rest"}:
                continue
        elif boundary_kind != edge_protocol:
            continue
        if str(occurrence.get("boundary_path") or "").strip() != endpoint:
            continue
        if str(occurrence.get("payload_role") or "").strip().casefold() != role:
            continue
        if str(occurrence.get("interaction_direction") or "").strip().casefold() != "outbound":
            continue
        if payload_identity and str(occurrence.get("payload_type") or "").strip() != payload_identity:
            continue
        raw_path = str(occurrence.get("wire_field_path") or item.get("wire_path") or "").strip()
        if not raw_path:
            continue
        current = raw_nodes.get(raw_path)
        if current is None or str(item.get("value_node_id") or "") < str(current.get("value_node_id") or ""):
            raw_nodes[raw_path] = item

    if not raw_nodes:
        return []

    collection_prefixes = {
        path for path, item in raw_nodes.items()
        if _is_collection_type(str(item.get("type_ref") or ""))
    }

    def canonical_path(raw_path: str) -> str:
        parts = raw_path.split(".")
        out: list[str] = []
        prefix: list[str] = []
        for index, part in enumerate(parts):
            prefix.append(part)
            rendered = part
            if index < len(parts) - 1 and ".".join(prefix) in collection_prefixes:
                rendered += "[]"
            out.append(rendered)
        return ".".join(out)

    base_paths = {field.field_path for field in parent_fields}
    result: list[BoundaryField] = []
    seen: set[str] = set()
    for raw_path in sorted(raw_nodes):
        path = canonical_path(raw_path)
        if path in base_paths:
            continue
        matching_parents = [
            parent for parent in base_paths
            if path.startswith(parent + ".") or path.startswith(parent + "[]" + ".")
        ]
        if not matching_parents:
            continue
        most_specific = max(matching_parents, key=lambda value: (len(value), value))
        if most_specific not in expandable_parents:
            continue
        if path in seen:
            continue
        seen.add(path)
        result.append(BoundaryField(
            transport_role=role,
            field_path=path,
            source_repository_id=exemplar.source_repository_id,
            target_repository_id=exemplar.target_repository_id,
            source_interface_ids=exemplar.source_interface_ids,
            target_interface_ids=exemplar.target_interface_ids,
            source_payload_identity=exemplar.source_payload_identity,
            target_payload_identity=exemplar.target_payload_identity,
            topology_basis="published_source_boundary_shape_under_observed_topology_branch",
        ))
    return result


def _structural_terminal_side(
    *, repository_id: str, binding, direction: str, field: BoundaryField,
) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "system_id": binding.system_id,
        "revision_id": binding.revision_id,
        "direction": direction,
        "requested_anchor": wire_display_ref(field.transport_role, field.field_path),
        "attempted_anchors": [],
        "resolved_anchor": None,
        "anchor_status": "terminal",
        "anchor_selection_basis": "exact_transport_structure_no_observed_local_use",
        "query": {"result": {"status": "resolved_terminal", "paths": [], "gaps": []}},
        "terminal_proof": {
            "source_boundary_structure": True,
            "payload_identity_exact": _payload_compatible(field),
            "field_path": field.field_path,
        },
    }

def _payload_compatible(field: BoundaryField) -> bool:
    return bool(
        field.source_payload_identity
        and field.target_payload_identity
        and field.source_payload_identity == field.target_payload_identity
    )


def _gap(repository_id: str, field: BoundaryField, side: str, reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "repository_id": repository_id,
        "transport_role": field.transport_role,
        "field_path": field.field_path,
        "side": side,
    }


def build_interaction_lineage(
    topology: Mapping[str, Any],
    *,
    edge_id: str,
    bindings: BindingIndex,
    gateway: AislPathGateway,
    transport_roles: Sequence[str] = ("request", "response"),
) -> dict[str, Any]:
    edge = select_edge(topology, edge_id)
    journeys: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    used_bindings: dict[str, Any] = {}
    node_catalog_cache: dict[tuple[str, ...], tuple[list[Mapping[str, Any]], bool]] = {}

    def process(field: BoundaryField, *, structural_expansion: bool = False) -> dict[str, Any]:
        source_binding = bindings.require(field.source_repository_id)
        target_binding = bindings.require(field.target_repository_id)
        used_bindings[source_binding.repository_id] = source_binding
        used_bindings[target_binding.repository_id] = target_binding
        source_ref = wire_display_ref(field.transport_role, field.field_path)
        source_side = _resolve_side(
            gateway, edge=edge, field=field, side="source", binding=source_binding,
            repository_id=field.source_repository_id, interface_ids=field.source_interface_ids,
            payload_identity=field.source_payload_identity, source_ref=source_ref, direction="reverse",
            node_catalog_cache=node_catalog_cache,
        )
        target_side = _resolve_side(
            gateway, edge=edge, field=field, side="target", binding=target_binding,
            repository_id=field.target_repository_id, interface_ids=field.target_interface_ids,
            payload_identity=field.target_payload_identity, source_ref=source_ref, direction="forward",
            node_catalog_cache=node_catalog_cache,
        )
        if structural_expansion and _payload_compatible(field):
            # A structural-expanded row asserts only exact transport shape beneath
            # an already-observed topology branch.  If repository-local value flow
            # does not resolve on either side, preserve that distinction as a
            # terminal/no-field-specific-flow state rather than manufacturing a
            # lineage gap.  Any observed local flow still wins and stays resolved.
            if source_side["anchor_status"] == "unresolved":
                source_side = _structural_terminal_side(
                    repository_id=field.source_repository_id, binding=source_binding,
                    direction="reverse", field=field,
                )
            if target_side["anchor_status"] == "unresolved":
                target_side = _structural_terminal_side(
                    repository_id=field.target_repository_id, binding=target_binding,
                    direction="forward", field=field,
                )

        payload_compatible = _payload_compatible(field)
        crossing_status = "resolved" if payload_compatible else "partial"
        crossing_basis = (
            "exact_field_path_within_matched_transport_payload"
            if payload_compatible else "insufficient_exact_boundary_evidence"
        )
        if not payload_compatible:
            gaps.append(_gap(field.source_repository_id, field, "crossing", "payload_identity_not_exactly_compatible"))
        if source_side["anchor_status"] == "unresolved":
            gaps.append(_gap(field.source_repository_id, field, "source", "source_local_anchor_unresolved"))
        if target_side["anchor_status"] == "unresolved":
            gaps.append(_gap(field.target_repository_id, field, "target", "target_local_anchor_unresolved"))

        if source_side["anchor_status"] == "resolved" and not structural_expansion:
            source_catalog, source_catalog_complete = _repository_node_catalog(
                gateway,
                binding=source_binding,
                repository_id=field.source_repository_id,
                cache=node_catalog_cache,
            )
            material_gap = _material_source_origin_gap(
                source_side,
                catalog=source_catalog,
                catalog_complete=source_catalog_complete,
            )
            if material_gap is not None:
                external_evidence = _external_origin_evidence(
                    gateway,
                    binding=source_binding,
                    repository_id=field.source_repository_id,
                    material_gap=material_gap,
                    cache=node_catalog_cache,
                    resolved_side=source_side,
                    local_catalog=source_catalog,
                    local_catalog_complete=source_catalog_complete,
                )
                if external_evidence is not None:
                    source_side["external_origin_evidence"] = dict(external_evidence)
                    semantic_source = _source_semantic_projection(
                        source_side, external_evidence=external_evidence,
                    )
                    if semantic_source is not None:
                        source_side["semantic_projection"] = dict(semantic_source)
                    gap = _gap(
                        field.source_repository_id, field, "source",
                        "source_external_origin_link_unproven",
                    )
                    gap["evidence"] = list(material_gap.get("evidence") or ())
                    gap["external_origin_evidence"] = dict(external_evidence)
                    gaps.append(gap)
                else:
                    gap = _gap(
                        field.source_repository_id, field, "source",
                        str(material_gap["reason"]),
                    )
                    gap["evidence"] = list(material_gap.get("evidence") or ())
                    gaps.append(gap)

        identity = {
            "edge_id": edge_id,
            "transport_role": field.transport_role,
            "field_path": field.field_path,
            "source_repository_id": field.source_repository_id,
            "target_repository_id": field.target_repository_id,
        }
        journey = {
            "journey_id": "interaction_attribute_journey_" + _fingerprint(identity)[:24],
            **identity,
            "topology_basis": field.topology_basis,
            "crossing": {
                "status": crossing_status,
                "basis": crossing_basis,
                "source_payload_identity": field.source_payload_identity,
                "target_payload_identity": field.target_payload_identity,
                "source_interface_ids": list(field.source_interface_ids),
                "target_interface_ids": list(field.target_interface_ids),
            },
            "source_side": source_side,
            "target_side": target_side,
        }
        journeys.append(journey)
        return journey

    for role in transport_roles:
        base_fields = boundary_fields(edge, transport_role=role)
        base_journeys: dict[str, dict[str, Any]] = {}
        for field in base_fields:
            base_journeys[field.field_path] = process(field)

        # Old topology fixtures intentionally publish only stable branch roots.
        # Extend those roots from exact source route-boundary facts, but only below
        # the most-specific topology branch that has observed consumer continuation.
        expandable = {
            path for path, journey in base_journeys.items()
            if _side_has_observed_continuation(journey["target_side"])
        }
        if base_fields and expandable:
            source_binding = bindings.require(base_fields[0].source_repository_id)
            catalog, complete = _repository_node_catalog(
                gateway, binding=source_binding,
                repository_id=base_fields[0].source_repository_id, cache=node_catalog_cache,
            )
            if complete:
                for field in _source_boundary_shape_fields(
                    catalog, edge=edge, parent_fields=base_fields, expandable_parents=expandable,
                ):
                    process(field, structural_expansion=True)

    # Attach direct observed target child evidence for diagnostics/UI only; the
    # canonical journey rows above already include permitted structural expansion.
    for journey in journeys:
        target_binding = bindings.require(journey["target_repository_id"])
        target_catalog, target_catalog_complete = _repository_node_catalog(
            gateway, binding=target_binding, repository_id=journey["target_repository_id"],
            cache=node_catalog_cache,
        )
        if target_catalog_complete:
            semantic_projection = _target_semantic_projection(
                journey["target_side"], catalog=target_catalog,
            )
            if semantic_projection is not None:
                journey["target_side"]["semantic_projection"] = dict(semantic_projection)
        child_expansion = _observed_child_expansion(
            gateway, binding=target_binding, repository_id=journey["target_repository_id"],
            side=journey["target_side"],
        )
        if child_expansion is not None:
            journey["target_side"]["observed_child_expansion"] = child_expansion

    journeys.sort(key=lambda item: (item["transport_role"], item["field_path"], item["journey_id"]))
    gaps.sort(key=lambda item: (item["transport_role"], item["field_path"], item["side"], item["repository_id"], item["reason"]))
    output = {
        "format": OUTPUT_FORMAT,
        "topology_id": str(topology.get("topology_id") or ""),
        "topology_fingerprint": _fingerprint(topology),
        "edge": {
            "edge_id": str(edge.get("edge_id") or ""), "protocol": edge.get("protocol"),
            "method": edge.get("method"), "matched_identity": edge.get("matched_identity"),
            "match_classification": edge.get("match_classification"),
            "claim_classification": edge.get("claim_classification"), "confidence": edge.get("confidence"),
            "source_repository_id": edge.get("source_repository_id"),
            "target_repository_id": edge.get("target_repository_id"),
        },
        "aisl_inputs": [used_bindings[key].to_dict() for key in sorted(used_bindings)],
        "journeys": journeys,
        "gaps": gaps,
        "summary": {
            "journey_count": len(journeys),
            "resolved_crossing_count": sum(1 for item in journeys if item["crossing"]["status"] == "resolved"),
            "partial_crossing_count": sum(1 for item in journeys if item["crossing"]["status"] != "resolved"),
            "source_local_anchor_gap_count": sum(1 for item in gaps if item["reason"] == "source_local_anchor_unresolved"),
            "source_material_semantic_gap_count": sum(1 for item in gaps if item["reason"] == "source_external_origin_unresolved"),
            "source_external_origin_link_gap_count": sum(1 for item in gaps if item["reason"] == "source_external_origin_link_unproven"),
            "target_local_anchor_gap_count": sum(1 for item in gaps if item["reason"] == "target_local_anchor_unresolved"),
            "gap_count": len(gaps),
        },
    }
    output["content_fingerprint"] = _fingerprint(output)
    return output

