from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExternalCommandAdapter:
    """Provider-neutral adapter that exchanges one JSON object over stdin/stdout."""

    executable: str
    args: tuple[str, ...] = ()
    timeout_seconds: float | None = None

    def __init__(
        self,
        executable: str,
        args: Sequence[str] = (),
        timeout_seconds: float | None = None,
    ) -> None:
        if not str(executable):
            raise ValueError("adapter executable is required")
        object.__setattr__(self, "executable", str(executable))
        object.__setattr__(self, "args", tuple(str(value) for value in args))
        object.__setattr__(self, "timeout_seconds", timeout_seconds)

    def rerank(self, package: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = json.dumps(package, ensure_ascii=False, separators=(",", ":"))
        completed = subprocess.run(
            [self.executable, *self.args],
            input=payload,
            text=True,
            capture_output=True,
            shell=False,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "adapter command failed"
            raise RuntimeError(
                f"adapter command exited with {completed.returncode}: {message[:1000]}"
            )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("adapter stdout is not one JSON object") from exc
        if not isinstance(response, Mapping):
            raise ValueError("adapter stdout JSON must be an object")
        return response
