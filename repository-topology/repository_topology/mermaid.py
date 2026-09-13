from __future__ import annotations

import hashlib
from typing import Any

from .attributes import edge_display_attributes
from .contracts import ATTRIBUTE_PATH_FORMAT, TOPOLOGY_FORMAT


def render_repository_mermaid(topology: dict[str, Any]) -> str:
    """Render a deterministic Mermaid repository graph from repository-topology/v3."""
    if topology.get("format") != TOPOLOGY_FORMAT:
        raise ValueError(f"unsupported topology format: {topology.get('format')!r}; expected {TOPOLOGY_FORMAT!r}")

    repository_ids = sorted(
        str(row.get("repository_id"))
        for row in topology.get("repositories") or []
        if isinstance(row, dict) and row.get("repository_id")
    )
    node_ids = {repository_id: _node_id(repository_id) for repository_id in repository_ids}
    lines = ["flowchart LR"]
    for repository_id in repository_ids:
        lines.append(f'    {node_ids[repository_id]}["{_escape(repository_id)}"]')

    for edge in sorted(topology.get("edges") or [], key=_edge_sort_key):
        source = str(edge.get("source_repository_id") or "")
        target = str(edge.get("target_repository_id") or "")
        if source not in node_ids or target not in node_ids:
            continue
        arrow = "-.->" if edge.get("match_classification") == "probable" else "-->"
        label = _edge_label(edge)
        lines.append(
            f'    {node_ids[source]} {arrow}|"{_escape(label)}"| {node_ids[target]}'
        )
    return "\n".join(lines) + "\n"


def _edge_label(edge: dict[str, Any]) -> str:
    protocol = str(edge.get("protocol") or "")
    matched_identity = str(edge.get("matched_identity") or "")
    method = edge.get("method")
    if protocol == "http":
        head = " ".join(part for part in (str(method or ""), matched_identity) if part) or "HTTP"
    elif protocol == "kafka":
        head = f"Kafka {matched_identity}".strip()
    else:
        head = protocol or "edge"

    attributes = edge_display_attributes(edge)
    parts = [head]
    for role in ("request", "response", "payload"):
        names = attributes.get(role) or []
        if names:
            parts.append(f"{role}: {', '.join(names)}")
    return "<br/>".join(parts)


def _node_id(repository_id: str) -> str:
    return "repo_" + hashlib.sha256(repository_id.encode("utf-8")).hexdigest()[:12]


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<br/>", "__BR__")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("__BR__", "<br/>")
    )


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(edge.get("source_repository_id") or ""),
        str(edge.get("target_repository_id") or ""),
        str(edge.get("protocol") or ""),
        str(edge.get("method") or ""),
        str(edge.get("matched_identity") or ""),
        str(edge.get("edge_id") or ""),
    )


def render_attribute_path_mermaid(result: dict[str, Any]) -> str:
    """Render the selected exact-name-preserving attribute crossing subgraph."""
    if result.get("format") != ATTRIBUTE_PATH_FORMAT:
        raise ValueError(
            f"unsupported attribute path format: {result.get('format')!r}; expected {ATTRIBUTE_PATH_FORMAT!r}"
        )

    repository_ids = {
        str(result.get("source_repository_id") or ""),
        str(result.get("target_repository_id") or ""),
    }
    crossings_by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for crossing in result.get("selected_crossings") or []:
        key = (
            str(crossing.get("source_repository_id") or ""),
            str(crossing.get("target_repository_id") or ""),
            str(crossing.get("protocol") or ""),
            str(crossing.get("transport_role") or ""),
            str(crossing.get("matched_identity") or ""),
            str(crossing.get("edge_id") or ""),
        )
        crossings_by_key[key] = crossing
        repository_ids.add(key[0])
        repository_ids.add(key[1])
    for path in result.get("paths") or []:
        for repository_id in path.get("repository_ids") or []:
            if repository_id:
                repository_ids.add(str(repository_id))

    repository_ids.discard("")
    node_ids = {repository_id: _node_id(repository_id) for repository_id in sorted(repository_ids)}
    lines = ["flowchart LR"]
    for repository_id in sorted(repository_ids):
        lines.append(f'    {node_ids[repository_id]}["{_escape(repository_id)}"]')
    if result.get("status") != "found":
        lines.append("    %% no exact-name-preserving attribute crossing found")
        return "\n".join(lines) + "\n"

    for key in sorted(crossings_by_key):
        crossing = crossings_by_key[key]
        source = str(crossing["source_repository_id"])
        target = str(crossing["target_repository_id"])
        arrow = "-.->" if crossing.get("match_classification") == "probable" else "-->"
        label = _attribute_crossing_label(crossing)
        lines.append(f'    {node_ids[source]} {arrow}|"{_escape(label)}"| {node_ids[target]}')
    return "\n".join(lines) + "\n"

def _attribute_crossing_label(crossing: dict[str, Any]) -> str:
    protocol = str(crossing.get("protocol") or "")
    identity = str(crossing.get("matched_identity") or "")
    role = str(crossing.get("transport_role") or "")
    attribute_name = str(crossing.get("attribute_name") or "")
    if protocol == "http":
        method = str(crossing.get("method") or "")
        head = " ".join(part for part in (method, identity) if part) or "HTTP"
    elif protocol == "kafka":
        head = f"Kafka {identity}".strip()
    else:
        head = protocol or "edge"
    return f"{head}<br/>{role}: {attribute_name}"
