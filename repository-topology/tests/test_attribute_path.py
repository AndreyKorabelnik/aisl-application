import json
from pathlib import Path

from repository_topology.attribute_path import find_attribute_paths
from repository_topology.builder import build_topology
from repository_topology.cli import main
from repository_topology.mermaid import render_attribute_path_mermaid


def _write_http(tmp_path: Path, repo: str, observations: list[dict]) -> Path:
    exacts = []
    identities = []
    for index, observation in enumerate(observations):
        exact_id = f"exact-{index}"
        exacts.append(
            {
                "exact_representation_id": exact_id,
                "exact_representation_basis": {
                    "family_kind": "http_boundary_observation",
                    "observed_metrics": {
                        "protocol": "http",
                        "direction": observation["direction"],
                        "method": observation.get("method", "POST"),
                        "path_status": observation.get("path_status", "resolved"),
                    },
                },
            }
        )
        facets = []
        for field_index, name in enumerate(observation.get("request_fields", [])):
            facets.append({"path": f"$.request_fields[{field_index}].name", "value": name})
        for field_index, name in enumerate(observation.get("response_fields", [])):
            facets.append({"path": f"$.response_fields[{field_index}].name", "value": name})
        for path_index, value in enumerate(observation.get("path_candidates", [])):
            facets.append({"path": f"$.path_candidates[{path_index}]", "value": value})
        identities.append(
            {
                "observed_identity_id": f"obs-{repo}-{index}",
                "exact_representation_ids": [exact_id],
                "representative_evidence_id": f"ev-{repo}-{index}",
                "occurrence_count": 1,
                "identity": {
                    "family_kind": "http_boundary_observation",
                    "family_label": observation["label"],
                    "string_facets": facets,
                },
            }
        )
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


def _write_kafka(tmp_path: Path, repo: str, direction: str, fields: list[str]) -> Path:
    payload = {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"red-{repo}",
        "semantic_fingerprint": f"sem-{repo}",
        "source_inventory": {
            "repository_id": repo,
            "inventory_id": f"inv-{repo}",
            "source_snapshot_fingerprint": f"snap-{repo}",
        },
        "exact_representations": [
            {
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
            }
        ],
        "observed_identities": [
            {
                "observed_identity_id": f"obs-{repo}",
                "exact_representation_ids": ["exact-1"],
                "representative_evidence_id": f"ev-{repo}",
                "occurrence_count": 1,
                "identity": {
                    "family_kind": "kafka_boundary_observation",
                    "family_label": "customer-events",
                    "string_facets": [
                        {"path": f"$.payload_fields[{index}].name", "value": name}
                        for index, name in enumerate(fields)
                    ],
                },
            }
        ],
    }
    path = tmp_path / f"{repo}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_request_attribute_path_across_intermediate_repository(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["sberProfileId"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["sberProfileId"]},
        {"direction": "outbound", "label": "/bc", "request_fields": ["sberProfileId"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/bc", "request_fields": ["sberProfileId"]},
    ])
    topology = build_topology([a, b, c])
    result = find_attribute_paths(
        topology,
        attribute_name="sberProfileId",
        source_repository_id="a",
        target_repository_id="c",
    )
    assert topology["format"] == "repository-topology/v3"
    assert topology["attribute_identity_policy"] == {
        "name_comparison": "exact_case_sensitive",
        "rename_inference": "forbidden",
    }
    assert result["status"] == "found"
    assert result["summary"]["shortest_path_count"] == 1
    assert result["paths"][0]["repository_ids"] == ["a", "b", "c"]
    assert [hop["transport_role"] for hop in result["paths"][0]["crossings"]] == ["request", "request"]
    assert result["path_semantics"]["code_level_data_lineage"] is False
    assert result["path_semantics"]["intra_repository_continuity"] == "same_exact_name_assumed"


