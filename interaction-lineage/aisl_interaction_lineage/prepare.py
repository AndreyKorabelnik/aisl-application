from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .aisl import AislReadinessGateway
from .checker import check_interaction_lineage
from .contracts import AislBinding, BINDINGS_SCHEMA_VERSION, BindingIndex
from .topology import boundary_fields, select_edge

PREPARATION_FORMAT = "interaction-lineage-preparation/v1"
_PRODUCT_ID = "attribute-lineage"



@dataclass
class PreparationBudget:
    """One command-scoped ceiling across all selected edges; KCP enforces max_steps."""

    max_preparations: int = 1
    max_steps_per_preparation: int = 1
    used: int = 0

    def __post_init__(self) -> None:
        if self.max_preparations < 0:
            raise ValueError("max_preparations cannot be negative")
        if not 1 <= self.max_steps_per_preparation <= 32:
            raise ValueError("max_steps_per_preparation must be in [1, 32]")

    def reserve(self) -> bool:
        if self.used >= self.max_preparations:
            return False
        self.used += 1  # Fail closed even on transport timeout/exception.
        return True


ProgressSink = Callable[[Mapping[str, Any]], None]
RepositoryEnsure = Callable[[str], Mapping[str, Any]]
PublishedLookup = Callable[[str, Mapping[str, Any]], AislBinding | None]


class PublicationGateway(Protocol):
    def publish(self, *, repository_id: str, result: Mapping[str, Any],
                expected_commit: str = "") -> AislBinding: ...

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



def _semantic_group_key(group: Sequence[Mapping[str, Any]]) -> str:
    """A stable attempt identity independent of newly published revision IDs.

    An externally observed *different* boundary is new work, while an unchanged
    field/boundary is not resubmitted just because its pinned revision changed.
    """
    item = sorted(group, key=lambda row: (
        str(row.get("transport_role") or ""),
        str(row.get("field_path") or ""),
        str(row.get("side") or ""),
    ))[0]
    context = item.get("selector_context")
    context = context if isinstance(context, Mapping) else {}
    selector = context.get("attribute_path")
    selector = selector if isinstance(selector, Mapping) else {}
    observed = item.get("observed_boundary")
    observed = observed if isinstance(observed, Mapping) else {}
    basis = item.get("preparation_group")
    basis = basis if isinstance(basis, Mapping) else observed
    return json.dumps({
        "state": str(item.get("state") or ""),
        "repository_id": str(item.get("repository_id") or ""),
        "boundary": dict(basis),
        "observed": dict(observed),
        "declared_external_type_evidence": sorted({
            str(row.get("parent_declared_type") or "")
            for row in item.get("evidence") or () if isinstance(row, Mapping)
            and str(row.get("parent_declared_type") or "")
        }),
        "selector_source": str(selector.get("source") or ""),
        "field": str(item.get("field_path") or "") if not item.get("preparation_group") else "",
        "side": str(item.get("side") or "") if not item.get("preparation_group") else "",
    }, sort_keys=True, default=str)


def _collect_readiness_requirements(
    readiness: Mapping[str, Any], bindings: BindingIndex,
) -> list[dict[str, Any]]:
    requirements = [dict(item) for item in readiness.get("preparation_requirements") or ()
                    if isinstance(item, Mapping)]
    for row in readiness.get("repositories") or ():
        if not isinstance(row, Mapping) or str(row.get("status") or "") not in {
            "missing_binding", "missing_compatible_revision", "missing_required_tool",
        }:
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
    return requirements

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


