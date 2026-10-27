from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

TOPOLOGY_FORMAT = "repository-topology/v5"


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
    """Candidate field probes based on Inventory observations, never proven crossings.

    Topology v5 has no attribute_flows by design.  A field observed on either
    interface side may be a useful AISL query seed, but its presence is NOT
    evidence that the remote repository reads or transfers the same field.
    """
    role = str(transport_role or "").strip().casefold()
    if role not in {"request", "response"}:
        raise ValueError("transport_role must be request or response")
    caller = str(edge.get("source_repository_id") or "").strip()
    provider = str(edge.get("target_repository_id") or "").strip()
    if not caller or not provider or caller == provider:
        return []
    source_repo, target_repo = (caller, provider) if role == "request" else (provider, caller)
    paths = sorted(set(_shape_paths(edge, caller, role)) | set(_shape_paths(edge, provider, role)))
    source_payloads = _payload_identities(edge, source_repo, role)
    target_payloads = _payload_identities(edge, target_repo, role)
    return [BoundaryField(
        transport_role=role,
        field_path=path,
        source_repository_id=source_repo,
        target_repository_id=target_repo,
        source_interface_ids=_interfaces(edge, source_repo),
        target_interface_ids=_interfaces(edge, target_repo),
        source_payload_identity=source_payloads[0] if len(source_payloads) == 1 else None,
        target_payload_identity=target_payloads[0] if len(target_payloads) == 1 else None,
        topology_basis="inventory_observed_candidate_field",
    ) for path in paths]


def wire_display_ref(transport_role: str, field_path: str) -> str:
    role = str(transport_role or "").strip().casefold()
    path = str(field_path or "").strip()
    if role not in {"request", "response"} or not path:
        raise ValueError("transport role and field path are required")
    return f"HTTP {role} {path.casefold()}"


def route_boundary_ref(edge: Mapping[str, Any], transport_role: str, field_path: str) -> str | None:
    """Return an exact REST boundary occurrence reference when topology proves the route.

    This is a deterministic identity bridge only: it reuses the exact topology route and
    field path and never infers names, payloads, or repository-local symbols.
    """
    protocol = str(edge.get("protocol") or "").strip().casefold()
    role = str(transport_role or "").strip().casefold()
    path = str(field_path or "").strip()
    endpoint = str(edge.get("matched_identity") or "").strip()
    if protocol != "http" or role not in {"request", "response"} or not path or not endpoint:
        return None
    # v5 matched_identity may be a payload type-pair identity, not a URL route.
    # Only a route-backed match can be turned into a REST boundary reference.
    basis = edge.get("basis")
    if not isinstance(basis, list) or not any(
        isinstance(entry, Mapping) and entry.get("kind") == "http_method_path"
        and entry.get("value") == f"{str(edge.get('method') or '').strip().upper()} {endpoint}"
        for entry in basis
    ):
        return None
    if not endpoint.startswith("/"):
        return None
    return f"boundary:rest:{endpoint}:{role}.{path}"


def expected_interface_direction(edge: Mapping[str, Any], repository_id: str) -> str | None:
    """Return the exact topology interface direction for one edge repository."""
    repo = str(repository_id or "").strip()
    source = str(edge.get("source_repository_id") or "").strip()
    target = str(edge.get("target_repository_id") or "").strip()
    if repo and repo == source and repo != target:
        return "outbound"
    if repo and repo == target and repo != source:
        return "inbound"
    return None


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
