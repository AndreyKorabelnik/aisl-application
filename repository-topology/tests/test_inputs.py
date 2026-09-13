import json
import pytest
from repository_topology.builder import build_topology
from repository_topology.reader import InventoryInputError


def test_rejects_full_inventory(tmp_path):
    a=tmp_path/'a.json'; b=tmp_path/'b.json'
    a.write_text(json.dumps({"format":"repository-inventory/v7"}))
    b.write_text(json.dumps({"format":"repository-inventory/v7"}))
    with pytest.raises(InventoryInputError):
        build_topology([a,b])


def test_requires_two_inputs(tmp_path):
    with pytest.raises(ValueError):
        build_topology([])
