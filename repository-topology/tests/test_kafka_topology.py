import json
from pathlib import Path

from repository_topology.builder import build_topology


def _write(tmp_path: Path, repo: str, direction: str, topic: str, *, kind: str = "literal", status: str = "resolved") -> Path:
    payload = {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"red-{repo}",
        "semantic_fingerprint": f"sem-{repo}",
        "source_inventory": {"repository_id": repo, "inventory_id": f"inv-{repo}", "source_snapshot_fingerprint": f"snap-{repo}"},
        "exact_representations": [{
            "exact_representation_id": "exact-1",
            "exact_representation_basis": {"family_kind": "kafka_boundary_observation", "observed_metrics": {
                "protocol": "kafka", "direction": direction, "topic_status": status, "topic_identity_kind": kind
            }}
        }],
        "observed_identities": [{
            "observed_identity_id": f"obs-{repo}", "exact_representation_ids": ["exact-1"], "representative_evidence_id": f"ev-{repo}",
            "occurrence_count": 1,
            "identity": {"family_kind": "kafka_boundary_observation", "family_label": topic, "string_facets": [
                {"path": "$.payload_identity", "value": "CustomerEvent"},
                {"path": "$.payload_fields[0].name", "value": "customerId"},
                {"path": "$.payload_fields[1].name", "value": "tags"}
            ]}
        }]
    }
    p=tmp_path/f"{repo}.json"; p.write_text(json.dumps(payload)); return p


def test_literal_topic_publish_consume_creates_exact_edge(tmp_path):
    pub=_write(tmp_path,"pub","publish","customer-events")
    con=_write(tmp_path,"con","consume","customer-events")
    out=build_topology([pub,con])
    assert out["summary"]["edge_count"] == 1
    edge=out["edges"][0]
    assert edge["protocol"] == "kafka"
    assert edge["match_classification"] == "exact"
    assert edge["matched_identity"] == "customer-events"
    assert edge["source_half_wires"][0]["payload_identity"] == "CustomerEvent"
    assert edge["source_half_wires"][0]["payload_field_names"] == ["customerId","tags"]


def test_same_config_key_is_not_topic_equality(tmp_path):
    pub=_write(tmp_path,"pub","publish","kafka.topic.customer",kind="config_key")
    con=_write(tmp_path,"con","consume","kafka.topic.customer",kind="config_key")
    assert build_topology([pub,con])["edges"] == []


def test_unresolved_literal_does_not_match(tmp_path):
    pub=_write(tmp_path,"pub","publish","customer-events",status="unresolved_expression")
    con=_write(tmp_path,"con","consume","customer-events")
    assert build_topology([pub,con])["edges"] == []


def test_non_literal_kafka_identity_is_diagnosed(tmp_path):
    pub=_write(tmp_path,"pub","publish","kafka.topic.customer",kind="config_key")
    con=_write(tmp_path,"con","consume","customer-events")
    out=build_topology([pub,con])
    reasons={row["reason"] for row in out["diagnostics"]}
    assert "kafka_identity_not_literal" in reasons
    assert "kafka_consume_no_publisher_same_literal_topic" in reasons


def test_literal_kafka_without_counterpart_is_diagnosed(tmp_path):
    pub=_write(tmp_path,"pub","publish","customer-events")
    con=_write(tmp_path,"con","consume","other-events")
    out=build_topology([pub,con])
    counts={row["reason"]: row["count"] for row in out["matchability_analysis"]["unmatched_reason_counts"]}
    assert counts["kafka_publish_no_consumer_same_literal_topic"] == 1
    assert counts["kafka_consume_no_publisher_same_literal_topic"] == 1
