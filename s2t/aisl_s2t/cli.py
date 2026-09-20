from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .primary_source import collapse_primary_sources

from .environment import (
    EnvironmentEvidenceIndex,
    EnvironmentPolicy,
    collapse_semantic_decisions,
    resolve_environment_gap,
)


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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

    args = parser.parse_args(argv)

    if args.command == "resolve-environment":
        gaps = _load(args.gaps)
        observations = _load(args.environment_observations)
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
    else:
        mappings = _load(args.mappings)
        environment_payload = _load(args.environment_resolution)
        semantic = (
            environment_payload.get("semantic_decisions")
            if isinstance(environment_payload, dict)
            else environment_payload
        ) or []
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


if __name__ == "__main__":
    raise SystemExit(main())
