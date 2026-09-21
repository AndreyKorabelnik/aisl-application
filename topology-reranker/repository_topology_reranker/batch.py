from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .adapter import AdapterIdentity, RerankAdapter
from .contracts import NON_CANONICAL_CLASSIFICATION, RERANK_PACKAGE_FORMAT, SEMANTIC_SHORTLIST_FORMAT
from .runner import rerank_package
from .validation import PackageValidationError, validate_package


RUN_MANIFEST_FORMAT = "repository-topology-rerank-run/v1"
TERMINAL_STATUSES = {"VALIDATED", "PROVIDER_ERROR", "INVALID_RESPONSE"}


class BatchInputError(ValueError):
    pass


class ResumeStateError(ValueError):
    pass


def packages_from_document(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, Mapping):
        if str(document.get("format") or "") == RERANK_PACKAGE_FORMAT:
            rows = [document]
        elif "packages" in document:
            rows = document.get("packages")
        else:
            raise BatchInputError("input object must be one rerank package or contain packages")
    elif isinstance(document, Sequence) and not isinstance(document, (str, bytes)):
        rows = document
    else:
        raise BatchInputError("input must be a rerank package, package array, or PR-A envelope")

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise BatchInputError("packages must be an array")

    result: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_cases: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise BatchInputError("each package must be an object")
        normalized = validate_package(row)
        package_hash = str(normalized["package_hash"])
        case_id = str(normalized["case"]["case_id"])
        if package_hash in seen_hashes or case_id in seen_cases:
            raise BatchInputError("duplicate package_hash or case_id in batch")
        seen_hashes.add(package_hash)
        seen_cases.add(case_id)
        result.append(normalized)
    return result


def load_packages(path: str | Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchInputError(f"cannot read package document: {exc}") from exc
    return packages_from_document(document)


def _result_path(output_dir: Path, package_hash: str) -> Path:
    return output_dir / f"{package_hash}.json"


def _load_terminal_result(path: Path, package: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResumeStateError(f"cannot read existing result {path.name}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ResumeStateError(f"existing result {path.name} is not an object")
    expected = {
        "format": SEMANTIC_SHORTLIST_FORMAT,
        "classification": NON_CANONICAL_CLASSIFICATION,
        "package_hash": str(package["package_hash"]),
        "case_id": str(package["case"]["case_id"]),
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ResumeStateError(f"existing result {path.name} does not match {key}")
    if str(value.get("status") or "") not in TERMINAL_STATUSES:
        raise ResumeStateError(f"existing result {path.name} is not terminal")
    return dict(value)


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def rerank_batch(
    packages: Iterable[Mapping[str, Any]],
    *,
    output_dir: str | Path,
    adapter: RerankAdapter,
    identity: AdapterIdentity,
) -> dict[str, Any]:
    # Validate the complete batch before the first provider call so malformed input
    # cannot leave a partially executed semantic run.
    normalized = packages_from_document(list(packages))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    invoked_count = 0
    resumed_count = 0
    results: list[dict[str, Any]] = []
    for package in normalized:
        path = _result_path(destination, str(package["package_hash"]))
        if path.exists():
            artifact = _load_terminal_result(path, package)
            resumed_count += 1
        else:
            artifact = rerank_package(package, adapter=adapter, identity=identity)
            _write_json_atomic(path, artifact)
            invoked_count += 1
        results.append(
            {
                "package_hash": str(package["package_hash"]),
                "case_id": str(package["case"]["case_id"]),
                "status": str(artifact["status"]),
                "result_file": path.name,
            }
        )

    status_counts = Counter(row["status"] for row in results)
    manifest = {
        "format": RUN_MANIFEST_FORMAT,
        "package_count": len(normalized),
        "adapter_invocation_count": invoked_count,
        "resumed_count": resumed_count,
        "status_counts": dict(sorted(status_counts.items())),
        "results": results,
        "adapter": identity.to_dict(),
    }
    _write_json_atomic(destination / "run-manifest.json", manifest)
    return manifest
