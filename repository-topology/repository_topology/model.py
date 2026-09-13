from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HalfWire:
    repository_id: str
    input_index: int
    observed_identity_id: str
    exact_representation_ids: tuple[str, ...]
    representative_evidence_id: str
    direction: str
    protocol: str
    method: str | None
    path_status: str | None
    paths: tuple[str, ...]
    family_label: str
    occurrence_count: int
    transport_identity_kind: str | None
    request_payload: str | None
    request_field_names: tuple[str, ...]
    response_payload: str | None
    response_field_names: tuple[str, ...]
    payload_identity: str | None
    payload_field_names: tuple[str, ...]

    def public_ref(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "observed_identity_id": self.observed_identity_id,
            "exact_representation_ids": list(self.exact_representation_ids),
            "representative_evidence_id": self.representative_evidence_id,
            "direction": self.direction,
            "protocol": self.protocol,
            "method": self.method,
            "identity_status": self.path_status,
            "identities": list(self.paths),
            "transport_identity_kind": self.transport_identity_kind,
            "occurrence_count": self.occurrence_count,
            "request_payload": self.request_payload,
            "request_field_names": list(self.request_field_names),
            "response_payload": self.response_payload,
            "response_field_names": list(self.response_field_names),
            "payload_identity": self.payload_identity,
            "payload_field_names": list(self.payload_field_names),
        }
