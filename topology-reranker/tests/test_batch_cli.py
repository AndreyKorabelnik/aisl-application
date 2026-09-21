from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from repository_topology_reranker import AdapterIdentity, BatchInputError, ResumeStateError
from repository_topology_reranker.batch import packages_from_document, rerank_batch
from repository_topology_reranker.external_command import ExternalCommandAdapter
from repository_topology_reranker.runner import ranking_response
from repository_topology_reranker.validation import PackageValidationError


def _hash_payload(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _package(case_id="case-x", suffix="a"):
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
            "case_id": case_id,
            "classification": "RERANKABLE_RESIDUAL",
            "reason": "multiple_mechanically_admissible_candidate_repositories",
        },
        "source": {
            "repository_id": f"caller-{suffix}",
            "repository_pin": {"repository_id": f"caller-{suffix}", "artifact_id": "a", "semantic_fingerprint": "s", "sha256": "x"},
            "diagnostic_reason": "unresolved",
            "interface_id": f"source-{suffix}",
            "interface": {"repository_id": f"caller-{suffix}", "interface_id": f"source-{suffix}"},
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
                "candidate_id": f"candidate-{suffix}-1",
                "repository_id": f"provider-{suffix}-1",
                "repository_pin": {"repository_id": f"provider-{suffix}-1", "artifact_id": "a", "semantic_fingerprint": "s", "sha256": "x"},
                "retrieval_score": 90,
                "retrieval_basis": [{"kind": "exact_request_payload_identity", "score": 45}],
                "supporting_interface_ids": [f"iface-{suffix}-1"],
                "supporting_interfaces": [{"repository_id": f"provider-{suffix}-1", "interface_id": f"iface-{suffix}-1"}],
            },
            {
                "candidate_id": f"candidate-{suffix}-2",
                "repository_id": f"provider-{suffix}-2",
                "repository_pin": {"repository_id": f"provider-{suffix}-2", "artifact_id": "b", "semantic_fingerprint": "s", "sha256": "y"},
                "retrieval_score": 80,
                "retrieval_basis": [{"kind": "exact_response_payload_identity", "score": 45}],
                "supporting_interface_ids": [f"iface-{suffix}-2"],
                "supporting_interfaces": [{"repository_id": f"provider-{suffix}-2", "interface_id": f"iface-{suffix}-2"}],
            },
        ],
    }
    payload["package_hash"] = _hash_payload(payload)
    return payload


def _response(package):
    candidate = package["candidates"][1]
    return ranking_response(
        package_hash=package["package_hash"],
        case_id=package["case"]["case_id"],
        ranked_candidates=[{
            "candidate_id": candidate["candidate_id"],
            "target_repository": candidate["repository_id"],
            "rank": 1,
            "supporting_interface_ids": candidate["supporting_interface_ids"],
            "explanation": "semantic fit",
        }],
    )


class FakeAdapter:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def rerank(self, package):
        self.calls.append(copy.deepcopy(package))
        if self.error:
            raise self.error
        return _response(package)


def test_package_document_accepts_single_array_and_pr_a_envelope():
    p1, p2 = _package("case-1", "a"), _package("case-2", "b")
    assert packages_from_document(p1) == [p1]
    assert packages_from_document([p1, p2]) == [p1, p2]
    assert packages_from_document({"packages": [p1, p2], "summary": {}}) == [p1, p2]


def test_package_document_rejects_unknown_shape_and_duplicates():
    with pytest.raises(BatchInputError):
        packages_from_document({"not_packages": []})
    p = _package()
    with pytest.raises(BatchInputError, match="duplicate"):
        packages_from_document([p, p])


def test_batch_writes_results_and_resume_skips_adapter(tmp_path: Path):
    packages = [_package("case-1", "a"), _package("case-2", "b")]
    adapter = FakeAdapter()
    identity = AdapterIdentity("fake", "weak")
    first = rerank_batch(packages, output_dir=tmp_path, adapter=adapter, identity=identity)
    assert first["adapter_invocation_count"] == 2
    assert first["resumed_count"] == 0
    assert len(adapter.calls) == 2
    second = rerank_batch(packages, output_dir=tmp_path, adapter=adapter, identity=identity)
    assert second["adapter_invocation_count"] == 0
    assert second["resumed_count"] == 2
    assert len(adapter.calls) == 2


def test_zero_package_batch_makes_zero_calls_and_writes_manifest(tmp_path: Path):
    adapter = FakeAdapter()
    manifest = rerank_batch([], output_dir=tmp_path, adapter=adapter, identity=AdapterIdentity("fake", "m"))
    assert manifest["package_count"] == 0
    assert manifest["adapter_invocation_count"] == 0
    assert adapter.calls == []
    assert json.loads((tmp_path / "run-manifest.json").read_text())["package_count"] == 0


def test_provider_error_is_persisted_and_resumed(tmp_path: Path):
    package = _package()
    adapter = FakeAdapter(error=TimeoutError("boom"))
    first = rerank_batch([package], output_dir=tmp_path, adapter=adapter, identity=AdapterIdentity("fake", "m"))
    assert first["status_counts"] == {"PROVIDER_ERROR": 1}
    assert len(adapter.calls) == 1
    second = rerank_batch([package], output_dir=tmp_path, adapter=adapter, identity=AdapterIdentity("fake", "m"))
    assert second["resumed_count"] == 1
    assert len(adapter.calls) == 1


def test_tampered_package_fails_before_first_adapter_call(tmp_path: Path):
    good = _package("case-1", "a")
    bad = _package("case-2", "b")
    bad["source"]["repository_id"] = "tampered"
    adapter = FakeAdapter()
    with pytest.raises(PackageValidationError):
        rerank_batch([good, bad], output_dir=tmp_path, adapter=adapter, identity=AdapterIdentity("fake", "m"))
    assert adapter.calls == []


def test_resume_state_mismatch_fails_closed(tmp_path: Path):
    package = _package()
    path = tmp_path / f"{package['package_hash']}.json"
    tmp_path.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "format": "repository-topology-semantic-shortlist/v1",
        "classification": "non_canonical_hypothesis",
        "package_hash": package["package_hash"],
        "case_id": "wrong-case",
        "status": "VALIDATED",
    }))
    with pytest.raises(ResumeStateError, match="case_id"):
        rerank_batch([package], output_dir=tmp_path, adapter=FakeAdapter(), identity=AdapterIdentity("fake", "m"))


def test_external_command_adapter_round_trip(tmp_path: Path):
    script = tmp_path / "adapter.py"
    script.write_text(
        "import json,sys\n"
        "p=json.load(sys.stdin)\n"
        "c=p['candidates'][0]\n"
        "json.dump({'format':'repository-topology-rerank-response/v1','package_hash':p['package_hash'],'case_id':p['case']['case_id'],'ranked_candidates':[{'candidate_id':c['candidate_id'],'target_repository':c['repository_id'],'rank':1,'supporting_interface_ids':c['supporting_interface_ids'],'explanation':'ok'}]},sys.stdout)\n"
    )
    package = _package()
    adapter = ExternalCommandAdapter(sys.executable, [str(script)])
    response = adapter.rerank(package)
    assert response["package_hash"] == package["package_hash"]
    assert response["ranked_candidates"][0]["candidate_id"] == package["candidates"][0]["candidate_id"]
