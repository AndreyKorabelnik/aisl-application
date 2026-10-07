from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


@dataclass(frozen=True, slots=True)
class CrossingUcpEvidence:
    """Mechanically grounded CPC crossing attribute -> canonical UCP semantic endpoint."""

    crossing_attribute: str
    classification: str
    ucp_semantic_path: str
    endpoint_key: str
    provenance_json: str = ""

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "CrossingUcpEvidence":
        return cls(
            crossing_attribute=_text(row.get("crossing_attribute"), "crossing_attribute"),
            classification=_text(row.get("classification"), "classification"),
            ucp_semantic_path=_text(row.get("ucp_semantic_path"), "ucp_semantic_path"),
            endpoint_key=_text(row.get("endpoint_key"), "endpoint_key"),
            provenance_json=str(row.get("ucp_resolution_provenance_json") or row.get("provenance_json") or "").strip(),
        )

    @property
    def source_type_fqcn(self) -> str:
        owner, sep, _field = self.endpoint_key.rpartition(".")
        if not sep or not owner:
            raise ValueError(f"endpoint_key must be '<type_fqcn>.<field>': {self.endpoint_key!r}")
        return owner

    @property
    def source_field(self) -> str:
        _owner, sep, field = self.endpoint_key.rpartition(".")
        if not sep or not field:
            raise ValueError(f"endpoint_key must be '<type_fqcn>.<field>': {self.endpoint_key!r}")
        return field


@dataclass(frozen=True, slots=True)
class KpkUcpEvidence:
    """Final KPK consumer endpoint bound to the CPC crossing and UCP semantic endpoint."""

    kpk_service: str
    kpk_interaction: str
    kpk_attribute: str
    kpk_output_root: str
    crossing_attribute: str
    interaction_consumer_attribute: str
    classification: str
    ucp_semantic_path: str
    endpoint_key: str
    kpk_gap: str = ""
    interaction_gap: str = ""
    interaction_full_attribute_path: str = ""
    provenance_json: str = ""
    interaction_provenance_json: str = ""

    @property
    def source_type_fqcn(self) -> str:
        owner, sep, _field = self.endpoint_key.rpartition(".")
        if not sep or not owner:
            raise ValueError(f"endpoint_key must be '<type_fqcn>.<field>': {self.endpoint_key!r}")
        return owner

    @property
    def source_field(self) -> str:
        _owner, sep, field = self.endpoint_key.rpartition(".")
        if not sep or not field:
            raise ValueError(f"endpoint_key must be '<type_fqcn>.<field>': {self.endpoint_key!r}")
        return field
