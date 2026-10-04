from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RevisionBinding:
    system_id: str
    revision_id: str

    def __post_init__(self) -> None:
        if not self.system_id.strip():
            raise ValueError("system_id must not be empty")
        if not self.revision_id.strip():
            raise ValueError("revision_id must not be empty")
