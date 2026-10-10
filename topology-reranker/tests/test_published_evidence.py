from __future__ import annotations

import copy

import pytest

from repository_topology_reranker.published_evidence import (
    PublishedEvidenceError, rank_published_candidates, REQUEST_FORMAT, RESULT_FORMAT,
)


def candidate(repository, *, score=225):
    return {
        "repository_id": repository, "revision_id": "rev-immutable1", "artifact_id": "inventory-observations",
        "interface_id": "iface-" + repository, "retrieval_score": score,
        "method": "POST", "route": "/kpk/ucpIdToSub",
        "request_payload": "UcpIdToSubRequest", "response_payload": "UcpIdToSubResponse",
    }


def published(c, java=False):
    return {"item": {
        "interface_id": c["interface_id"], "direction": "inbound", "protocol": "http",
        "method": "POST", "address": {"value": c["route"], "status": "resolved"},
        "payloads": [{"role": "request", "identity": "UcpIdToSubRequest"},
                     {"role": "response", "identity": "UcpIdToSubResponse"}],
        "evidence_ids": ["file-evidence-1"],
        "provenance": {"basis_variants": [{"kind": "java_exact_route_annotation" if java else "openapi_paths_operation"}]},
    }}


def test_java_breaks_equal_score_tie_but_keeps_all_alternatives():
    rows = [candidate("openapi_a"), candidate("java_b"), candidate("openapi_c")]
    received = {c["interface_id"]: published(c, java=c["repository_id"] == "java_b") for c in rows}
    request = {"format": REQUEST_FORMAT, "case_id": "SBS", "candidates": rows}
    result = rank_published_candidates(request, get_knowledge_item=lambda repo, rev, art, iid: received[iid])
    assert result["format"] == RESULT_FORMAT
    assert [x["repository_id"] for x in result["candidates"]] == ["java_b", "openapi_a", "openapi_c"]
    assert result["selection_status"] == "single_evidence_leader_not_runtime_proof"
    assert result["candidates"][0]["evidence_ids"] == ["file-evidence-1"]
    assert result["runtime_target_proven"] is False
    assert result["canonical_topology_mutated"] is False


def test_java_never_overrides_stronger_original_retrieval_score():
    rows = [candidate("higher_score", score=230), candidate("java", score=225)]
    received = {c["interface_id"]: published(c, java=c["repository_id"] == "java") for c in rows}
    result = rank_published_candidates({"format": REQUEST_FORMAT, "case_id": "C", "candidates": rows},
                                       get_knowledge_item=lambda r, v, a, i: received[i])
    assert [x["repository_id"] for x in result["candidates"]] == ["higher_score", "java"]


def test_two_real_implementations_remain_ambiguous():
    rows = [candidate("java_a"), candidate("java_b")]
    received = {c["interface_id"]: published(c, java=True) for c in rows}
    result = rank_published_candidates({"format": REQUEST_FORMAT, "case_id": "C", "candidates": rows},
                                       get_knowledge_item=lambda r, v, a, i: received[i])
    assert result["top_evidence_tie_count"] == 2
    assert result["selection_status"] == "ambiguous_top_evidence"


def test_openapi_only_is_no_implementation_claim():
    rows = [candidate("a"), candidate("b")]
    received = {c["interface_id"]: published(c) for c in rows}
    result = rank_published_candidates({"format": REQUEST_FORMAT, "case_id": "C", "candidates": rows},
                                       get_knowledge_item=lambda r, v, a, i: received[i])
    assert result["top_evidence_tie_count"] == 2
    assert result["selection_status"] == "ambiguous_top_evidence"
    assert all(not c["observed_java_implementation"] for c in result["candidates"])


@pytest.mark.parametrize("mutation", [
    lambda d: d["candidates"][0].update(revision_id="latest"),
    lambda d: d["candidates"][0].update(retrieval_score=True),
    lambda d: d["candidates"][0].update(interface_id=""),
    lambda d: d["candidates"].append(copy.deepcopy(d["candidates"][0])),
])
def test_invalid_request_fails_closed(mutation):
    doc = {"format": REQUEST_FORMAT, "case_id": "C", "candidates": [candidate("a")]}
    mutation(doc)
    with pytest.raises(PublishedEvidenceError):
        rank_published_candidates(doc, get_knowledge_item=lambda *args: None)


@pytest.mark.parametrize("mutation", [
    lambda d: d["item"].update(method="GET"),
    lambda d: d["item"].update(interface_id="wrong"),
    lambda d: d["item"].update(address={"status": "unresolved_expression", "value": None}),
    lambda d: d["item"].update(payloads=[]),
    lambda d: d["item"].update(provenance={}),
])
def test_mismatched_or_missing_published_fact_fails_closed(mutation):
    c = candidate("a")
    body = published(c, java=True)
    mutation(body)
    with pytest.raises(PublishedEvidenceError):
        rank_published_candidates({"format": REQUEST_FORMAT, "case_id": "C", "candidates": [c]},
                                  get_knowledge_item=lambda *args: body)
