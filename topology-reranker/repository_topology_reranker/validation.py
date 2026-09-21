from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .contracts import MAX_RANKED_CANDIDATES, RERANK_PACKAGE_FORMAT, RERANK_RESPONSE_FORMAT


class PackageValidationError(ValueError):
    pass


class ResponseValidationError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def validate_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an Inventory-owned rerank package without re-deriving candidates."""

    if not isinstance(package, Mapping):
        raise PackageValidationError("package must be an object")
    if str(package.get("format") or "") != RERANK_PACKAGE_FORMAT:
        raise PackageValidationError("unsupported rerank package format")
    package_hash = str(package.get("package_hash") or "")
    if len(package_hash) != 64:
        raise PackageValidationError("package_hash must be a sha256 hex digest")

    unhashed = dict(package)
    unhashed.pop("package_hash", None)
    expected_hash = canonical_sha256(unhashed)
    if package_hash != expected_hash:
        raise PackageValidationError("package_hash does not match package content")

    case = package.get("case")
    if not isinstance(case, Mapping) or str(case.get("classification") or "") != "RERANKABLE_RESIDUAL":
        raise PackageValidationError("package case must be RERANKABLE_RESIDUAL")
    case_id = str(case.get("case_id") or "")
    if not case_id:
        raise PackageValidationError("package case_id is required")

    candidates = package.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise PackageValidationError("package candidates must be an array")
    if not 2 <= len(candidates) <= 15:
        raise PackageValidationError("package must contain between 2 and 15 candidates")

    candidate_ids: set[str] = set()
    repository_ids: set[str] = set()
    normalized_candidates: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            raise PackageValidationError("candidate must be an object")
        candidate_id = str(item.get("candidate_id") or "")
        repository_id = str(item.get("repository_id") or "")
        interface_ids = item.get("supporting_interface_ids")
        if not candidate_id or not repository_id:
            raise PackageValidationError("candidate_id and repository_id are required")
        if candidate_id in candidate_ids or repository_id in repository_ids:
            raise PackageValidationError("candidate_id and repository_id must be unique")
        if not isinstance(interface_ids, Sequence) or isinstance(interface_ids, (str, bytes)) or not interface_ids:
            raise PackageValidationError("candidate supporting_interface_ids must be non-empty")
        normalized_ids = [str(value) for value in interface_ids if str(value)]
        if len(normalized_ids) != len(interface_ids) or len(set(normalized_ids)) != len(normalized_ids):
            raise PackageValidationError("candidate supporting_interface_ids must be unique non-empty strings")
        candidate_ids.add(candidate_id)
        repository_ids.add(repository_id)
        normalized_candidates.append(dict(item))

    normalized = dict(package)
    normalized["candidates"] = normalized_candidates
    return normalized


def validate_response(package: Mapping[str, Any], response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate model ranking against the exact supplied candidate/evidence set."""

    package = validate_package(package)
    if not isinstance(response, Mapping):
        raise ResponseValidationError("response must be an object")
    expected_keys = {"format", "package_hash", "case_id", "ranked_candidates"}
    if set(response) != expected_keys:
        raise ResponseValidationError("response contains unsupported or missing top-level fields")
    if str(response.get("format") or "") != RERANK_RESPONSE_FORMAT:
        raise ResponseValidationError("unsupported rerank response format")
    if str(response.get("package_hash") or "") != str(package["package_hash"]):
        raise ResponseValidationError("response package_hash does not match request")
    case_id = str(package["case"]["case_id"])
    if str(response.get("case_id") or "") != case_id:
        raise ResponseValidationError("response case_id does not match request")

    ranked = response.get("ranked_candidates")
    if not isinstance(ranked, Sequence) or isinstance(ranked, (str, bytes)):
        raise ResponseValidationError("ranked_candidates must be an array")
    if not 1 <= len(ranked) <= min(MAX_RANKED_CANDIDATES, len(package["candidates"])):
        raise ResponseValidationError("ranked_candidates length is outside allowed top-k")

    candidates = {str(item["candidate_id"]): item for item in package["candidates"]}
    seen_candidate_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    expected_ranks = list(range(1, len(ranked) + 1))
    actual_ranks: list[int] = []

    for item in ranked:
        if not isinstance(item, Mapping):
            raise ResponseValidationError("ranked candidate must be an object")
        expected_item_keys = {"candidate_id", "target_repository", "rank", "supporting_interface_ids", "explanation"}
        if set(item) != expected_item_keys:
            raise ResponseValidationError("ranked candidate contains unsupported or missing fields")
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise ResponseValidationError("ranked candidate is not in supplied candidate set")
        if candidate_id in seen_candidate_ids:
            raise ResponseValidationError("ranked candidate IDs must be unique")
        seen_candidate_ids.add(candidate_id)

        target_repository = str(item.get("target_repository") or "")
        if target_repository != str(candidate["repository_id"]):
            raise ResponseValidationError("target_repository does not match supplied candidate")

        rank = item.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ResponseValidationError("rank must be an integer")
        actual_ranks.append(rank)

        evidence_ids = item.get("supporting_interface_ids")
        if not isinstance(evidence_ids, Sequence) or isinstance(evidence_ids, (str, bytes)) or not evidence_ids:
            raise ResponseValidationError("supporting_interface_ids must be a non-empty array")
        normalized_evidence = [str(value) for value in evidence_ids if str(value)]
        if len(normalized_evidence) != len(evidence_ids):
            raise ResponseValidationError("supporting_interface_ids must contain non-empty strings")
        allowed = {str(value) for value in candidate.get("supporting_interface_ids") or []}
        if not set(normalized_evidence).issubset(allowed):
            raise ResponseValidationError("supporting_interface_ids cross candidate evidence boundary")

        explanation = item.get("explanation")
        if not isinstance(explanation, str):
            raise ResponseValidationError("explanation must be a string")

        normalized.append(
            {
                "candidate_id": candidate_id,
                "target_repository": target_repository,
                "rank": rank,
                "supporting_interface_ids": normalized_evidence,
                "explanation": explanation,
            }
        )

    if actual_ranks != expected_ranks:
        raise ResponseValidationError("ranks must be unique, ordered, and contiguous from 1")
    return normalized