def _external_origin_observed_boundary(requirement: Mapping[str, Any]) -> dict[str, Any] | None:
    """Turn observed external-origin evidence into a generic Task42 boundary.

    The Application must not guess Maven ownership.  It may, however, pass the
    exact externally-declared type already published in AISL as a bounded Nexus
    discovery anchor.  Framework/Task42 remains the owner of G:A discovery,
    acquisition, analysis and publication.
    """
    if str(requirement.get("state") or "") != "external_source_owner_unresolved":
        return None
    anchors = sorted({
        str(item.get("parent_declared_type") or "").strip()
        for item in requirement.get("evidence") or ()
        if isinstance(item, Mapping) and str(item.get("parent_declared_type") or "").strip()
    })
    if not anchors:
        return None
    terminal_ids = sorted({
        str(item.get("terminal_value_node_id") or "").strip()
        for item in requirement.get("evidence") or ()
        if isinstance(item, Mapping) and str(item.get("terminal_value_node_id") or "").strip()
    })
    boundary: dict[str, Any] = {
        "repository_id": str(requirement.get("repository_id") or "").strip(),
        "system_id": str(requirement.get("system_id") or "").strip(),
        "boundary_kind": "external_type",
        "observed_anchors": anchors,
    }
    if len(terminal_ids) == 1:
        boundary["terminal_value_node_id"] = terminal_ids[0]
    return boundary


