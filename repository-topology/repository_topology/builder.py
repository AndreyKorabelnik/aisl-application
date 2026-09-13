from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .attributes import ATTRIBUTE_NAME_COMPARISON, RENAME_INFERENCE, pair_attribute_flows
from .contracts import TOPOLOGY_FORMAT
from .matching import Match, analyze_matchability, match_all
from .model import HalfWire
from .reader import load_reduced_inventory


def build_topology(paths: Iterable[Path]) -> dict[str, Any]:
    normalized_paths = [Path(p) for p in paths]
    if len(normalized_paths) < 2:
        raise ValueError("repository-topology requires at least two Reduced Inventory inputs")

    inputs: list[dict[str, Any]] = []
    all_half_wires: list[HalfWire] = []
    repository_ids: set[str] = set()
    for index, path in enumerate(normalized_paths):
        input_record, half_wires = load_reduced_inventory(path, input_index=index)
        repository_id = input_record["repository_id"]
        if repository_id in repository_ids:
            raise ValueError(f"duplicate repository_id input: {repository_id}")
        repository_ids.add(repository_id)
        inputs.append(input_record)
        all_half_wires.extend(half_wires)

    inputs.sort(key=lambda r: r["repository_id"])
    matches = match_all(all_half_wires)
    edges = _consolidate_matches(matches)
    islands = _build_islands(sorted(repository_ids), edges)
    matchability_analysis, diagnostics = analyze_matchability(all_half_wires, matches, repository_ids=repository_ids)
    basis = {
        "format": TOPOLOGY_FORMAT,
        "inputs": [{k: row[k] for k in ("repository_id", "artifact_id", "semantic_fingerprint", "sha256")} for row in inputs],
        "edges": [row["edge_id"] for row in edges],
        "islands": [row["island_id"] for row in islands],
    }
    topology_id = "repository_topology_" + hashlib.sha256(_canonical_bytes(basis)).hexdigest()[:24]
    return {
        "format": TOPOLOGY_FORMAT,
        "topology_id": topology_id,
        "inputs": inputs,
        "repositories": [
            {"repository_id": row["repository_id"], "input_ref": row["artifact_id"]}
            for row in inputs
        ],
        "edges": edges,
        "islands": islands,
        "diagnostics": diagnostics,
        "matchability_analysis": matchability_analysis,
        "attribute_identity_policy": {
            "name_comparison": ATTRIBUTE_NAME_COMPARISON,
            "rename_inference": RENAME_INFERENCE,
        },
        "summary": {
            "repository_count": len(repository_ids),
            "edge_count": len(edges),
            "exact_edge_count": sum(1 for e in edges if e["match_classification"] == "exact"),
            "probable_edge_count": sum(1 for e in edges if e["match_classification"] == "probable"),
            "island_count": len(islands),
            "half_wire_count": matchability_analysis["summary"]["half_wire_count"],
            "matched_half_wire_count": matchability_analysis["summary"]["matched_half_wire_count"],
            "unmatched_half_wire_count": matchability_analysis["summary"]["unmatched_half_wire_count"],
            "repository_with_half_wire_count": matchability_analysis["summary"]["repository_with_half_wire_count"],
            "repository_without_half_wire_count": matchability_analysis["summary"]["repository_without_half_wire_count"],
        },
    }


