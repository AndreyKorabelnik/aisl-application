from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Any

from .attributes import ATTRIBUTE_NAME_COMPARISON, RENAME_INFERENCE, edge_attribute_flows
from .contracts import ATTRIBUTE_PATH_FORMAT, TOPOLOGY_FORMAT


def find_attribute_paths(
    topology: dict[str, Any],
    *,
    attribute_name: str,
    source_repository_id: str | None = None,
    target_repository_id: str | None = None,
) -> dict[str, Any]:
    """Discover directed exact-name-preserving repository routes.

    Query scope is controlled only by the optional repository bounds:
    - both bounds: all shortest routes between the two repositories;
    - source only: all shortest routes from source to every reachable repository;
    - target only: all shortest routes from every reachable repository to target;
    - no bounds: the complete attribute-specific directed crossing subgraph.

    The result is intentionally a name-preserving route view, not code-level
    data lineage. Crossing an intermediate repository assumes continuity only
    while the exact case-sensitive attribute name remains unchanged.
    """
    repository_ids = _validate_query(topology, attribute_name, source_repository_id, target_repository_id)
    crossings = _attribute_crossings(topology, attribute_name)
    query_scope = _query_scope(source_repository_id, target_repository_id)

    if query_scope == "between_repositories":
        assert source_repository_id is not None and target_repository_id is not None
        raw_paths = _all_shortest_paths(crossings, source_repository_id, target_repository_id)
        public_paths = [
            _public_path(source_repository_id, target_repository_id, crossings_path)
            for crossings_path in raw_paths
        ]
        selected_crossings = _crossing_union(public_paths)
    elif query_scope == "from_repository":
        assert source_repository_id is not None
        paths_by_target = _all_shortest_paths_from_source(crossings, source_repository_id)
        public_paths = []
        for target_id in sorted(paths_by_target):
            if target_id == source_repository_id:
                continue
            public_paths.extend(
                _public_path(source_repository_id, target_id, crossings_path)
                for crossings_path in paths_by_target[target_id]
            )
        selected_crossings = _crossing_union(public_paths)
    elif query_scope == "to_repository":
        assert target_repository_id is not None
        paths_by_source = _all_shortest_paths_to_target(crossings, target_repository_id, repository_ids)
        public_paths = []
        for source_id in sorted(paths_by_source):
            if source_id == target_repository_id:
                continue
            public_paths.extend(
                _public_path(source_id, target_repository_id, crossings_path)
                for crossings_path in paths_by_source[source_id]
            )
        selected_crossings = _crossing_union(public_paths)
    else:
        public_paths = []
        selected_crossings = crossings

    found = bool(selected_crossings) or (
        query_scope == "between_repositories"
        and source_repository_id == target_repository_id
    )
    status = "found" if found else "not_found"
    diagnostics = _diagnostics(
        status=status,
        query_scope=query_scope,
        attribute_name=attribute_name,
        source_repository_id=source_repository_id,
        target_repository_id=target_repository_id,
    )

    basis = {
        "topology_id": topology.get("topology_id"),
        "attribute_name": attribute_name,
        "query_scope": query_scope,
        "source_repository_id": source_repository_id,
        "target_repository_id": target_repository_id,
        "selected_crossings": selected_crossings,
        "paths": public_paths,
    }
    query_id = "repository_attribute_path_" + hashlib.sha256(_canonical_bytes(basis)).hexdigest()[:24]
    shortest_hop_counts = [path["hop_count"] for path in public_paths]
    return {
        "format": ATTRIBUTE_PATH_FORMAT,
        "query_id": query_id,
        "topology_id": topology.get("topology_id"),
        "attribute_name": attribute_name,
        "query_scope": query_scope,
        "source_repository_id": source_repository_id,
        "target_repository_id": target_repository_id,
        "status": status,
        "path_semantics": {
            "kind": "name_preserving_repository_route",
            "code_level_data_lineage": False,
            "attribute_name_comparison": ATTRIBUTE_NAME_COMPARISON,
            "rename_inference": RENAME_INFERENCE,
            "intra_repository_continuity": "same_exact_name_assumed",
            "unbounded_query_representation": "attribute_specific_directed_subgraph",
        },
        "selected_crossings": selected_crossings,
        "paths": public_paths,
        "diagnostics": diagnostics,
        "summary": {
            "candidate_crossing_count": len(crossings),
            "selected_crossing_count": len(selected_crossings),
            "path_count": len(public_paths),
            "shortest_path_count": len(public_paths),
            "shortest_hop_count": min(shortest_hop_counts) if shortest_hop_counts else None,
        },
    }