def prepare_interaction_lineage(
    topology: Mapping[str, Any],
    *,
    edge_id: str,
    bindings: BindingIndex,
    readiness_gateway: AislReadinessGateway,
    preparation_gateway: PreparationGateway,
    transport_roles: Sequence[str] = ("request", "response"),
    budget: PreparationBudget | None = None,
    progress: ProgressSink | None = None,
    ensure_repository: RepositoryEnsure | None = None,
    publication_gateway: PublicationGateway | None = None,
    published_lookup: PublishedLookup | None = None,
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

    requirements = _collect_readiness_requirements(before, bindings)
    unresolved_external = [
        item for item in requirements
        if str(item.get("state") or "") == "external_source_owner_unresolved"
        and _external_origin_observed_boundary(item) is None
    ]
    if unresolved_external:
        return {
            "format": PREPARATION_FORMAT, "status": "blocked",
            "topology_id": str(topology.get("topology_id") or ""), "edge_id": edge_id,
            "framework_preparations": [],
            "bindings": {"schema_version": BINDINGS_SCHEMA_VERSION, "repositories": [
                binding.to_dict() for repository_id in repository_ids if (binding := bindings.find(repository_id)) is not None
            ]},
            "readiness_before": before, "readiness_after": before,
            "diagnostics": [{
                "code": "external_source_owner_unresolved",
                "message": "material external source origin is observed, but its exact source owner is not mechanically resolved",
                "requirements": unresolved_external,
            }],
            "summary": {"framework_invocation_count": 0, "prepared_group_count": 0},
        }

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
    deferred_groups: list[dict[str, Any]] = []
    attempted: set[str] = set()
    exhausted = False
    stopped = False
    kcp_step_limit_seen = False
    no_new_requirement = False
    rounds = 0
    after: Mapping[str, Any] = before
    pending_groups = groups
    new_boundary_count = 0
    remaining_diagnostics: list[dict[str, Any]] = []
    published_count = 0
    awaiting_count = 0
    while pending_groups:
        rounds += 1
        for group_index, group in enumerate(pending_groups):
            # Reuse an exact previously materialized source before consuming
            # the costly KCP preparation budget.  KCP owns the Git SHA evidence.
            representative_for_reuse = group[0]
            reuse_repository_id = str(representative_for_reuse.get("repository_id") or "")
            reuse_registration = None
            if (reuse_repository_id and reuse_repository_id not in current
                    and ensure_repository is not None and published_lookup is not None):
                reuse_registration = dict(ensure_repository(reuse_repository_id))
                reused = published_lookup(reuse_repository_id, reuse_registration)
                if reused is not None:
                    if reused.repository_id != reuse_repository_id:
                        raise RuntimeError("published lookup returned a mismatched repository")
                    state = readiness_gateway.revision_status(reused)
                    if (state.get("status") != "ready"
                            or "resolve_attribute_path" not in state.get("available_tools", ())):
                        raise RuntimeError("reused revision no longer has required Knowledge Product")
                    current[reuse_repository_id] = reused
                    if progress is not None:
                        progress({"event": "preparation.published_revision_reused",
                                  "edge_id": edge_id, "repository_id": reuse_repository_id,
                                  "system_id": reused.system_id, "revision_id": reused.revision_id})
                    continue
            if budget is not None and not budget.reserve():
                exhausted = True
                deferred_groups = [{
                    "reason": "preparation_budget_exhausted",
                    "requirements": [dict(item) for item in pending],
                } for pending in pending_groups[group_index:]]
                if progress is not None:
                    progress({"event": "preparation.budget_exhausted", "edge_id": edge_id,
                              "deferred_group_count": len(deferred_groups)})
                break
            attempted.add(_semantic_group_key(group))
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
            external_origin_boundary = _external_origin_observed_boundary(representative)
            selector_context = {
                **dict(representative.get("selector_context") or {}),
                "topology_id": str(topology.get("topology_id") or ""),
                "edge_id": edge_id,
                "preparation_group_field_count": len(group),
            }
            if external_origin_boundary is not None:
                # The attribute-path selector led us to this already-observed external
                # type, but KCP must now own external-source discovery.  Leaving the
                # selector in place would make KCP re-evaluate the same local terminal
                # and never enter its Task42 Nexus routing branch.
                selector_context.setdefault("repository_id", repository_id)
                selector_context.setdefault("system_id", str(representative.get("system_id") or ""))
                selector_context.pop("attribute_path", None)
            registration = reuse_registration
            if registration is None and ensure_repository is not None and repository_id:
                registration = dict(ensure_repository(repository_id))
                if progress is not None:
                    progress({"event": "repository.registration_checked", "edge_id": edge_id,
                              "repository_id": repository_id, **registration})
            request = {
                "consumer_id": "interaction-lineage",
                "journey_id": journey_id,
                "product_ids": [_PRODUCT_ID],
                "execution_scope": "workspace",
                "pinned_revision_context": _pinned_context(BindingIndex(list(current.values())), repository_ids),
                "observed_boundary": (
                    external_origin_boundary
                    if external_origin_boundary is not None
                    else dict(representative.get("observed_boundary") or {})
                ),
                "selector_context": selector_context,
            }
            if budget is not None:
                request["max_steps"] = budget.max_steps_per_preparation
            started = time.monotonic()
            if progress is not None:
                progress({"event": "preparation.started", "edge_id": edge_id,
                          "repository_id": repository_id, "group_index": group_index + 1,
                          "group_count": len(pending_groups), "product_ids": [_PRODUCT_ID],
                          "max_steps": request.get("max_steps", 8)})
            try:
                result = dict(preparation_gateway.run_preparation(request))
            except Exception as exc:
                if progress is not None:
                    progress({"event": "preparation.failed", "edge_id": edge_id,
                              "repository_id": repository_id, "elapsed_seconds": round(time.monotonic() - started, 3),
                              "exception_type": type(exc).__name__})
                raise
            # Registration tracks a Git ref, not the Inventory snapshot itself.
            # A published Framework step must report exactly the observed commit.
            if registration is not None:
                expected_commit = str(registration.get("inventory_resolved_commit") or "").lower()
                for step in result.get("steps") or ():
                    if not isinstance(step, Mapping) or step.get("status") != "published":
                        continue
                    refs = [ref for ref in step.get("source_provenance_refs") or ()
                            if isinstance(ref, Mapping) and ref.get("source_kind") == "repository"
                            and ref.get("repository_id") == repository_id]
                    actual_commit = str(refs[0].get("revision") or "").lower() if len(refs) == 1 else ""
                    if not re.fullmatch(r"[0-9a-f]{40}", actual_commit):
                        raise RuntimeError(f"KCP prepared source revision does not match required exact Git commit: {repository_id}")
                    if expected_commit and actual_commit != expected_commit:
                        raise RuntimeError(f"KCP prepared source revision does not match Inventory resolved commit: {repository_id}")
                    # No Topology commit means fresh publication is pinned but NOT
                    # evidence of source parity with the historical Inventory snapshot.
            elapsed = round(time.monotonic() - started, 3)
            if progress is not None:
                source_ids = sorted({
                    str(source_id) for step in result.get("steps") or () if isinstance(step, Mapping)
                    for source in step.get("source_provenance_refs") or () if isinstance(source, Mapping)
                    for source_id in source.get("selected_source_ids") or () if str(source_id)
                })
                progress({"event": "preparation.completed", "edge_id": edge_id,
                          "repository_id": repository_id, "outcome": result.get("outcome"),
                          "elapsed_seconds": elapsed,
                          "job_ids": [str(step.get("step_id")) for step in result.get("steps") or ()
                                      if isinstance(step, Mapping) and step.get("step_id")],
                          "selected_source_ids": source_ids})
            framework_results.append({
                "journey_id": journey_id,
                "repository_id": repository_id,
                "field_count": len(group),
                "round": rounds,
                "requested_boundary": dict(request["observed_boundary"]),
                "requirement_states": sorted({str(row.get("state") or "") for row in group}),
                "elapsed_seconds": elapsed,
                "outcome": result.get("outcome"),
                "initial_readiness": result.get("initial_readiness"),
                "final_readiness": result.get("final_readiness"),
                "steps": result.get("steps") or [],
                "diagnostics": result.get("diagnostics") or [],
            })
            if str(result.get("outcome") or "") == "awaiting_publication":
                if publication_gateway is None:
                    awaiting_count += 1
                    remaining_diagnostics.append({"code": "publication_gateway_unavailable",
                        "repository_id": repository_id,
                        "message": "KCP bundles await an explicit Server publication"})
                    stopped = True
                    deferred_groups = [{"reason": "awaiting_publication",
                        "requirements": [dict(item) for item in pending]}
                        for pending in pending_groups[group_index + 1:]]
                    break
                if progress is not None:
                    progress({"event": "publication.started", "edge_id": edge_id,
                              "repository_id": repository_id})
                try:
                    bound = publication_gateway.publish(
                        repository_id=repository_id, result=result,
                        expected_commit=str((registration or {}).get("inventory_resolved_commit") or ""),
                    )
                    if not isinstance(bound, AislBinding) or bound.repository_id != repository_id:
                        raise RuntimeError("publication gateway returned invalid repository binding")
                    # A server-issued revision is not sufficient: the public
                    # revision-tools read gate must confirm required knowledge.
                    published_state = readiness_gateway.revision_status(bound)
                    if (str(published_state.get("status") or "") != "ready"
                            or "resolve_attribute_path" not in published_state.get("available_tools", ())):
                        raise RuntimeError("published revision lacks pinned resolve_attribute_path tool")
                    current[repository_id] = bound
                    published_count += 1
                    if progress is not None:
                        progress({"event": "publication.completed", "edge_id": edge_id,
                                  "repository_id": repository_id, "system_id": bound.system_id,
                                  "revision_id": bound.revision_id})
                except Exception as exc:
                    awaiting_count += 1
                    stopped = True
                    remaining_diagnostics.append({"code": "publication_failed",
                        "repository_id": repository_id, "exception_type": type(exc).__name__,
                        "message": str(exc)})
                    if progress is not None:
                        progress({"event": "publication.failed", "edge_id": edge_id,
                                  "repository_id": repository_id, "exception_type": type(exc).__name__})
                    deferred_groups = [{"reason": "publication_failed",
                        "requirements": [dict(item) for item in pending]}
                        for pending in pending_groups[group_index + 1:]]
                    break
            for repo, binding in _binding_updates(result).items():
                current[repo] = binding
            if str(result.get("outcome") or "") == "step_limit":
                # A fresh public AISL check may reveal a *different* observed
                # dependency after partial KCP publication. Never repeat the
                # same boundary merely to bypass the KCP step limit.
                kcp_step_limit_seen = True
            if str(result.get("outcome") or "") in {"blocked", "no_progress"}:
                deferred_groups = [{
                    "reason": "previous_preparation_stopped",
                    "requirements": [dict(item) for item in pending],
                } for pending in pending_groups[group_index + 1:]]
                stopped = True
                break


        # A completed wave is followed by a fresh public AISL read. Any newly
        # observed external source is admitted only through the same checker.
        if not exhausted and all(repository_id in current for repository_id in repository_ids):
            final_bindings = BindingIndex([current[key] for key in repository_ids])
            after = check_interaction_lineage(
                topology, edge_id=edge_id, bindings=final_bindings, gateway=readiness_gateway,
                transport_roles=transport_roles,
            )
        if after.get("status") == "ready" or exhausted or stopped:
            break
        # No additional execution without an actually new, mechanically observed
        # requirement; never resubmit an unchanged boundary on a new revision.
        active_bindings = BindingIndex(list(current.values()))
        newly_reported = _collect_readiness_requirements(after, active_bindings)
        blockers = [dict(item) for item in newly_reported if (
            (str(item.get("state") or "") == "external_source_owner_unresolved"
             and _external_origin_observed_boundary(item) is None)
            or str(item.get("state") or "") == "ambiguous"
        )]
        if blockers:
            stopped = True
            remaining_diagnostics.append({
                "code": "preparation_boundary_unresolved_after_analysis",
                "requirements": blockers,
            })
            break
        fresh_groups = [group for group in _group_requirements(newly_reported)
                        if _semantic_group_key(group) not in attempted]
        if progress is not None:
            progress({"event": "preparation.readiness_rechecked", "edge_id": edge_id,
                      "round": rounds, "status": after.get("status"),
                      "remaining_requirement_count": len(newly_reported),
                      "new_group_count": len(fresh_groups)})
        if not fresh_groups:
            no_new_requirement = True
            remaining_diagnostics.append({
                "code": "preparation_no_new_supported_boundary",
                "message": "No new mechanically observed preparation group after publication",
                "remaining_requirements": newly_reported,
            })
            break
        new_boundary_count += len(fresh_groups)
        pending_groups = fresh_groups
    success = after.get("status") == "ready"
    final_bindings_payload = {
        "schema_version": BINDINGS_SCHEMA_VERSION,
        "repositories": [current[key].to_dict() for key in sorted(current) if key in repository_ids],
    }
    outcomes = [str(item.get("outcome") or "") for item in framework_results]
    if success:
        status = "prepared"
    elif exhausted:
        status = "budget_exhausted"
    elif awaiting_count:
        status = "awaiting_publication"
    elif "no_progress" in outcomes:
        status = "no_progress"
    elif kcp_step_limit_seen:
        status = "step_limit"
    elif no_new_requirement:
        status = "no_progress"
    else:
        status = "blocked"
    if progress is not None:
        progress({"event": "preparation.finished", "edge_id": edge_id,
                  "status": status, "framework_invocation_count": len(framework_results),
                  "deferred_group_count": len(deferred_groups),
                  "new_requirement_group_count": new_boundary_count})
    return {
        "format": PREPARATION_FORMAT,
        "status": status,
        "topology_id": str(topology.get("topology_id") or ""),
        "edge_id": edge_id,
        "framework_preparations": framework_results,
        "deferred_groups": deferred_groups,
        "diagnostics": remaining_diagnostics,
        "bindings": final_bindings_payload,
        "published_dependency_revisions": [current[key].to_dict() for key in sorted(current)
                                           if key not in repository_ids],
        "readiness_before": before,
        "readiness_after": after,
        "summary": {
            "framework_invocation_count": len(framework_results),
            "published_revision_count": published_count,
            "awaiting_publication_count": awaiting_count,
            "readiness_recheck_round_count": rounds,
            "new_requirement_group_count": new_boundary_count,
            "deferred_group_count": len(deferred_groups),
            "prepared_group_count": sum(
                1 for item in framework_results
                if item.get("outcome") in {"prepared", "resolved_terminal", "already_prepared"}
            ),
        },
    }
