from __future__ import annotations

import copy
import hashlib
import json

import pytest

from repository_topology_reranker import (
    AdapterIdentity,
    PackageValidationError,
    ResponseValidationError,
    rerank_package,
    validate_package,
    validate_response,
)
from repository_topology_reranker.runner import ranking_response


def _hash_payload(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _package():
    payload = {
        "format": "repository-topology-rerank-package/v1",
        "topology_id": "topology-x",
        "corpus": {
            "corpus_id": "corpus-x",
            "topology_format": "repository-topology/v4",
            "topology_id": "topology-x",
            "input_count": 3,
        },
        "case": {
            "case_id": "case-x",
            "classification": "RERANKABLE_RESIDUAL",
            "reason": "multiple_mechanically_admissible_candidate_repositories",
        },
        "source": {
            "repository_id": "caller",
            "repository_pin": {"repository_id": "caller", "artifact_id": "a", "semantic_fingerprint": "s", "sha256": "x"},
            "diagnostic_reason": "unresolved",
            "interface_id": "source-iface",
            "interface": {"repository_id": "caller", "interface_id": "source-iface"},
        },
        "retrieval": {
            "policy": "exact_published_http_payload_v1",
            "max_candidates": 15,
            "candidate_repository_count_before_limit": 2,
            "candidate_repository_count": 2,
            "truncated": False,
            "ordering": "retrieval_score_desc_repository_id_asc",
        },
        "candidates": [
            {
                "candidate_id": "candidate-a",
                "repository_id": "provider-a",
                "repository_pin": {"repository_id": "provider-a", "artifact_id": "a", "semantic_fingerprint": "s", "sha256": "x"},
                "retrieval_score": 90,
                "retrieval_basis": [{"kind": "exact_request_payload_identity", "score": 45}],
                "supporting_interface_ids": ["iface-a"],
                "supporting_interfaces": [{"repository_id": "provider-a", "interface_id": "iface-a"}],
            },
            {
                "candidate_id": "candidate-b",
                "repository_id": "provider-b",
                "repository_pin": {"repository_id": "provider-b", "artifact_id": "b", "semantic_fingerprint": "s", "sha256": "y"},
                "retrieval_score": 80,
                "retrieval_basis": [{"kind": "exact_response_payload_identity", "score": 45}],
                "supporting_interface_ids": ["iface-b"],
                "supporting_interfaces": [{"repository_id": "provider-b", "interface_id": "iface-b"}],
            },
        ],
    }
    payload["package_hash"] = _hash_payload(payload)
    return payload


def _valid_response(package):
    return ranking_response(
        package_hash=package["package_hash"],
        case_id=package["case"]["case_id"],
        ranked_candidates=[
            {
                "candidate_id": "candidate-b",
                "target_repository": "provider-b",
                "rank": 1,
                "supporting_interface_ids": ["iface-b"],
                "explanation": "stronger semantic fit",
            },
            {
                "candidate_id": "candidate-a",
                "target_repository": "provider-a",
                "rank": 2,
                "supporting_interface_ids": ["iface-a"],
                "explanation": "second",
            },
        ],
    )


class FakeAdapter:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def rerank(self, package):
        self.calls.append(copy.deepcopy(package))
        if self.error:
            raise self.error
        return copy.deepcopy(self.response)


def test_valid_response_yields_noncanonical_shortlist_and_keeps_deterministic_order():
    package = _package()
    adapter = FakeAdapter(_valid_response(package))
    result = rerank_package(
        package,
        adapter=adapter,
        identity=AdapterIdentity(provider="fake", model="weak-model"),
    )
    assert result["format"] == "repository-topology-semantic-shortlist/v1"
    assert result["classification"] == "non_canonical_hypothesis"
    assert result["status"] == "VALIDATED"
    assert result["deterministic_candidate_order"] == ["candidate-a", "candidate-b"]
    assert result["model_reranked_order"] == ["candidate-b", "candidate-a"]
    assert result["package_hash"] == package["package_hash"]
    assert adapter.calls == [package]


def test_tampered_package_is_rejected_before_adapter_call():
    package = _package()
    package["candidates"][0]["repository_id"] = "tampered"
    adapter = FakeAdapter({})
    with pytest.raises(PackageValidationError, match="package_hash"):
        rerank_package(package, adapter=adapter, identity=AdapterIdentity("fake", "m"))
    assert adapter.calls == []


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda r: r.update(case_id="wrong"), "case_id"),
        (lambda r: r.update(package_hash="0" * 64), "package_hash"),
        (lambda r: r["ranked_candidates"][0].update(candidate_id="not-supplied"), "candidate"),
        (lambda r: r["ranked_candidates"][0].update(target_repository="provider-a"), "target_repository"),
        (lambda r: r["ranked_candidates"][0].update(supporting_interface_ids=["iface-a"]), "cross candidate"),
        (lambda r: r["ranked_candidates"][1].update(rank=1), "ranks"),
    ],
)
def test_contract_violations_are_rejected(mutator, message):
    package = _package()
    response = _valid_response(package)
    mutator(response)
    with pytest.raises(ResponseValidationError, match=message):
        validate_response(package, response)


def test_provider_error_is_isolated_without_ranking():
    package = _package()
    result = rerank_package(
        package,
        adapter=FakeAdapter(error=TimeoutError("provider timed out")),
        identity=AdapterIdentity(provider="fake", model="weak-model"),
    )
    assert result["status"] == "PROVIDER_ERROR"
    assert result["model_reranked_order"] == []
    assert result["ranked_candidates"] == []
    assert result["diagnostics"][0]["code"] == "provider_error"


def test_malformed_provider_response_is_isolated_and_hashed():
    package = _package()
    response = _valid_response(package)
    response["unexpected"] = True
    result = rerank_package(
        package,
        adapter=FakeAdapter(response=response),
        identity=AdapterIdentity(provider="fake", model="weak-model"),
    )
    assert result["status"] == "INVALID_RESPONSE"
    assert result["model_reranked_order"] == []
    assert result["response_hash"] == _hash_payload(response)
    assert result["diagnostics"][0]["code"] == "invalid_response"


def test_package_and_valid_response_validation_is_deterministic():
    package = _package()
    assert validate_package(package) == validate_package(copy.deepcopy(package))
    response = _valid_response(package)
    assert validate_response(package, response) == validate_response(copy.deepcopy(package), copy.deepcopy(response))
