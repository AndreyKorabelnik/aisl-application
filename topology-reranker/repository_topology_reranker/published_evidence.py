"""Non-canonical candidate ordering using only revision-pinned public AISL observations.

This is consumer-side composition. It neither builds topology nor infers a deployed
caller/target link. Java-implementation evidence breaks *equal-score* ties only.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

REQUEST_FORMAT = "repository-topology-published-shortlist-request/v1"
RESULT_FORMAT = "repository-topology-published-shortlist/v1"
JAVA_BASIS = "java_exact_route_annotation"


class PublishedEvidenceError(ValueError):
    """Invalid pinned inputs, missing/unreadable knowledge, or mismatched evidence."""


def _nonempty(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublishedEvidenceError(f"{key} must be a nonempty string")
    return value.strip()


def _validate_request(document: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(document, Mapping) or document.get("format") != REQUEST_FORMAT:
        raise PublishedEvidenceError("unsupported request format")
    case_id = _nonempty(document.get("case_id"), "case_id")
    rows = document.get("candidates")
    if not isinstance(rows, list) or not (1 <= len(rows) <= 100):
        raise PublishedEvidenceError("candidates must contain 1..100 bounded records")
    seen: set[tuple[str, str]] = set()
    cleaned: list[dict[str, Any]] = []
    for idx, c in enumerate(rows):
        if not isinstance(c, Mapping):
            raise PublishedEvidenceError("candidate must be an object")
        required = ("repository_id", "revision_id", "artifact_id", "interface_id", "method", "route")
        item = {k: _nonempty(c.get(k), f"candidates[{idx}].{k}") for k in required}
        if item["revision_id"].lower() in {"latest", "active"}:
            raise PublishedEvidenceError("candidate must use an immutable pinned revision_id")
        item["method"] = item["method"].upper()
        if not item["route"].startswith("/"):
            raise PublishedEvidenceError("route must be an exact HTTP path")
        score = c.get("retrieval_score")
        if type(score) is not int:
            raise PublishedEvidenceError("retrieval_score must be an integer")
        item["retrieval_score"] = score
        for field in ("request_payload", "response_payload"):
            v = c.get(field)
            if v is not None and (not isinstance(v, str) or not v.strip()):
                raise PublishedEvidenceError(field + " must be a nonempty string when supplied")
            item[field] = v.strip() if isinstance(v, str) else None
        identity = (item["repository_id"], item["interface_id"])
        if identity in seen:
            raise PublishedEvidenceError("duplicate repository/interface candidate")
        seen.add(identity)
        cleaned.append(item)
    return case_id, cleaned


def public_http_get_json(*, base_url: str, timeout_seconds: float = 15.0) -> Callable[[str, str, str, str], Mapping[str, Any]]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise PublishedEvidenceError("base_url must be an HTTP(S) Knowledge API origin")
    if timeout_seconds <= 0:
        raise PublishedEvidenceError("timeout_seconds must be positive")
    origin = base_url.rstrip("/")

    def get(repo: str, rev: str, artifact: str, interface_id: str) -> Mapping[str, Any]:
        segments = [quote(x, safe="") for x in (repo, artifact, "interface", interface_id)]
        path = f"/api/knowledge/v1/systems/{segments[0]}/knowledge-items/{'/'.join(segments[1:])}"
        url = origin + path + "?" + urlencode({"revision_id": rev})
        try:
            with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=timeout_seconds) as response:
                body = response.read(4_000_001)
                if len(body) > 4_000_000:
                    raise PublishedEvidenceError("public API response exceeds the bounded size")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise PublishedEvidenceError(f"public API read failed for {repo}/{interface_id}: {exc}") from exc
        try:
            obj = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PublishedEvidenceError("public API returned invalid JSON") from exc
        if not isinstance(obj, Mapping):
            raise PublishedEvidenceError("public API JSON must be an object")
        return obj

    return get


def rank_published_candidates(
    request: Mapping[str, Any],
    *,
    get_knowledge_item: Callable[[str, str, str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Prioritize exact observed Java implementations inside each retrieval-score tie.

    The caller supplies an already admitted candidate set, not repository names to
    discover; no source, Inventory JSON or Gold is consulted. All candidates remain.
    """
    case_id, candidates = _validate_request(request)
    ranked: list[dict[str, Any]] = []
    for c in candidates:
        response = get_knowledge_item(c["repository_id"], c["revision_id"], c["artifact_id"], c["interface_id"])
        if not isinstance(response, Mapping):
            raise PublishedEvidenceError("public API result must be an object")
        item = response.get("item")
        if not isinstance(item, Mapping):
            raise PublishedEvidenceError("public API does not contain an observed interface item")
        if item.get("interface_id") != c["interface_id"]:
            raise PublishedEvidenceError("public evidence interface_id does not match the candidate")
        if item.get("direction") != "inbound" or item.get("protocol") != "http":
            raise PublishedEvidenceError("candidate is not an observed incoming HTTP interface")
        address = item.get("address")
        if not isinstance(address, Mapping) or address.get("status") != "resolved":
            raise PublishedEvidenceError("incoming HTTP interface lacks a resolved route")
        if item.get("method") != c["method"] or address.get("value") != c["route"]:
            raise PublishedEvidenceError("published method/route conflicts with admitted candidate")
        payloads = item.get("payloads")
        if not isinstance(payloads, list):
            raise PublishedEvidenceError("published interface payload descriptors missing")
        for role in ("request", "response"):
            expected = c[f"{role}_payload"]
            if expected is not None and not any(isinstance(p, Mapping) and p.get("role") == role and p.get("identity") == expected for p in payloads):
                raise PublishedEvidenceError("published payload conflicts with admitted candidate")
        provenance = item.get("provenance")
        if not isinstance(provenance, Mapping) or not isinstance(provenance.get("basis_variants"), list):
            raise PublishedEvidenceError("published basis variants are unavailable, cannot rank")
        observed_java = any(isinstance(x, Mapping) and x.get("kind") == JAVA_BASIS for x in provenance["basis_variants"])
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list) or any(not isinstance(e, str) or not e for e in evidence_ids):
            raise PublishedEvidenceError("published interface evidence references unavailable")
        ranked.append({**c, "observed_java_implementation": observed_java,
                       "matched_basis": JAVA_BASIS if observed_java else "published_contract_or_other_basis",
                       "evidence_ids": list(evidence_ids),
                       "published_evidence_revision": c["revision_id"]})
    ranked.sort(key=lambda x: (-x["retrieval_score"], -int(x["observed_java_implementation"]), x["repository_id"], x["interface_id"]))
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
    best = ranked[0]
    comparable = [c for c in ranked if (c["retrieval_score"], c["observed_java_implementation"]) == (best["retrieval_score"], best["observed_java_implementation"])]
    return {
        "format": RESULT_FORMAT,
        "case_id": case_id,
        "classification": "non_canonical_candidate_priority",
        "runtime_target_proven": False,
        "canonical_topology_mutated": False,
        "ranking_basis": "retrieval_score_desc_then_exact_published_java_implementation_evidence_within_score_ties",
        "top_evidence_tie_count": len(comparable),
        "selection_status": "ambiguous_top_evidence" if len(comparable) != 1 else "single_evidence_leader_not_runtime_proof",
        "candidates": ranked,
    }