def _consolidate_matches(matches: list[Match]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str | None, str], list[Match]] = defaultdict(list)
    for match in matches:
        key = (
            match.source.repository_id,
            match.target.repository_id,
            match.source.protocol,
            match.source.method,
            match.matched_identity,
        )
        groups[key].append(match)

    edges: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        strongest = min(group, key=lambda m: 0 if m.classification == "exact" else 1)
        source_refs = _unique_half_wire_refs(m.source for m in group)
        target_refs = _unique_half_wire_refs(m.target for m in group)
        edge_basis = {
            "source_repository_id": key[0],
            "target_repository_id": key[1],
            "protocol": key[2],
            "method": key[3],
            "matched_identity": key[4],
        }
        edge_id = "repository_edge_" + hashlib.sha256(_canonical_bytes(edge_basis)).hexdigest()[:24]
        basis = []
        seen_basis = set()
        for match in group:
            for item in match.basis:
                encoded = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                if encoded not in seen_basis:
                    seen_basis.add(encoded)
                    basis.append(item)
        edges.append(
            {
                "edge_id": edge_id,
                "protocol": key[2],
                "method": key[3],
                "matched_identity": key[4],
                "source_repository_id": key[0],
                "target_repository_id": key[1],
                "match_classification": strongest.classification,
                "claim_classification": strongest.claim_classification,
                "confidence": strongest.confidence,
                "source_half_wires": source_refs,
                "target_half_wires": target_refs,
                "attribute_flows": _consolidate_attribute_flows(group),
                "basis": basis,
            }
        )
    return edges


def _consolidate_attribute_flows(group: list[Match]) -> list[dict[str, Any]]:
    by_flow: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for match in group:
        for flow in pair_attribute_flows(match.source, match.target):
            flow_key = (
                str(flow["transport_role"]),
                str(flow["source_repository_id"]),
                str(flow["target_repository_id"]),
            )
            for attribute_name in flow.get("attribute_names") or []:
                by_flow[flow_key][str(attribute_name)].append(
                    {
                        "attribute_name": str(attribute_name),
                        "edge_source_observed_identity_id": match.source.observed_identity_id,
                        "edge_target_observed_identity_id": match.target.observed_identity_id,
                    }
                )

    result: list[dict[str, Any]] = []
    for flow_key in sorted(by_flow):
        evidence_by_name = by_flow[flow_key]
        basis: list[dict[str, str]] = []
        for attribute_name in sorted(evidence_by_name):
            unique = {
                (row["attribute_name"], row["edge_source_observed_identity_id"], row["edge_target_observed_identity_id"]): row
                for row in evidence_by_name[attribute_name]
            }
            basis.extend(unique[key] for key in sorted(unique))
        result.append(
            {
                "transport_role": flow_key[0],
                "source_repository_id": flow_key[1],
                "target_repository_id": flow_key[2],
                "attribute_names": sorted(evidence_by_name),
                "basis": basis,
            }
        )
    return result


def _unique_half_wire_refs(half_wires: Iterable[HalfWire]) -> list[dict[str, Any]]:
    by_id = {half_wire.observed_identity_id: half_wire.public_ref() for half_wire in half_wires}
    return [by_id[key] for key in sorted(by_id)]


def _build_islands(repository_ids: list[str], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjacency = {repo: set() for repo in repository_ids}
    edge_ids_by_repo_pair: dict[frozenset[str], list[str]] = defaultdict(list)
    for edge in edges:
        source = edge["source_repository_id"]
        target = edge["target_repository_id"]
        adjacency[source].add(target)
        adjacency[target].add(source)
        edge_ids_by_repo_pair[frozenset((source, target))].append(edge["edge_id"])

    islands = []
    visited = set()
    for start in repository_ids:
        if start in visited:
            continue
        queue = deque([start])
        component = []
        visited.add(start)
        while queue:
            node = queue.popleft()
            component.append(node)
            for nxt in sorted(adjacency[node]):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        component = sorted(component)
        component_set = set(component)
        edge_ids = sorted(
            edge["edge_id"]
            for edge in edges
            if edge["source_repository_id"] in component_set and edge["target_repository_id"] in component_set
        )
        island_basis = {"repository_ids": component, "edge_ids": edge_ids}
        island_id = "repository_island_" + hashlib.sha256(_canonical_bytes(island_basis)).hexdigest()[:24]
        islands.append({"island_id": island_id, "repository_ids": component, "edge_ids": edge_ids})
    islands.sort(key=lambda row: (row["repository_ids"], row["island_id"]))
    return islands


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
