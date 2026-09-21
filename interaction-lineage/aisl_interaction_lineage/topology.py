from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

TOPOLOGY_FORMAT = "repository-topology/v4"


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value or () if isinstance(item, Mapping)]


def _texts(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or ():
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _root(path: str) -> str:
    return path.split(".", 1)[0].split("[", 1)[0]


@dataclass(frozen=True, slots=True)
class BoundaryField:
    transport_role: str
    field_path: str
    source_repository_id: str
    target_repository_id: str
    source_interface_ids: tuple[str, ...]
    target_interface_ids: tuple[str, ...]
    source_payload_identity: str | None
    target_payload_identity: str | None
    topology_basis: str


def validate_topology(payload: Mapping[str, Any]) -> None:
    if payload.get("format") != TOPOLOGY_FORMAT:
        raise ValueError(f"expected {TOPOLOGY_FORMAT}, got {payload.get('format')!r}")
    if not str(payload.get("topology_id") or "").strip():
        raise ValueError("topology_id must not be empty")
    if not isinstance(payload.get("edges"), list):
        raise ValueError("topology.edges must be an array")


def select_edge(topology: Mapping[str, Any], edge_id: str) -> Mapping[str, Any]:
    validate_topology(topology)
    matches = [edge for edge in _rows(topology.get("edges")) if str(edge.get("edge_id") or "") == edge_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one topology edge {edge_id!r}, found {len(matches)}")
    return matches[0]


def _half_wires(edge: Mapping[str, Any], repository_id: str) -> list[Mapping[str, Any]]:
    return [
        item
        for item in [*_rows(edge.get("source_half_wires")), *_rows(edge.get("target_half_wires"))]
        if str(item.get("repository_id") or "") == repository_id
    ]


def _interfaces(edge: Mapping[str, Any], repository_id: str) -> tuple[str, ...]:
    return _texts(item.get("interface_id") for item in _half_wires(edge, repository_id))


def _payload_identities(edge: Mapping[str, Any], repository_id: str, role: str) -> tuple[str, ...]:
    key = f"{role}_payload"
    return _texts(item.get(key) for item in _half_wires(edge, repository_id))


def _shape_paths(edge: Mapping[str, Any], repository_id: str, role: str) -> tuple[str, ...]:
    paths_key = f"{role}_field_paths"
    names_key = f"{role}_field_names"
    result: list[str] = []
    for item in _half_wires(edge, repository_id):
        values = item.get(paths_key) or item.get(names_key) or ()
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
    return tuple(result)


def boundary_fields(edge: Mapping[str, Any], *, transport_role: str) -> list[BoundaryField]:
    role = str(transport_role or "").strip().casefold()
    if role not in {"request", "response"}:
        raise ValueError("transport_role must be request or response")

    flows = [
        item for item in _rows(edge.get("attribute_flows"))
        if str(item.get("transport_role") or "").casefold() == role
    ]
    if not flows:
        return []

    result: list[BoundaryField] = []
    seen: set[tuple[str, str, str]] = set()
    for flow in flows:
        source_repo = str(flow.get("source_repository_id") or "").strip()
        target_repo = str(flow.get("target_repository_id") or "").strip()
        if not source_repo or not target_repo:
            continue
        top_level = _texts(flow.get("attribute_names"))
        if not top_level:
            continue
        candidates: list[tuple[str, str]] = [(name, "topology_attribute_flow") for name in top_level]
        shape_paths = [*_shape_paths(edge, source_repo, role), *_shape_paths(edge, target_repo, role)]
        for path in shape_paths:
            if path not in top_level and _root(path) in top_level:
                candidates.append((path, "topology_payload_shape_under_published_top_level"))

        source_payloads = _payload_identities(edge, source_repo, role)
        target_payloads = _payload_identities(edge, target_repo, role)
        source_payload = source_payloads[0] if len(source_payloads) == 1 else None
        target_payload = target_payloads[0] if len(target_payloads) == 1 else None
        for field_path, basis in candidates:
            key = (role, source_repo, field_path)
            if key in seen:
                continue
            seen.add(key)
            result.append(BoundaryField(
                transport_role=role,
                field_path=field_path,
                source_repository_id=source_repo,
                target_repository_id=target_repo,
                source_interface_ids=_interfaces(edge, source_repo),
                target_interface_ids=_interfaces(edge, target_repo),
                source_payload_identity=source_payload,
                target_payload_identity=target_payload,
                topology_basis=basis,
            ))
    result.sort(key=lambda item: (item.transport_role, item.source_repository_id, item.field_path))
    return result


def wire_display_ref(transport_role: str, field_path: str) -> str:
    role = str(transport_role or "").strip().casefold()
    path = str(field_path or "").strip()
    if role not in {"request", "response"} or not path:
        raise ValueError("transport role and field path are required")
    return f"HTTP {role} {path.casefold()}"


def local_payload_binding_symbols(
    edge: Mapping[str, Any],
    *,
    repository_id: str,
    payload_identity: str | None,
) -> tuple[str, ...]:
    """Return exact local symbols explicitly typed as the topology payload.

    Repository Topology already owns source-side transport binding evidence.  The
    interaction-lineage consumer may reuse that exact evidence, but it must not infer
    symbols from naming conventions or source text.
    """
    payload = str(payload_identity or "").strip()
    if not payload:
        return ()
    symbols: list[str] = []
    for half_wire in _half_wires(edge, repository_id):
        for trace in _rows(half_wire.get("resolution_traces")):
            for binding in _rows(trace.get("local_bindings")):
                if str(binding.get("declared_type") or "").strip() != payload:
                    continue
                if str(binding.get("binding_status") or "") != "exact_single_assignment":
                    continue
                symbol = str(binding.get("symbol") or "").strip()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
    return tuple(symbols)
