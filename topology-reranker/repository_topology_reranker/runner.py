from __future__ import annotations

import copy
from typing import Any, Mapping

from .adapter import AdapterIdentity, RerankAdapter
from .contracts import NON_CANONICAL_CLASSIFICATION, RERANK_RESPONSE_FORMAT, SEMANTIC_SHORTLIST_FORMAT
from .validation import PackageValidationError, ResponseValidationError, canonical_sha256, validate_package, validate_response


def _base_artifact(package: Mapping[str, Any], identity: AdapterIdentity) -> dict[str, Any]:
    return {
        "format": SEMANTIC_SHORTLIST_FORMAT,
        "classification": NON_CANONICAL_CLASSIFICATION,
        "package_hash": str(package["package_hash"]),
        "case_id": str(package["case"]["case_id"]),
        "deterministic_candidate_order": [str(item["candidate_id"]) for item in package["candidates"]],
        "model_reranked_order": [],
        "ranked_candidates": [],
        "adapter": identity.to_dict(),
        "response_hash": None,
        "status": "",
        "diagnostics": [],
    }


def rerank_package(
    package: Mapping[str, Any],
    *,
    adapter: RerankAdapter,
    identity: AdapterIdentity,
) -> dict[str, Any]:
    """Invoke one external adapter without changing canonical topology semantics.

    Invalid/tampered packages fail before any provider call. Provider or response
    failures are isolated into a non-canonical artifact and never create an edge.
    """

    frozen = validate_package(package)
    artifact = _base_artifact(frozen, identity)
    provider_input = copy.deepcopy(frozen)

    try:
        response = adapter.rerank(provider_input)
    except Exception as exc:  # provider boundary: preserve topology success
        artifact["status"] = "PROVIDER_ERROR"
        artifact["diagnostics"] = [
            {"code": "provider_error", "message": f"{type(exc).__name__}: {exc}"}
        ]
        return artifact

    response_hash = canonical_sha256(response)
    artifact["response_hash"] = response_hash
    try:
        ranked = validate_response(frozen, response)
    except (PackageValidationError, ResponseValidationError) as exc:
        artifact["status"] = "INVALID_RESPONSE"
        artifact["diagnostics"] = [
            {"code": "invalid_response", "message": str(exc)}
        ]
        return artifact

    artifact["status"] = "VALIDATED"
    artifact["ranked_candidates"] = ranked
    artifact["model_reranked_order"] = [item["candidate_id"] for item in ranked]
    return artifact


def ranking_response(
    *,
    package_hash: str,
    case_id: str,
    ranked_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Small helper for provider adapters/tests to emit the exact response contract."""

    return {
        "format": RERANK_RESPONSE_FORMAT,
        "package_hash": package_hash,
        "case_id": case_id,
        "ranked_candidates": ranked_candidates,
    }
