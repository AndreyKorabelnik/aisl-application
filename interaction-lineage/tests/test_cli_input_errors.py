from __future__ import annotations

import json

from aisl_interaction_lineage.cli import main


def test_check_missing_bindings_writes_structured_error_without_api_contact(tmp_path) -> None:
    topology = tmp_path / "topology.json"
    topology.write_text(json.dumps({
        "format": "repository-topology/v5", "topology_id": "toy", "edges": [],
    }), encoding="utf-8")
    output = tmp_path / "error.json"
    code = main([
        "check", "--topology", str(topology), "--edge-id", "unknown",
        "--bindings", str(tmp_path / "absent-bindings.json"),
        "--aisl-base-url", "http://127.0.0.1:1", "--output", str(output),
    ])
    assert code == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["diagnostics"][0]["exception_type"] == "FileNotFoundError"


def test_prepare_invalid_topology_writes_structured_error_before_kcp(tmp_path) -> None:
    bad_topology = tmp_path / "invalid.json"
    bad_topology.write_text("not json", encoding="utf-8")
    output = tmp_path / "error.json"
    code = main([
        "prepare", "--topology", str(bad_topology), "--edge-id", "unknown",
        "--aisl-base-url", "http://127.0.0.1:1", "--kcp-base-url", "http://127.0.0.1:2",
        "--output", str(output),
    ])
    assert code == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["diagnostics"][0]["exception_type"] == "JSONDecodeError"