def _query_scope(source_repository_id: str | None, target_repository_id: str | None) -> str:
    if source_repository_id is not None and target_repository_id is not None:
        return "between_repositories"
    if source_repository_id is not None:
        return "from_repository"
    if target_repository_id is not None:
        return "to_repository"
    return "all_repositories"


def _validate_query(
    topology: dict[str, Any],
    attribute_name: str,
    source_repository_id: str | None,
    target_repository_id: str | None,
) -> set[str]:
    if topology.get("format") != TOPOLOGY_FORMAT:
        raise ValueError(f"unsupported topology format: {topology.get('format')!r}; expected {TOPOLOGY_FORMAT!r}")
    if not attribute_name:
        raise ValueError("attribute_name must be non-empty")
    repository_ids = {
        str(row.get("repository_id"))
        for row in topology.get("repositories") or []
        if isinstance(row, dict) and row.get("repository_id")
    }
    if source_repository_id is not None and source_repository_id not in repository_ids:
        raise ValueError(f"unknown source_repository_id: {source_repository_id}")
    if target_repository_id is not None and target_repository_id not in repository_ids:
        raise ValueError(f"unknown target_repository_id: {target_repository_id}")
    return repository_ids


def _diagnostics(
    *,
    status: str,
    query_scope: str,
    attribute_name: str,
    source_repository_id: str | None,
    target_repository_id: str | None,
) -> list[dict[str, Any]]:
    if status == "found":
        return []
    diagnostic: dict[str, Any] = {
        "kind": {
            "between_repositories": "no_exact_name_preserving_path",
            "from_repository": "no_reachable_exact_name_preserving_path_from_repository",
            "to_repository": "no_reachable_exact_name_preserving_path_to_repository",
            "all_repositories": "no_attribute_crossings",
        }[query_scope],
        "attribute_name": attribute_name,
    }
    if source_repository_id is not None:
        diagnostic["source_repository_id"] = source_repository_id
    if target_repository_id is not None:
        diagnostic["target_repository_id"] = target_repository_id
    return [diagnostic]


def _public_path(
    source_repository_id: str,
    target_repository_id: str,
    crossings_path: list[dict[str, Any]],
) -> dict[str, Any]:
    repository_ids = [source_repository_id]
    for crossing in crossings_path:
        repository_ids.append(crossing["target_repository_id"])
    return {
        "source_repository_id": source_repository_id,
        "target_repository_id": target_repository_id,
        "hop_count": len(crossings_path),
        "repository_ids": repository_ids,
        "path_match_classification": (
            "probable"
            if any(row["match_classification"] == "probable" for row in crossings_path)
            else "exact"
        ),
        "crossings": crossings_path,
    }


