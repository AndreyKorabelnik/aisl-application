from __future__ import annotations

from dataclasses import dataclass

from aisl_ucp_tsa_replica_er.contracts import RevisionBinding
from aisl_ucp_tsa_replica_er.gateway import KnowledgeApiGateway


@dataclass
class Product:
    artifact_id: str = "tsa-map"
    model_kind: str = "logical-physical-mapping-evidence"


class Revision:
    def list_products(self, *, capability: str):
        assert capability == "common.observed-record-set"
        return [Product()]


class Client:
    def __init__(self):
        self.calls = []

    def revision(self, system_id: str, revision_id: str):
        assert (system_id, revision_id) == ("tsa", "rev-t")
        return Revision()

    def get_json(self, path: str, *, params: dict):
        self.calls.append((path, dict(params)))
        if path.endswith("/data-model/declared-dataset"):
            return {
                "record_kinds": [
                    {"record_kind": "type", "available": True, "fields": ["type_occurrence_id", "fully_qualified_name", "simple_name"]},
                    {"record_kind": "field", "available": True, "fields": ["field_occurrence_id", "owner_type_occurrence_id", "name", "declared_type_expression"]},
                    {"record_kind": "effective_field", "available": True, "fields": ["effective_field_occurrence_id", "effective_owner_type_occurrence_id", "field_name"]},
                    {"record_kind": "relationship", "available": True, "fields": ["relationship_occurrence_id", "source_type_occurrence_id", "target_type_occurrence_id", "field_occurrence_id"]},
                    {"record_kind": "annotation", "available": True, "fields": ["annotation_occurrence_id", "target_kind", "target_occurrence_id", "annotation_name"]},
                ]
            }
        if "/declared-dataset/" in path:
            kind = path.rsplit("/", 1)[-1]
            offset = params["offset"]
            if kind == "type" and offset == 0:
                return {"items": [{"type_occurrence_id": str(i), "fully_qualified_name": f"X{i}", "simple_name": f"X{i}"} for i in range(500)]}
            if kind == "type" and offset == 500:
                return {"items": [{"type_occurrence_id": "500", "fully_qualified_name": "X500", "simple_name": "X500"}]}
            return {"items": []}
        if "/observed-records/tsa-map" in path:
            kind = params["item_kind"]
            if kind == "entity_mapping":
                return {"items": [{"item_kind": kind, "payload": {"mapping_status": "observed_exact"}}]}
            return {"items": []}
        raise AssertionError(path)

    def close(self):
        pass


def _gateway(client: Client) -> KnowledgeApiGateway:
    gateway = KnowledgeApiGateway.__new__(KnowledgeApiGateway)
    gateway._client = client
    return gateway


def test_declared_dataset_is_discovered_by_shape_and_paginated() -> None:
    client = Client()
    result = _gateway(client).load_ucp_dataset(RevisionBinding("ucp", "rev-u"))
    assert len(result["types"]) == 501
    assert set(result) == {"types", "fields", "effective_fields", "relationships", "annotations"}
    type_calls = [params for path, params in client.calls if path.endswith("/declared-dataset/type")]
    assert [call["offset"] for call in type_calls] == [0, 500]



def test_canonical_record_kind_wins_over_broader_shape_match() -> None:
    client = Client()
    original = client.get_json

    seen_paths: list[str] = []

    def with_candidate_member(path: str, *, params: dict):
        seen_paths.append(path)
        if path.endswith("/declared-dataset/types"):
            offset = params["offset"]
            if offset == 0:
                return {"items": [{"type_occurrence_id": str(i), "fully_qualified_name": f"X{i}", "simple_name": f"X{i}"} for i in range(500)]}
            if offset == 500:
                return {"items": [{"type_occurrence_id": "500", "fully_qualified_name": "X500", "simple_name": "X500"}]}
            return {"items": []}
        payload = original(path, params=params)
        if path.endswith("/data-model/declared-dataset"):
            payload["record_kinds"][0]["record_kind"] = "types"
            payload["record_kinds"].append({
                "record_kind": "candidate_members",
                "available": True,
                "fields": [
                    "type_occurrence_id", "fully_qualified_name", "simple_name",
                    "candidate_id", "source_occurrence_id",
                ],
            })
        return payload

    client.get_json = with_candidate_member
    result = _gateway(client).load_ucp_dataset(RevisionBinding("ucp", "rev-u"))
    assert len(result["types"]) == 501
    type_paths = [path for path in seen_paths if "/declared-dataset/" in path]
    assert any(path.endswith("/types") for path in type_paths)
    assert not any(path.endswith("/candidate_members") for path in type_paths)

def test_declared_dataset_shape_must_be_unique() -> None:
    client = Client()
    original = client.get_json

    def duplicate(path: str, *, params: dict):
        payload = original(path, params=params)
        if path.endswith("/data-model/declared-dataset"):
            payload["record_kinds"].append({
                "record_kind": "another_type", "available": True,
                "fields": ["type_occurrence_id", "fully_qualified_name", "simple_name", "extra"],
            })
        return payload

    client.get_json = duplicate
    try:
        _gateway(client).load_ucp_dataset(RevisionBinding("ucp", "rev-u"))
    except RuntimeError as exc:
        assert "exactly one shape match for types" in str(exc)
    else:
        raise AssertionError("expected ambiguous record-kind failure")


def test_tsa_observed_product_is_public_and_paginated_by_kind() -> None:
    client = Client()
    result = _gateway(client).load_tsa_mappings(RevisionBinding("tsa", "rev-t"))
    assert len(result["entity_mappings"]) == 1
    assert result["field_mappings"] == []
    observed = [(path, params["item_kind"]) for path, params in client.calls if "/observed-records/" in path]
    assert observed == [
        ("/api/knowledge/v1/systems/tsa/observed-records/tsa-map", "entity_mapping"),
        ("/api/knowledge/v1/systems/tsa/observed-records/tsa-map", "field_mapping"),
    ]