def test_rename_inside_repository_breaks_path(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["sberProfileId"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["sberProfileId"]},
        {"direction": "outbound", "label": "/bc", "request_fields": ["profileId"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/bc", "request_fields": ["profileId"]},
    ])
    result = find_attribute_paths(
        build_topology([a, b, c]),
        attribute_name="sberProfileId",
        source_repository_id="a",
        target_repository_id="c",
    )
    assert result["status"] == "not_found"
    assert result["diagnostics"][0]["kind"] == "no_exact_name_preserving_path"


def test_attribute_identity_is_case_sensitive(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["ucpId"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["ucpId"]},
        {"direction": "outbound", "label": "/bc", "request_fields": ["ucpID"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/bc", "request_fields": ["ucpID"]},
    ])
    result = find_attribute_paths(
        build_topology([a, b, c]),
        attribute_name="ucpId",
        source_repository_id="a",
        target_repository_id="c",
    )
    assert result["status"] == "not_found"


def test_http_response_attribute_flows_callee_to_caller(tmp_path):
    caller = _write_http(tmp_path, "caller", [
        {"direction": "outbound", "label": "/x", "response_fields": ["status"]},
    ])
    callee = _write_http(tmp_path, "callee", [
        {"direction": "inbound", "label": "/x", "response_fields": ["status"]},
    ])
    topology = build_topology([caller, callee])
    found = find_attribute_paths(
        topology,
        attribute_name="status",
        source_repository_id="callee",
        target_repository_id="caller",
    )
    assert found["status"] == "found"
    crossing = found["paths"][0]["crossings"][0]
    assert crossing["transport_role"] == "response"
    assert crossing["source_repository_id"] == "callee"
    assert crossing["target_repository_id"] == "caller"

    reverse = find_attribute_paths(
        topology,
        attribute_name="status",
        source_repository_id="caller",
        target_repository_id="callee",
    )
    assert reverse["status"] == "not_found"


def test_kafka_payload_attribute_path(tmp_path):
    publisher = _write_kafka(tmp_path, "publisher", "publish", ["customerId", "tags"])
    consumer = _write_kafka(tmp_path, "consumer", "consume", ["customerId", "tags"])
    result = find_attribute_paths(
        build_topology([publisher, consumer]),
        attribute_name="customerId",
        source_repository_id="publisher",
        target_repository_id="consumer",
    )
    assert result["status"] == "found"
    assert result["paths"][0]["crossings"][0]["transport_role"] == "payload"


def test_all_shortest_paths_are_preserved(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["id"]},
        {"direction": "outbound", "label": "/ac", "request_fields": ["id"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["id"]},
        {"direction": "outbound", "label": "/bd", "request_fields": ["id"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/ac", "request_fields": ["id"]},
        {"direction": "outbound", "label": "/cd", "request_fields": ["id"]},
    ])
    d = _write_http(tmp_path, "d", [
        {"direction": "inbound", "label": "/bd", "request_fields": ["id"]},
        {"direction": "inbound", "label": "/cd", "request_fields": ["id"]},
    ])
    result = find_attribute_paths(
        build_topology([a, b, c, d]),
        attribute_name="id",
        source_repository_id="a",
        target_repository_id="d",
    )
    assert result["summary"]["shortest_path_count"] == 2
    assert [path["repository_ids"] for path in result["paths"]] == [
        ["a", "b", "d"],
        ["a", "c", "d"],
    ]


def test_attribute_flows_are_derived_from_actual_probable_match_pairs(tmp_path):
    a_names = [f"a{i}" for i in range(9)]
    b_names = [f"b{i}" for i in range(9)]
    source = _write_http(tmp_path, "source", [
        {
            "direction": "outbound",
            "label": "prop-a",
            "path_status": "ambiguous_declared_config",
            "path_candidates": ["/prefix/update"],
            "request_fields": [*a_names, "phantom"],
        },
        {
            "direction": "outbound",
            "label": "prop-b",
            "path_status": "ambiguous_declared_config",
            "path_candidates": ["/other/update"],
            "request_fields": [*b_names, "sourceOnly"],
        },
    ])
    target = _write_http(tmp_path, "target", [
        {"direction": "inbound", "label": "/update", "request_fields": [*a_names, "targetOnly"]},
        {"direction": "inbound", "label": "/update", "request_fields": [*b_names, "phantom"]},
    ])
    topology = build_topology([source, target])
    assert len(topology["edges"]) == 1
    flow = topology["edges"][0]["attribute_flows"][0]
    assert flow["transport_role"] == "request"
    assert "a0" in flow["attribute_names"]
    assert "b0" in flow["attribute_names"]
    assert "phantom" not in flow["attribute_names"]


def test_attribute_path_cli_writes_json_and_mermaid(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/x", "request_fields": ["id"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/x", "request_fields": ["id"]},
    ])
    topology_path = tmp_path / "repository_topology.json"
    topology_path.write_text(json.dumps(build_topology([a, b])), encoding="utf-8")
    output = tmp_path / "attribute_path.json"
    mermaid_output = tmp_path / "attribute_path.mmd"
    assert main([
        "attribute-path",
        "--topology", str(topology_path),
        "--attribute", "id",
        "--from-repository", "a",
        "--to-repository", "b",
        "--output", str(output),
        "--mermaid-output", str(mermaid_output),
    ]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["format"] == "repository-attribute-path/v2"
    assert result["status"] == "found"
    assert mermaid_output.read_text(encoding="utf-8") == render_attribute_path_mermaid(result)
    assert "request: id" in mermaid_output.read_text(encoding="utf-8")



def test_attribute_path_source_bound_only_returns_shortest_routes_to_all_reachable(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["id"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["id"]},
        {"direction": "outbound", "label": "/bc", "request_fields": ["id"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/bc", "request_fields": ["id"]},
    ])
    result = find_attribute_paths(
        build_topology([a, b, c]),
        attribute_name="id",
        source_repository_id="a",
    )
    assert result["query_scope"] == "from_repository"
    assert result["source_repository_id"] == "a"
    assert result["target_repository_id"] is None
    assert result["status"] == "found"
    assert [(p["source_repository_id"], p["target_repository_id"], p["hop_count"]) for p in result["paths"]] == [
        ("a", "b", 1),
        ("a", "c", 2),
    ]
    assert [(c["source_repository_id"], c["target_repository_id"]) for c in result["selected_crossings"]] == [
        ("a", "b"),
        ("b", "c"),
    ]


def test_attribute_path_target_bound_only_returns_shortest_routes_from_all_reachable(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["id"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["id"]},
        {"direction": "outbound", "label": "/bc", "request_fields": ["id"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/bc", "request_fields": ["id"]},
    ])
    result = find_attribute_paths(
        build_topology([a, b, c]),
        attribute_name="id",
        target_repository_id="c",
    )
    assert result["query_scope"] == "to_repository"
    assert result["source_repository_id"] is None
    assert result["target_repository_id"] == "c"
    assert result["status"] == "found"
    assert [(p["source_repository_id"], p["target_repository_id"], p["hop_count"]) for p in result["paths"]] == [
        ("a", "c", 2),
        ("b", "c", 1),
    ]


def test_attribute_path_without_repository_bounds_returns_complete_attribute_subgraph(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/ab", "request_fields": ["id"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/ab", "request_fields": ["id"]},
        {"direction": "outbound", "label": "/bc", "request_fields": ["id"]},
    ])
    c = _write_http(tmp_path, "c", [
        {"direction": "inbound", "label": "/bc", "request_fields": ["id"]},
    ])
    x = _write_http(tmp_path, "x", [
        {"direction": "outbound", "label": "/xy", "request_fields": ["id"]},
    ])
    y = _write_http(tmp_path, "y", [
        {"direction": "inbound", "label": "/xy", "request_fields": ["id"]},
    ])
    result = find_attribute_paths(build_topology([a, b, c, x, y]), attribute_name="id")
    assert result["query_scope"] == "all_repositories"
    assert result["source_repository_id"] is None
    assert result["target_repository_id"] is None
    assert result["status"] == "found"
    assert result["paths"] == []
    assert result["summary"]["selected_crossing_count"] == 3
    assert {(c["source_repository_id"], c["target_repository_id"]) for c in result["selected_crossings"]} == {
        ("a", "b"), ("b", "c"), ("x", "y")
    }
    mermaid = render_attribute_path_mermaid(result)
    assert 'request: id' in mermaid
    assert mermaid.count('request: id') == 3


def test_attribute_path_cli_allows_omitting_both_repository_bounds(tmp_path):
    a = _write_http(tmp_path, "a", [
        {"direction": "outbound", "label": "/x", "request_fields": ["id"]},
    ])
    b = _write_http(tmp_path, "b", [
        {"direction": "inbound", "label": "/x", "request_fields": ["id"]},
    ])
    topology_path = tmp_path / "repository_topology.json"
    topology_path.write_text(json.dumps(build_topology([a, b])), encoding="utf-8")
    output = tmp_path / "attribute_path.json"
    mermaid_output = tmp_path / "attribute_path.mmd"
    assert main([
        "attribute-path",
        "--topology", str(topology_path),
        "--attribute", "id",
        "--output", str(output),
        "--mermaid-output", str(mermaid_output),
    ]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["query_scope"] == "all_repositories"
    assert result["status"] == "found"
    assert result["summary"]["selected_crossing_count"] == 1
    assert "request: id" in mermaid_output.read_text(encoding="utf-8")
