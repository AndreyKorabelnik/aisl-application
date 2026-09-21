from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class AdapterIdentity:
    provider: str
    model: str
    prompt_contract: str = "repository-topology-rerank-prompt/v1"

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_contract": self.prompt_contract,
        }


class RerankAdapter(Protocol):
    """Provider-neutral boundary for one frozen rerank package.

    Implementations may call any external model/provider, but they receive only the
    already-frozen package and return structured ranking data. Provider transport,
    retries and credentials are intentionally outside this package.
    """

    def rerank(self, package: Mapping[str, Any]) -> Mapping[str, Any]: ...
