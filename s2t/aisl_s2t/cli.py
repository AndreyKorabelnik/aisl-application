from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .builder import build_deterministic_s2t, write_build_outputs
from .primary_source import collapse_primary_sources
from .environment import (
    EnvironmentEvidenceIndex,
    EnvironmentPolicy,
    collapse_semantic_decisions,
    resolve_environment_gap,
)


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rows(payload: Any, *keys: str) -> list[Mapping[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _semantic_environment(payload: Any) -> list[Mapping[str, Any]]:
    return _rows(payload, "semantic_decisions")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aisl-s2t")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve-environment")
    resolve.add_argument("--gaps", required=True)
    resolve.add_argument("--environment-observations", required=True)
    resolve.add_argument("--policy", required=True)
    resolve.add_argument("--environment")
    resolve.add_argument("--output", required=True)

    primary = sub.add_parser("collapse-primary-sources")
    primary.add_argument("--mappings", required=True)
    primary.add_argument("--environment-resolution", required=True)
    primary.add_argument("--output", required=True)

    build = sub.add_parser("build-deterministic")
    build.add_argument("--mappings", required=True)
    build.add_argument("--mapping-gaps")
    build.add_argument("--environment-resolution")
    build.add_argument("--target-fields")
    build.add_argument("--column-usage-contexts")
    build.add_argument("--system-id", default="")
    build.add_argument("--revision-id", default="")
    build.add_argument("--csv-output", required=True)
    build.add_argument("--audit-output", required=True)

    args = parser.parse_args(argv)

    if args.command == "resolve-environment":
        gaps = _rows(_load(args.gaps), "gaps", "rows")
        observations = _rows(_load(args.environment_observations), "observations", "rows")
        policy_raw = _load(args.policy)
        policy = EnvironmentPolicy(
            environment_scopes=policy_raw.get("environment_scopes") or {},
            default_environment=str(policy_raw.get("default_environment") or "production"),
            explicit_environment=args.environment,
        )
        index = EnvironmentEvidenceIndex.from_observations(observations)
        decisions = [resolve_environment_gap(item, index=index, policy=policy) for item in gaps]
        semantic = collapse_semantic_decisions(decisions)
        payload = {
            "schema_version": "aisl_s2t_environment_resolution/v1",
            "policy": {
                "default_environment": policy.default_environment,
                "explicit_environment": policy.explicit_environment,
                "selected_environment": policy.selected_environment,
                "selected_scopes": sorted(policy.selected_scopes),
            },
            "counts": {
                "gap_rows": len(decisions),
                "resolved_gap_rows": sum(1 for item in decisions if item.status == "resolved"),
                "semantic_decisions": len(semantic),
                "resolved_semantic_decisions": sum(1 for item in semantic if item["status"] == "resolved"),
                "ambiguous_semantic_decisions": sum(1 for item in semantic if item["status"] == "ambiguous"),
                "unresolved_semantic_decisions": sum(1 for item in semantic if item["status"] == "unresolved"),
            },
            "decisions": [item.to_dict() for item in decisions],
            "semantic_decisions": semantic,
        }
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.command == "collapse-primary-sources":
        mappings = _rows(_load(args.mappings), "mappings", "rows", "sql_target_source_mapping")
        environment_payload = _load(args.environment_resolution)
        semantic = _semantic_environment(environment_payload)
        decisions = collapse_primary_sources(mappings, environment_resolutions=semantic)
        payload = {
            "schema_version": "aisl_s2t_primary_source_resolution/v1",
            "counts": {
                "mapping_rows": len(mappings),
                "primary_source_decisions": len(decisions),
                "resolved_primary_source_decisions": sum(1 for item in decisions if item.status == "resolved"),
                "ambiguous_primary_source_decisions": sum(1 for item in decisions if item.status == "ambiguous"),
                "unresolved_primary_source_decisions": sum(1 for item in decisions if item.status == "unresolved"),
            },
            "decisions": [item.to_dict() for item in decisions],
        }
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    mappings = _rows(_load(args.mappings), "mappings", "rows", "sql_target_source_mapping")
    mapping_gaps = _rows(
        _load(args.mapping_gaps) if args.mapping_gaps else [],
        "gaps", "rows", "sql_target_source_mapping_gap",
    )
    environment_payload = _load(args.environment_resolution) if args.environment_resolution else []
    semantic = _semantic_environment(environment_payload)
    target_fields = _rows(_load(args.target_fields) if args.target_fields else [], "targets", "target_fields", "rows")
    column_usage_contexts = _rows(
        _load(args.column_usage_contexts) if args.column_usage_contexts else [],
        "contexts", "column_usage_contexts", "rows",
    )
    result = build_deterministic_s2t(
        mappings,
        mapping_gaps=mapping_gaps,
        environment_resolutions=semantic,
        target_fields=target_fields,
        column_usage_contexts=column_usage_contexts,
    )
    write_build_outputs(
        result,
        csv_path=args.csv_output,
        audit_path=args.audit_output,
        system_id=args.system_id,
        revision_id=args.revision_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
