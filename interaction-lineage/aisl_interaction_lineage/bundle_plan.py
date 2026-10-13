"""Read-only, exact-source plan for manually prepared AISL publication bundles.

Inventory/Topology own repository discovery. KCP owns production of a bundle.
This module owns only a consumer-side plan and an executable handoff script;
no Git, KCP, Nexus or publishing subprocess is invoked here.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .contracts import BindingIndex, BINDINGS_SCHEMA_VERSION
from .topology import validate_topology

PROFILE = "attribute-lineage-v1"
CAPABILITY = "workspace.attribute-path-resolver"
SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _repo_sources(topology: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    validate_topology(topology)
    records: dict[str, dict[str, str]] = {}
    for row in topology.get("repositories") or []:
        if not isinstance(row, Mapping):
            raise ValueError("topology.repositories requires objects")
        rid = str(row.get("repository_id") or "").strip()
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", rid)
                or rid in records):
            raise ValueError(f"invalid/duplicate topology repository_id: {rid!r}")
        url = str(row.get("repository_url") or "").strip()
        sha = str(row.get("resolved_commit") or "").lower().strip()
        if url:
            if any(ord(ch) < 33 for ch in url):
                raise ValueError(f"unsafe topology repository_url for {rid}")
            parsed = urlsplit(url)
            if (parsed.scheme not in {"https", "http", "ssh"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError(f"unsafe topology repository_url for {rid}")
        if sha and not SHA.fullmatch(sha):
            raise ValueError(f"invalid topology resolved_commit for {rid}")
        records[rid] = {"repository_id": rid, "repository_url": url, "resolved_commit": sha}
    edge_repos = {
        str(edge.get(key) or "").strip()
        for edge in topology.get("edges") or [] if isinstance(edge, Mapping)
        for key in ("source_repository_id", "target_repository_id")
    }
    edge_repos.discard("")
    for rid in sorted(edge_repos):
        records.setdefault(rid, {"repository_id": rid, "repository_url": "", "resolved_commit": ""})
    return {rid: records[rid] for rid in sorted(edge_repos)}


def _matching_revision(revision: Mapping[str, Any], source: Mapping[str, str]) -> bool:
    """Match only immutable producer snapshots, not a coincidental system name."""
    metadata = revision.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    for entry in metadata.get("source_snapshots") or []:
        if not isinstance(entry, Mapping) or entry.get("source_kind") != "git":
            continue
        rv = entry.get("resolved_version") or {}
        if not isinstance(rv, Mapping):
            continue
        if (entry.get("location") == source.get("repository_url")
                and str(rv.get("commit_sha") or "").lower() == source.get("resolved_commit")):
            return True
    return False


def _published_candidates(client: Any, sources: Mapping[str, Mapping[str, str]]) -> dict[str, list[dict[str, str]]]:
    candidates: dict[str, list[dict[str, str]]] = {rid: [] for rid in sources}
    eligible = {rid: source for rid, source in sources.items() if source.get("repository_url") and source.get("resolved_commit")}
    if not eligible:
        return candidates
    # Reuse public AISL catalog and its standard paging/limits, never invent a registry.
    for system in client.list_systems():
        for revision in client.list_revisions(system.system_id):
            raw = revision.raw
            for rid, source in eligible.items():
                if _matching_revision(raw, source) and CAPABILITY in revision.capabilities:
                    candidates[rid].append({"repository_id": rid, "system_id": system.system_id,
                                            "revision_id": revision.revision_id})
    return candidates


def plan_missing_bundles(
    topology: Mapping[str, Any], *, client: Any, bindings: BindingIndex | None = None,
) -> dict[str, Any]:
    sources = _repo_sources(topology)
    published = _published_candidates(client, sources)
    explicit = bindings or BindingIndex([])
    result: list[dict[str, Any]] = []
    for rid, source in sources.items():
        matching = published[rid]
        bound = explicit.find(rid)
        if bound is not None:
            matching = [row for row in matching
                        if row["system_id"] == bound.system_id and row["revision_id"] == bound.revision_id]
        if len(matching) == 1:
            status = "ready"
            reason = "published_exact_source_revision_and_capability"
        elif len(matching) > 1:
            status = "ambiguous"
            reason = "multiple_published_exact_source_revisions"
        elif not source["repository_url"] or not source["resolved_commit"]:
            status = "source_identity_missing"
            reason = "topology_missing_repository_url_or_exact_commit"
        else:
            status = "requires_bundle"
            reason = "no_compatible_published_revision_confirmed"
        result.append({**source, "status": status, "reason": reason,
                       "profile": PROFILE, "published_matches": matching})
    ready = [row["published_matches"][0] for row in result if row["status"] == "ready"]
    pending = [row for row in result if row["status"] != "ready"]
    return {
        "format": "interaction-lineage-manual-bundle-plan/v1",
        "topology_id": topology.get("topology_id"),
        "status": "ready" if not pending else "needs_manual_bundles",
        "repositories": result,
        "summary": {
            "repository_count": len(result),
            "ready_count": len(ready),
            "requires_bundle_count": sum(row["status"] == "requires_bundle" for row in result),
            "unresolved_count": sum(row["status"] in {"source_identity_missing", "ambiguous"} for row in result),
        },
        "resolved_bindings": {"schema_version": BINDINGS_SCHEMA_VERSION, "repositories": ready},
    }


def render_preparation_script(plan: Mapping[str, Any]) -> str:
    """Create KCP bundle production commands; no transfer, copying or publication."""
    lines = [
        "#!/usr/bin/env bash", "set -euo pipefail", "",
        '# Generated from immutable Topology source metadata; run where Git and KCP CLI are available.',
        '# Only prepares publication bundles. Copying and server import are MANUAL.',
        'mkdir -p work bundles', '',
    ]
    jobs = 0
    for row in plan.get("repositories") or []:
        state = row["status"]
        rid = row["repository_id"]
        if state == "ready":
            continue
        if state != "requires_bundle":
            lines.append(f'# {rid}: BLOCKED ({state}): {row["reason"]}; no guessed source or revision.')
            continue
        url, sha = row["repository_url"], row["resolved_commit"]
        # File paths derived from sequence, not unsanitized repository ID.
        key = f"repo-{jobs + 1:04d}"
        jobs += 1
        quote = shlex.quote
        lines += [
            f'# {rid} @ {sha}; profile {PROFILE}',
            f'if test -d {quote(f"work/{key}/.git")}; then',
            f'  test "$(git -C {quote(f"work/{key}")} remote get-url origin)" = {quote(url)}',
            'else',
            f'  git clone --no-checkout {quote(url)} {quote(f"work/{key}")}',
            'fi',
            f'git -C {quote(f"work/{key}")} cat-file -e {quote(sha + "^{commit}")} 2>/dev/null || git -C {quote(f"work/{key}")} fetch origin {quote(sha)}',
            f'git -C {quote(f"work/{key}")} checkout --detach {quote(sha)}',
            f'test "$(git -C {quote(f"work/{key}")} rev-parse HEAD)" = {quote(sha)}',
            f'knowledge-control-plane run --knowledge-profile {quote(PROFILE)} '
            f'--repository {quote(f"work/{key}")} --system-id {quote(rid)} '
            f'--output {quote(f"bundles/{key}-work")} --json > {quote(f"bundles/{key}-job.json")}',
            f'echo {quote(f"{rid}: preparation completed; see bundles/{key}-job.json for publication_bundle.path")}',
            '',
        ]
    if not jobs:
        lines.append('echo "No mechanically executable bundle preparation tasks."')
    lines.append('# Manual next step: locate each publication_bundle.path in job JSON, transfer and import on AISL Server.')
    return "\n".join(lines) + "\n"


def write_bundle_plan(plan: Mapping[str, Any], directory: str | Path) -> None:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "missing-revisions.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "resolved-bindings.json").write_text(json.dumps(plan["resolved_bindings"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = root / "prepare-missing-bundles.sh"
    path.write_text(render_preparation_script(plan), encoding="utf-8")
    path.chmod(0o755)
