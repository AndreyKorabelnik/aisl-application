from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .aisl import AislReadinessGateway
from .checker import check_interaction_lineage
from .contracts import AislBinding, BINDINGS_SCHEMA_VERSION, BindingIndex
from .topology import boundary_fields, select_edge

PREPARATION_FORMAT = "interaction-lineage-preparation/v1"
_PROFILE_ID = "interaction-lineage-attribute-lineage-v1"
_REQUIRED_CAPABILITY = "workspace.attribute-path-resolver"


def _repo_ids(edge: Mapping[str, Any], roles: Sequence[str]) -> list[str]:
    values: set[str] = set()
    for role in roles:
        for field in boundary_fields(edge, transport_role=role):
            values.add(field.source_repository_id)
            values.add(field.target_repository_id)
    return sorted(values)


class PreparationGateway(Protocol):
    def run_preparation(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class KnowledgeControlPlaneGateway:
    """Thin caller of the public generic Framework preparation lifecycle."""

    def __init__(self, base_url: str, *, timeout_sec: float = 3600.0) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        if not self.base_url:
            raise ValueError("KCP base URL must not be empty")
        self.timeout_sec = float(timeout_sec)

    def run_preparation(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + "/api/v1/preparations/run",
            data=body,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            error = RuntimeError(
                f"KCP POST /api/v1/preparations/run failed: HTTP {exc.code}: {detail[:1000]}"
            )
            setattr(error, "status_code", exc.code)
            raise error from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(
                "KCP POST /api/v1/preparations/run unavailable: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, Mapping):
            raise RuntimeError("KCP preparation returned non-object JSON")
        if str(value.get("schema_version") or "") != "framework_preparation_result/v1":
            raise RuntimeError("KCP preparation returned unsupported schema_version")
        return dict(value)


def _bindings_payload(bindings: BindingIndex, repository_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": BINDINGS_SCHEMA_VERSION,
        "repositories": [bindings.require(repository_id).to_dict() for repository_id in sorted(repository_ids)],
    }


def _pinned_context(bindings: BindingIndex, repository_ids: Sequence[str]) -> dict[str, str]:
    return {
        repository_id: binding.revision_id
        for repository_id in sorted(repository_ids)
        if (binding := bindings.find(repository_id)) is not None
    }


def _group_requirements(requirements: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for item in requirements:
        state = str(item.get("state") or "")
        if state != "needs_external_source":
            key = "state:" + state + ":" + json.dumps(dict(item), sort_keys=True, default=str)
        else:
            group = item.get("preparation_group")
            key = "external:" + json.dumps(dict(group) if isinstance(group, Mapping) else dict(item), sort_keys=True, default=str)
        groups.setdefault(key, []).append(item)
    return [groups[key] for key in sorted(groups)]


def _binding_updates(result: Mapping[str, Any]) -> dict[str, AislBinding]:
    final = result.get("final_readiness")
    if not isinstance(final, Mapping):
        return {}
    updates: dict[str, AislBinding] = {}
    for ref in final.get("knowledge_refs") or ():
        if not isinstance(ref, Mapping):
            continue
        repository_id = str(ref.get("repository_id") or "").strip()
        system_id = str(ref.get("system_id") or "").strip()
        revision_id = str(ref.get("revision_id") or "").strip()
        if not repository_id or not system_id or not revision_id:
            continue
        if revision_id.casefold() in {"active", "latest"}:
            raise RuntimeError("Framework preparation returned a non-immutable revision binding")
        selected_repo_ids = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in ref.get("selected_repo_ids") or ()
                if str(value).strip()
            )
        )
        updates[repository_id] = AislBinding(
            repository_id, system_id, revision_id, selected_repo_ids
        )
    return updates


def prepare_interaction_lineage(
    topology: Mapping[str, Any],
    *,
    edge_id: str,
    bindings: BindingIndex,
    readiness_gateway: AislReadinessGateway,
    preparation_gateway: PreparationGateway,
    transport_roles: Sequence[str] = ("request", "response"),
) -> dict[str, Any]:
    edge = select_edge(topology, edge_id)
    repository_ids = _repo_ids(edge, transport_roles)
    before = check_interaction_lineage(
        topology, edge_id=edge_id, bindings=bindings, gateway=readiness_gateway,
        transport_roles=transport_roles,
    )
    if before.get("status") == "ready":
        return {
            "format": PREPARATION_FORMAT,
            "status": "already_prepared",
            "topology_id": str(topology.get("topology_id") or ""),
            "edge_id": edge_id,
            "framework_preparations": [],
            "bindings": _bindings_payload(bindings, repository_ids),
            "readiness_before": before,
            "readiness_after": before,
            "summary": {"framework_invocation_count": 0, "prepared_group_count": 0},
        }

    requirements = [item for item in before.get("preparation_requirements") or () if isinstance(item, Mapping)]
    preparable_repository_statuses = {
        "missing_binding",
        "missing_compatible_revision",
        "missing_required_capability",
    }
    for row in before.get("repositories") or ():
        if not isinstance(row, Mapping) or str(row.get("status") or "") not in preparable_repository_statuses:
            continue
        repository_id = str(row.get("repository_id") or "").strip()
        if not repository_id:
            continue
        existing = bindings.find(repository_id)
        system_id = existing.system_id if existing is not None else repository_id
        requirements.append({
            "state": "needs_repository_preparation",
            "repository_id": repository_id,
            "system_id": system_id,
            "revision_id": existing.revision_id if existing is not None else None,
            "observed_boundary": {"repository_id": repository_id, "system_id": system_id},
            "selector_context": {"repository_id": repository_id, "system_id": system_id},
        })
    ambiguous = [item for item in requirements if str(item.get("state") or "") == "ambiguous"]
    if ambiguous:
        return {
            "format": PREPARATION_FORMAT, "status": "blocked",
            "topology_id": str(topology.get("topology_id") or ""), "edge_id": edge_id,
            "framework_preparations": [],
            "bindings": {"schema_version": BINDINGS_SCHEMA_VERSION, "repositories": [
                binding.to_dict() for repository_id in repository_ids if (binding := bindings.find(repository_id)) is not None
            ]},
            "readiness_before": before, "readiness_after": before,
            "diagnostics": [{"code": "preparation_boundary_ambiguous", "requirements": ambiguous}],
            "summary": {"framework_invocation_count": 0, "prepared_group_count": 0},
        }

    groups = _group_requirements(requirements)
    if not groups:
        return {
            "format": PREPARATION_FORMAT, "status": "blocked",
            "topology_id": str(topology.get("topology_id") or ""), "edge_id": edge_id,
            "framework_preparations": [],
            "bindings": {"schema_version": BINDINGS_SCHEMA_VERSION, "repositories": [
                binding.to_dict() for repository_id in repository_ids if (binding := bindings.find(repository_id)) is not None
            ]},
            "readiness_before": before, "readiness_after": before,
            "diagnostics": [{"code": "generic_preparation_not_eligible", "readiness_status": before.get("status")}],
            "summary": {"framework_invocation_count": 0, "prepared_group_count": 0},
        }

    current: dict[str, AislBinding] = {
        repository_id: binding
        for repository_id in repository_ids
        if (binding := bindings.find(repository_id)) is not None
    }
    framework_results: list[dict[str, Any]] = []
    for group in groups:
        representative = sorted(
            group,
            key=lambda item: (
                str(item.get("transport_role") or ""),
                str(item.get("field_path") or ""),
                str(item.get("side") or ""),
            ),
        )[0]
        repository_id = str(representative.get("repository_id") or "")
        if representative.get("transport_role"):
            journey_id = "interaction-lineage:" + ":".join((
                edge_id,
                str(representative.get("transport_role") or ""),
                str(representative.get("field_path") or ""),
                str(representative.get("side") or ""),
            ))
        else:
            journey_id = f"interaction-lineage:{edge_id}:repository:{repository_id}"
        request = {
            "consumer_id": "interaction-lineage",
            "journey_id": journey_id,
            "required_capabilities": [_REQUIRED_CAPABILITY],
            "analysis_profile_id": _PROFILE_ID,
            "pinned_revision_context": _pinned_context(BindingIndex(list(current.values())), repository_ids),
            "observed_boundary": dict(representative.get("observed_boundary") or {}),
            "selector_context": {
                **dict(representative.get("selector_context") or {}),
                "topology_id": str(topology.get("topology_id") or ""),
                "edge_id": edge_id,
                "preparation_group_field_count": len(group),
            },
        }
        result = dict(preparation_gateway.run_preparation(request))
        framework_results.append({
            "journey_id": journey_id,
            "repository_id": repository_id,
            "field_count": len(group),
            "outcome": result.get("outcome"),
            "initial_readiness": result.get("initial_readiness"),
            "final_readiness": result.get("final_readiness"),
            "steps": result.get("steps") or [],
            "diagnostics": result.get("diagnostics") or [],
        })
        for repo, binding in _binding_updates(result).items():
            current[repo] = binding
        if str(result.get("outcome") or "") in {"blocked", "no_progress", "step_limit"}:
            break

    if any(repository_id not in current for repository_id in repository_ids):
        after = before
    else:
        final_bindings = BindingIndex([current[repository_id] for repository_id in repository_ids])
        after = check_interaction_lineage(
            topology, edge_id=edge_id, bindings=final_bindings, gateway=readiness_gateway,
            transport_roles=transport_roles,
        )
    success = after.get("status") == "ready"
    final_bindings_payload = {
        "schema_version": BINDINGS_SCHEMA_VERSION,
        "repositories": [current[key].to_dict() for key in sorted(current) if key in repository_ids],
    }
    outcomes = [str(item.get("outcome") or "") for item in framework_results]
    if success:
        status = "prepared"
    elif "no_progress" in outcomes:
        status = "no_progress"
    elif "step_limit" in outcomes:
        status = "step_limit"
    else:
        status = "blocked"
    return {
        "format": PREPARATION_FORMAT,
        "status": status,
        "topology_id": str(topology.get("topology_id") or ""),
        "edge_id": edge_id,
        "framework_preparations": framework_results,
        "bindings": final_bindings_payload,
        "readiness_before": before,
        "readiness_after": after,
        "summary": {
            "framework_invocation_count": len(framework_results),
            "prepared_group_count": sum(
                1 for item in framework_results
                if item.get("outcome") in {"prepared", "resolved_terminal", "already_prepared"}
            ),
        },
    }
