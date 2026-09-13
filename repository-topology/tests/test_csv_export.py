import csv
import io
import json
from pathlib import Path

import pytest

from repository_topology.builder import build_topology
from repository_topology.cli import main
from repository_topology.csv_export import render_topology_csv, topology_csv_rows


def _reduced(repo_id: str, observations: list[dict]) -> dict:
    exacts = []
    identities = []
    for i, obs in enumerate(observations):
        eid = f"exact-{repo_id}-{i}"
        exacts.append(
            {
                "exact_representation_id": eid,
                "exact_representation_basis": {
                    "family_kind": "http_boundary_observation",
                    "observed_metrics": {
                        "protocol": "http",
                        "direction": obs["direction"],
                        "method": obs["method"],
                        "path_status": obs["path_status"],
                    },
                },
            }
        )
        facets = []
        for idx, path in enumerate(obs.get("path_candidates", [])):
            facets.append({"path": f"$.path_candidates[{idx}]", "value": path})
        for idx, name in enumerate(obs.get("request_fields", [])):
            facets.append({"path": f"$.request_fields[{idx}].name", "value": name})
        for idx, name in enumerate(obs.get("response_fields", [])):
            facets.append({"path": f"$.response_fields[{idx}].name", "value": name})
        identities.append(
            {
                "observed_identity_id": f"obs-{repo_id}-{i}",
                "exact_representation_ids": [eid],
                "representative_evidence_id": f"evidence-{repo_id}-{i}",
                "occurrence_count": 1,
                "identity": {
                    "family_kind": "http_boundary_observation",
                    "family_label": obs["label"],
                    "string_facets": facets,
                },
            }
        )
    return {
        "format": "repository-inventory-reduced/v3",
        "reduced_inventory_id": f"reduced-{repo_id}",
        "semantic_fingerprint": f"sem-{repo_id}",
        "source_inventory": {
            "repository_id": repo_id,
            "inventory_id": f"inv-{repo_id}",
            "source_snapshot_fingerprint": f"snap-{repo_id}",
        },
        "exact_representations": exacts,
        "observed_identities": identities,
    }


def _write(tmp_path: Path, repo: str, observations: list[dict]) -> Path:
    path = tmp_path / f"{repo}.json"
    path.write_text(json.dumps(_reduced(repo, observations)), encoding="utf-8")
    return path


def _topology(tmp_path: Path) -> dict:
    a = _write(
        tmp_path,
        "repo-a",
        [
            {
                "direction": "outbound",
                "method": "POST",
                "path_status": "resolved",
                "label": "/search",
                "request_fields": ["sberProfileId", "@formulaLike"],
                "response_fields": ["status"],
            },
            {
                "direction": "outbound",
                "method": "POST",
                "path_status": "unresolved_expression",
                "label": "dynamicPath",
            },
        ],
    )
    b = _write(
        tmp_path,
        "repo-b",
        [
            {
                "direction": "inbound",
                "method": "POST",
                "path_status": "resolved",
                "label": "/search",
                "request_fields": ["sberProfileId", "@formulaLike"],
                "response_fields": ["status"],
            }
        ],
    )
    c = _write(tmp_path, "repo-c", [])
    return build_topology([a, b, c])


def _parse(text: str, delimiter: str = ",") -> list[dict[str, str]]:
    assert text.startswith("\ufeff")
    return list(csv.DictReader(io.StringIO(text.removeprefix("\ufeff")), delimiter=delimiter))


def test_csv_contains_topology_islands_repositories_edges_attributes_and_diagnostics(tmp_path):
    topology = _topology(tmp_path)
    rows = _parse(render_topology_csv(topology))
    record_types = [row["record_type"] for row in rows]
    assert record_types.count("topology") == 1
    assert record_types.count("island") == 2
    assert record_types.count("repository") == 3
    assert record_types.count("edge") == 1
    assert record_types.count("attribute") == 3
    assert record_types.count("diagnostic") == 1
    assert record_types.count("matchability_summary") == 1
    assert record_types.count("matchability_reason") == 1
    assert record_types.count("repository_matchability") == 3

    attrs = {row["attribute_name"]: row for row in rows if row["record_type"] == "attribute"}
    assert attrs["sberProfileId"]["transport_role"] == "request"
    assert attrs["sberProfileId"]["source_repository_id"] == "repo-a"
    assert attrs["sberProfileId"]["target_repository_id"] == "repo-b"
    assert attrs["status"]["transport_role"] == "response"
    assert attrs["status"]["attribute_flow_source_repository_id"] == "repo-b"
    assert attrs["status"]["attribute_flow_target_repository_id"] == "repo-a"

    edge = next(row for row in rows if row["record_type"] == "edge")
    assert edge["protocol"] == "http"
    assert edge["method"] == "POST"
    assert edge["matched_identity"] == "/search"
    assert edge["match_classification"] == "exact"
    assert json.loads(edge["source_half_wires_json"])[0]["repository_id"] == "repo-a"

    isolated = next(row for row in rows if row["record_type"] == "repository" and row["repository_id"] == "repo-c")
    assert isolated["island_id"]
    assert json.loads(isolated["island_repository_ids_json"]) == ["repo-c"]

    diagnostic = next(row for row in rows if row["record_type"] == "diagnostic")
    assert diagnostic["diagnostic_kind"] == "unmatched_half_wire"
    assert diagnostic["diagnostic_reason"] == "http_outbound_identity_not_matchable"
    assert diagnostic["diagnostic_repository_id"] == "repo-a"
    matchability_reason = next(row for row in rows if row["record_type"] == "matchability_reason")
    assert matchability_reason["matchability_reason"] == "http_outbound_identity_not_matchable"
    assert matchability_reason["matchability_count"] == "1"


def test_csv_is_deterministic_and_excel_safe_without_losing_original_json(tmp_path):
    topology = _topology(tmp_path)
    first = render_topology_csv(topology)
    second = render_topology_csv(topology)
    assert first == second
    rows = _parse(first)
    formula_row = next(row for row in rows if row["record_type"] == "attribute" and "formulaLike" in row["attribute_name"])
    assert formula_row["attribute_name"] == "'@formulaLike"
    record = json.loads(formula_row["record_json"])
    assert record["attribute_name"] == "@formulaLike"


def test_csv_supports_semicolon_for_excel_locales(tmp_path):
    topology = _topology(tmp_path)
    rows = _parse(render_topology_csv(topology, delimiter="semicolon"), delimiter=";")
    assert any(row["record_type"] == "edge" for row in rows)


def test_csv_cli(tmp_path):
    topology = _topology(tmp_path)
    topology_path = tmp_path / "topology.json"
    output_path = tmp_path / "topology.csv"
    topology_path.write_text(json.dumps(topology), encoding="utf-8")
    assert main(["csv", "--topology", str(topology_path), "--output", str(output_path), "--delimiter", "semicolon"]) == 0
    rows = _parse(output_path.read_text(encoding="utf-8"), delimiter=";")
    assert any(row["record_type"] == "attribute" and "sberProfileId" in row["attribute_name"] for row in rows)


def test_csv_rejects_wrong_topology_format():
    with pytest.raises(ValueError, match="repository-topology/v3"):
        render_topology_csv({"format": "repository-topology/v1"})