def _crossing_union(paths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for path in paths:
        for crossing in path.get("crossings") or []:
            by_key[_crossing_identity(crossing)] = crossing
    return [by_key[key] for key in sorted(by_key)]


def _attribute_crossings(topology: dict[str, Any], attribute_name: str) -> list[dict[str, Any]]:
    crossings: list[dict[str, Any]] = []
    for edge in sorted(topology.get("edges") or [], key=_edge_sort_key):
        for flow in edge_attribute_flows(edge):
            if attribute_name not in (flow.get("attribute_names") or []):
                continue
            attribute_basis = [
                row
                for row in flow.get("basis") or []
                if isinstance(row, dict) and row.get("attribute_name") == attribute_name
            ]
            crossings.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "protocol": str(edge.get("protocol") or ""),
                    "transport_role": str(flow.get("transport_role") or ""),
                    "source_repository_id": str(flow.get("source_repository_id") or ""),
                    "target_repository_id": str(flow.get("target_repository_id") or ""),
                    "attribute_name": attribute_name,
                    "method": edge.get("method"),
                    "matched_identity": str(edge.get("matched_identity") or ""),
                    "match_classification": str(edge.get("match_classification") or ""),
                    "claim_classification": str(edge.get("claim_classification") or ""),
                    "confidence": str(edge.get("confidence") or ""),
                    "basis": attribute_basis,
                }
            )
    crossings.sort(key=_crossing_sort_key)
    return crossings


def _all_shortest_paths(
    crossings: list[dict[str, Any]],
    source_repository_id: str,
    target_repository_id: str,
) -> list[list[dict[str, Any]]]:
    return _all_shortest_paths_from_source(crossings, source_repository_id).get(target_repository_id, [])


def _all_shortest_paths_from_source(
    crossings: list[dict[str, Any]],
    source_repository_id: str,
) -> dict[str, list[list[dict[str, Any]]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for crossing in crossings:
        adjacency[crossing["source_repository_id"]].append(crossing)
    for rows in adjacency.values():
        rows.sort(key=_crossing_sort_key)

    distance = {source_repository_id: 0}
    parents: dict[str, list[dict[str, Any]]] = defaultdict(list)
    queue = deque([source_repository_id])
    while queue:
        repository_id = queue.popleft()
        current_distance = distance[repository_id]
        for crossing in adjacency.get(repository_id, []):
            nxt = crossing["target_repository_id"]
            next_distance = current_distance + 1
            if nxt not in distance:
                distance[nxt] = next_distance
                parents[nxt].append(crossing)
                queue.append(nxt)
            elif distance[nxt] == next_distance:
                parents[nxt].append(crossing)

    memo: dict[str, list[list[dict[str, Any]]]] = {source_repository_id: [[]]}

    def build(repository_id: str) -> list[list[dict[str, Any]]]:
        if repository_id in memo:
            return memo[repository_id]
        result: list[list[dict[str, Any]]] = []
        for crossing in sorted(parents.get(repository_id, []), key=_crossing_sort_key):
            previous_repository_id = crossing["source_repository_id"]
            for prefix in build(previous_repository_id):
                result.append([*prefix, crossing])
        result.sort(key=_canonical_bytes)
        memo[repository_id] = result
        return result

    return {repository_id: build(repository_id) for repository_id in sorted(distance)}


def _all_shortest_paths_to_target(
    crossings: list[dict[str, Any]],
    target_repository_id: str,
    repository_ids: set[str],
) -> dict[str, list[list[dict[str, Any]]]]:
    result: dict[str, list[list[dict[str, Any]]]] = {}
    for source_repository_id in sorted(repository_ids):
        paths = _all_shortest_paths(crossings, source_repository_id, target_repository_id)
        if paths:
            result[source_repository_id] = paths
    return result


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(edge.get("source_repository_id") or ""),
        str(edge.get("target_repository_id") or ""),
        str(edge.get("protocol") or ""),
        str(edge.get("method") or ""),
        str(edge.get("matched_identity") or ""),
        str(edge.get("edge_id") or ""),
    )


def _crossing_identity(crossing: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(crossing.get("source_repository_id") or ""),
        str(crossing.get("target_repository_id") or ""),
        str(crossing.get("protocol") or ""),
        str(crossing.get("transport_role") or ""),
        str(crossing.get("matched_identity") or ""),
        str(crossing.get("edge_id") or ""),
    )


def _crossing_sort_key(crossing: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return _crossing_identity(crossing)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
