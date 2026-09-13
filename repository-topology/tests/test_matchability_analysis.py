import json
from pathlib import Path

from repository_topology.builder import build_topology


def _http_repo(tmp_path: Path, repo: str, observations: list[dict]) -> Path:
    exacts = []
    identities = []
    for i, obs in enumerate(observations):
        exact_id = f"exact-{repo}-{i}"
        exacts.append({
            "exact_representation_id": exact_id,
            "exact_representation_basis": {
                "family_kind": "http_boundary_observation",
                "observed_metrics": {
                    "protocol": "http",
                    "direction": obs["direction"],
                    "method": obs.get("method"),
                    "path_status": obs["path_status"],
                },
            },
        })
        facets = []
        for index, value in enumerate(obs.get("path_candidates", [])):
            facets.append({"path": f"$.path_candidates[{index}]", "value": value})
        for index, value in enumerate(obs.get("request_fields", [])):
            facets.append({"path": f"$.request_fields[{index}].name", "value": value})
        identities.append({
            "observed_identity_id": f"obs-{repo}-{i}",
            "exact_representation_ids": [exact_id],
            "representative_evidence_id": f"ev-{repo}-{i}",
            "occurrence_count": obs.get("occurrence_count", 1),
            "identity": {
                "family_kind": "http_boundary_observation",
                "family_label": obs.get("label", ""),
                "string_facets": facets,
            },
        })
    payload = {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"red-{repo}",
        "semantic_fingerprint": f"sem-{repo}",
        "source_inventory": {
            "repository_id": repo,
            "inventory_id": f"inv-{repo}",
            "source_snapshot_fingerprint": f"snap-{repo}",
        },
        "exact_representations": exacts,
        "observed_identities": identities,
    }
    path = tmp_path / f"{repo}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _empty_repo(tmp_path: Path, repo: str) -> Path:
    payload = {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"red-{repo}",
        "semantic_fingerprint": f"sem-{repo}",
        "source_inventory": {
            "repository_id": repo,
            "inventory_id": f"inv-{repo}",
            "source_snapshot_fingerprint": f"snap-{repo}",
        },
        "exact_representations": [],
        "observed_identities": [],
    }
    path = tmp_path / f"{repo}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _reason_counts(topology: dict) -> dict[str, int]:
    return {
        row["reason"]: row["count"]
        for row in topology["matchability_analysis"]["unmatched_reason_counts"]
    }


def test_reports_repositories_without_transport_half_wires(tmp_path):
    a = _empty_repo(tmp_path, "a")
    b = _empty_repo(tmp_path, "b")
    out = build_topology([a, b])
    summary = out["matchability_analysis"]["summary"]
    assert summary["repository_count"] == 2
    assert summary["repository_with_half_wire_count"] == 0
    assert summary["repository_without_half_wire_count"] == 2
    assert summary["half_wire_count"] == 0
    assert out["diagnostics"] == []


def test_reports_resolved_http_without_inbound_same_path(tmp_path):
    a = _http_repo(tmp_path, "a", [{"direction": "outbound", "method": "POST", "path_status": "resolved", "label": "/x"}])
    b = _http_repo(tmp_path, "b", [{"direction": "inbound", "method": "POST", "path_status": "resolved", "label": "/y"}])
    out = build_topology([a, b])
    counts = _reason_counts(out)
    assert counts["http_exact_no_inbound_same_path"] == 1
    assert counts["http_inbound_no_outbound_candidate"] == 1
    assert out["summary"]["edge_count"] == 0


def test_reports_http_method_mismatch(tmp_path):
    a = _http_repo(tmp_path, "a", [{"direction": "outbound", "method": "POST", "path_status": "resolved", "label": "/x"}])
    b = _http_repo(tmp_path, "b", [{"direction": "inbound", "method": "GET", "path_status": "resolved", "label": "/x"}])
    out = build_topology([a, b])
    counts = _reason_counts(out)
    assert counts["http_exact_method_mismatch"] == 1
    assert counts["http_inbound_exact_method_mismatch"] == 1


def test_reports_probable_field_overlap_below_threshold(tmp_path):
    a = _http_repo(tmp_path, "a", [{
        "direction": "outbound",
        "method": "POST",
        "path_status": "ambiguous_declared_config",
        "label": "property",
        "path_candidates": ["/prefix/update"],
        "request_fields": ["a", "b", "c", "d"],
    }])
    b = _http_repo(tmp_path, "b", [{
        "direction": "inbound",
        "method": "POST",
        "path_status": "resolved",
        "label": "/update",
        "request_fields": ["a", "z"],
    }])
    out = build_topology([a, b])
    outbound = next(row for row in out["diagnostics"] if row["repository_id"] == "a")
    assert outbound["reason"] == "http_probable_request_field_overlap_below_threshold"
    assert outbound["max_request_field_overlap"] == 0.2
    assert outbound["required_request_field_overlap"] == 0.8


def test_matched_half_wires_are_not_reported_as_unmatched(tmp_path):
    a = _http_repo(tmp_path, "a", [{"direction": "outbound", "method": "POST", "path_status": "resolved", "label": "/x"}])
    b = _http_repo(tmp_path, "b", [{"direction": "inbound", "method": "POST", "path_status": "resolved", "label": "/x"}])
    out = build_topology([a, b])
    summary = out["matchability_analysis"]["summary"]
    assert summary["half_wire_count"] == 2
    assert summary["matched_half_wire_count"] == 2
    assert summary["unmatched_half_wire_count"] == 0
    assert out["diagnostics"] == []
