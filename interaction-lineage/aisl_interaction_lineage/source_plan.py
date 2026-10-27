"""Read-only, bounded preparation preview over already published Topology facts.

No repository discovery, KCP registration, source acquisition, build or Nexus lookup.
Only explicitly requested public AISL/KCP metadata reads are allowed.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .bundle_plan import PRODUCT_ID, _repo_sources, plan_missing_bundles
from .contracts import BindingIndex
from .repository_sources import KcpRepositoryRegistrar, _safe_git_url
from .topology import select_edge, validate_topology


def plan_interaction_sources(
    topology: Mapping[str, Any], *, edge_ids: Sequence[str],
    bindings: BindingIndex | None = None,
    aisl_client: Any | None = None,
    kcp_base_url: str | None = None,
) -> dict[str, Any]:
    """Preview selected source preparation. Unknown facts remain explicit unknowns."""
    validate_topology(topology)
    if not edge_ids or len(set(edge_ids)) != len(edge_ids):
        raise ValueError("selected edges must have unique nonempty IDs")
    selected_edges = [select_edge(topology, edge_id) for edge_id in edge_ids]
    # Retain exactly the requested edges in the existing source/coverage planner.
    selected_ids = {
        str(edge.get(key) or "").strip() for edge in selected_edges
        for key in ("source_repository_id", "target_repository_id")
    }
    scoped_topology = {
        **topology,
        "edges": selected_edges,
        "repositories": [row for row in topology.get("repositories") or ()
                         if isinstance(row, Mapping) and str(row.get("repository_id") or "") in selected_ids],
    }
    sources = _repo_sources(scoped_topology)
    # Do not call the AISL server when not explicitly requested.
    published = (plan_missing_bundles(scoped_topology, client=aisl_client,
                                       bindings=bindings or BindingIndex([]))
                 if aisl_client is not None else None)
    published_by_id = ({row["repository_id"]: row for row in published["repositories"]}
                       if published is not None else {})
    # No KCP API calls when its URL is absent. This client is GET-only below.
    registrar = (KcpRepositoryRegistrar(kcp_base_url, {}) if kcp_base_url else None)
    rows: list[dict[str, Any]] = []
    for rid, source in sources.items():
        url, commit = source["repository_url"], source["resolved_commit"]
        if url and not _safe_git_url(url):
            raise ValueError(f"unsafe topology Git URL for {rid}")
        if url and urlsplit(url).scheme != "https":
            git_url_status = "unsupported_git_scheme"
        elif url:
            git_url_status = "topology_https_url_validated_kcp_authorization_pending"
        else:
            git_url_status = "repository_url_missing"

        published_row = published_by_id.get(rid)
        publication = (published_row["status"] if published_row else "not_checked")
        matches = list(published_row["published_matches"] if published_row else ())
        registry_state = "not_checked"
        kcp_repository_id: str | None = None
        if registrar is not None and url:
            registered = registrar._matches(rid, url)  # GET-only registry pagination, no discover/POST
            if len(registered) == 1 and str(registered[0].get("location") or "") == url:
                registry_state = "registered"
                kcp_repository_id = str(registered[0].get("repository_id") or "") or None
            elif registered:
                registry_state = "ambiguous_or_conflicting"
            else:
                registry_state = "not_registered"

        if publication == "ready":
            action = "reuse_published_exact_revision"
        elif publication == "ambiguous":
            action = "resolve_published_revision_ambiguity"
        elif not url:
            action = "blocked_missing_git_location"
        elif git_url_status == "unsupported_git_scheme":
            action = "blocked_unsupported_git_scheme"
        elif not commit:
            action = "resolve_git_commit_then_check_publication"
        elif published is None:
            action = "check_published_knowledge_before_download"
        else:
            action = "prepare_missing_knowledge"
        rows.append({
            "repository_id": rid,
            "repository_url": url,
            "resolved_commit": commit or None,
            "snapshot_compatibility": "verifiable_by_exact_commit" if commit else "unverified_topology_snapshot",
            "git_url_status": git_url_status,
            "kcp_registry_status": registry_state,
            "kcp_repository_id": kcp_repository_id,
            "published_revision_status": publication,
            "published_matches": matches,
            "next_action": action,
            "download_decision": (
                "not_required_exact_published_knowledge" if publication == "ready"
                else "not_authorized" if action.startswith("blocked_")
                else "conditional_after_readiness_and_commit_resolution"
            ),
            "product_id": PRODUCT_ID,
        })
    pending = sum(row["next_action"] != "reuse_published_exact_revision" for row in rows)
    return {
        "format": "interaction-lineage-source-plan/v1",
        "topology_id": str(topology["topology_id"]),
        "selected_edge_ids": list(edge_ids),
        "operation": "read_only_preview",
        "side_effects": {"git_clones": 0, "nexus_downloads": 0, "kcp_registrations": 0,
                         "aisl_publications": 0},
        "knowledge_checks": {"aisl_catalog_queried": aisl_client is not None,
                             "kcp_registry_queried": registrar is not None},
        "repositories": rows,
        "nexus_artifacts": {
            "confirmed_exact_downloads": [],
            "discovery_status": "pending_bounded_source_or_published_external_evidence",
            "explanation": "Topology v5 does not establish the exact Maven GAV/version/source-digest closure. "
                           "Framework/KCP discovers required artifacts demand-driven from observed dependency evidence; "
                           "no GAV is invented by the consumer.",
        },
        "summary": {"selected_edges": len(edge_ids), "selected_repositories": len(rows),
                    "already_published_exact": len(rows) - pending,
                    "not_confirmed_ready": pending,
                    "registered_in_kcp": sum(row["kcp_registry_status"] == "registered" for row in rows),
                    "unverified_source_snapshots": sum(not row["resolved_commit"] for row in rows)},
    }
