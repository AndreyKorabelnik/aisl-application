import json
from pathlib import Path

import pytest

from repository_topology.cli import main
from repository_topology.reader import InventoryInputError, discover_reduced_inventory_paths


def _write_reduced(path: Path, repo: str, direction: str) -> None:
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
                    "path_status": "resolved",
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
                "family_label": "/x",
                "string_facets": [],
            },
        }],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_directory_mode_discovers_nested_canonical_reduced_files_only(tmp_path):
    root = tmp_path / "inventories"
    a = root / "team-a" / "repo-a" / "repository_inventory_reduced.json"
    b = root / "team-b" / "repo-b" / "repository_inventory_reduced.json"
    _write_reduced(a, "a", "outbound")
    _write_reduced(b, "b", "inbound")

    # Unrelated JSON and a Full Inventory-shaped file are intentionally ignored
    # because directory mode only discovers the canonical Reduced filename.
    (root / "notes.json").write_text("{}", encoding="utf-8")
    (root / "repo-c").mkdir()
    (root / "repo-c" / "repository_inventory.json").write_text(
        json.dumps({"format": "repository-inventory/v7"}), encoding="utf-8"
    )

    assert discover_reduced_inventory_paths(root) == [a, b]

    output = tmp_path / "out" / "repository_topology.json"
    assert main(["build-directory", "--inventories", str(root), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["repository_count"] == 2
    assert payload["summary"]["edge_count"] == 1
    assert payload["summary"]["exact_edge_count"] == 1
    assert payload["summary"]["probable_edge_count"] == 0
    assert payload["summary"]["island_count"] == 1
    assert payload["summary"]["half_wire_count"] == 2
    assert payload["summary"]["matched_half_wire_count"] == 2


def test_directory_mode_requires_directory(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(InventoryInputError, match="does not exist"):
        discover_reduced_inventory_paths(missing)

    file_path = tmp_path / "not-a-directory"
    file_path.write_text("{}", encoding="utf-8")
    with pytest.raises(InventoryInputError, match="not a directory"):
        discover_reduced_inventory_paths(file_path)


def test_directory_mode_requires_at_least_two_reduced_artifacts(tmp_path):
    root = tmp_path / "inventories"
    _write_reduced(root / "repo-a" / "repository_inventory_reduced.json", "a", "outbound")
    with pytest.raises(InventoryInputError, match="at least two"):
        discover_reduced_inventory_paths(root)
