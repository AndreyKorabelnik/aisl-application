import json
from pathlib import Path

from repository_topology.builder import build_topology
from repository_topology.cli import main
from repository_topology.mermaid import render_repository_mermaid


def _write_http(tmp_path: Path, repo: str, direction: str, *, status: str = "resolved") -> Path:
    facets = [
        {"path": "$.request_fields[0].name", "value": "sberProfileId"},
        {"path": "$.request_fields[1].name", "value": "scope"},
        {"path": "$.response_fields[0].name", "value": "status"},
    ]
    payload = {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"red-{repo}",
        "semantic_fingerprint": f"sem-{repo}",
        "source_inventory": {
            "repository_id": repo,
            "inventory_id": f"inv-{repo}",
            "source_snapshot_fingerprint": f"snap-{repo}",
        },
        "exact_representations": [{
            "exact_representation_id": "exact-1",
            "exact_representation_basis": {
                "family_kind": "http_boundary_observation",
                "observed_metrics": {
                    "protocol": "http",
                    "direction": direction,
                    "method": "POST",
                    "path_status": status,
                },
            },
        }],
        "observed_identities": [{
            "observed_identity_id": f"obs-{repo}",
            "exact_representation_ids": ["exact-1"],
            "representative_evidence_id": f"ev-{repo}",
            "occurrence_count": 1,
            "identity": {
                "family_kind": "http_boundary_observation",
                "family_label": "/sberProfileId/search",
                "string_facets": facets,
            },
        }],
    }
    path = tmp_path / f"{repo}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_kafka(tmp_path: Path, repo: str, direction: str) -> Path:
    payload = {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"red-{repo}",
        "semantic_fingerprint": f"sem-{repo}",
        "source_inventory": {
            "repository_id": repo,
            "inventory_id": f"inv-{repo}",
            "source_snapshot_fingerprint": f"snap-{repo}",
        },
        "exact_representations": [{
            "exact_representation_id": "exact-1",
            "exact_representation_basis": {
                "family_kind": "kafka_boundary_observation",
                "observed_metrics": {
                    "protocol": "kafka",
                    "direction": direction,
                    "topic_status": "resolved",
                    "topic_identity_kind": "literal",
                },
            },
        }],
        "observed_identities": [{
            "observed_identity_id": f"obs-{repo}",
            "exact_representation_ids": ["exact-1"],
            "representative_evidence_id": f"ev-{repo}",
            "occurrence_count": 1,
            "identity": {
                "family_kind": "kafka_boundary_observation",
                "family_label": "customer-events",
                "string_facets": [
                    {"path": "$.payload_fields[0].name", "value": "customerId"},
                    {"path": "$.payload_fields[1].name", "value": "tags"},
                ],
            },
        }],
    }
    path = tmp_path / f"{repo}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_http_mermaid_shows_api_request_and_response_fields(tmp_path):
    caller = _write_http(tmp_path, "caller", "outbound")
    callee = _write_http(tmp_path, "callee", "inbound")
    topology = build_topology([caller, callee])

    edge = topology["edges"][0]
    assert edge["source_half_wires"][0]["response_field_names"] == ["status"]
    assert edge["target_half_wires"][0]["response_field_names"] == ["status"]

    mermaid = render_repository_mermaid(topology)
    assert mermaid.startswith("flowchart LR\n")
    assert "POST /sberProfileId/search" in mermaid
    assert "request: sberProfileId, scope" in mermaid
    assert "response: status" in mermaid
    assert " -->|" in mermaid


def test_kafka_mermaid_shows_topic_and_payload_fields(tmp_path):
    publisher = _write_kafka(tmp_path, "publisher", "publish")
    consumer = _write_kafka(tmp_path, "consumer", "consume")
    mermaid = render_repository_mermaid(build_topology([publisher, consumer]))
    assert "Kafka customer-events" in mermaid
    assert "payload: customerId, tags" in mermaid


def test_mermaid_only_shows_names_observed_on_both_sides(tmp_path):
    caller = _write_http(tmp_path, "caller", "outbound")
    callee = _write_http(tmp_path, "callee", "inbound")
    payload = json.loads(callee.read_text(encoding="utf-8"))
    payload["observed_identities"][0]["identity"]["string_facets"].append(
        {"path": "$.response_fields[1].name", "value": "calleeOnly"}
    )
    callee.write_text(json.dumps(payload), encoding="utf-8")
    mermaid = render_repository_mermaid(build_topology([caller, callee]))
    assert "calleeOnly" not in mermaid


def test_mermaid_cli_renders_existing_topology(tmp_path):
    caller = _write_http(tmp_path, "caller", "outbound")
    callee = _write_http(tmp_path, "callee", "inbound")
    topology_path = tmp_path / "repository_topology.json"
    topology_path.write_text(json.dumps(build_topology([caller, callee])), encoding="utf-8")
    output = tmp_path / "repository_topology.mmd"
    assert main(["mermaid", "--topology", str(topology_path), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == render_repository_mermaid(
        json.loads(topology_path.read_text(encoding="utf-8"))
    )
