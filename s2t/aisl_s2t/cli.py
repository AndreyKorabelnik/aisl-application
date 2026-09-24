from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from .builder import build_deterministic_s2t, write_build_outputs
from .environment import (
    EnvironmentEvidenceIndex,
    EnvironmentPolicy,
    collapse_semantic_decisions,
    resolve_environment_gap,
)
from .revision_source import RevisionSourceError, load_revision_inputs


def _audit_path(csv_path: str | Path) -> Path:
    path = Path(csv_path)
    if path.suffix:
        return path.with_suffix(".audit.json")
    return path.with_name(path.name + ".audit.json")


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rows(payload: Any, *keys: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _attach_audit_sections(
    path: Path,
    *,
    retrieval: Mapping[str, object],
    environment: Mapping[str, object] | None,
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["retrieval"] = dict(retrieval)
    if environment is not None:
        payload["environment"] = dict(environment)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_environment(
    mapping_gaps: Sequence[Mapping[str, Any]],
    *,
    policy_path: str | None,
    observations_path: str | None,
    explicit_environment: str | None,
) -> tuple[list[Mapping[str, Any]], dict[str, object] | None]:
    if not policy_path and not observations_path:
        if explicit_environment:
            raise ValueError("--environment requires --environment-policy and --environment-observations")
        return [], None
    if not policy_path or not observations_path:
        raise ValueError("--environment-policy and --environment-observations must be supplied together")

    policy_raw = _load_json(policy_path)
    if not isinstance(policy_raw, Mapping):
        raise ValueError("environment policy must be a JSON object")
    observations = _rows(_load_json(observations_path), "observations", "rows")
    if not observations:
        raise ValueError("environment observations must contain at least one observation")

    policy = EnvironmentPolicy(
        environment_scopes=policy_raw.get("environment_scopes") or {},
        default_environment=str(policy_raw.get("default_environment") or "production"),
        explicit_environment=explicit_environment,
    )
    if not policy.selected_environment:
        raise ValueError("selected environment must not be empty")
    if not policy.selected_scopes:
        raise ValueError(
            f"environment {policy.selected_environment!r} has no configured scopes"
        )

    index = EnvironmentEvidenceIndex.from_observations(observations)
    candidate_gaps = [
        gap
        for gap in mapping_gaps
        if isinstance(gap.get("evidence"), Mapping)
        and bool((gap.get("evidence") or {}).get("placeholder_resolution"))
    ]
    decisions = [
        resolve_environment_gap(gap, index=index, policy=policy)
        for gap in candidate_gaps
    ]
    semantic = collapse_semantic_decisions(decisions)
    audit = {
        "schema_version": "aisl_s2t_environment_resolution/v1",
        "default_environment": policy.default_environment,
        "explicit_environment": policy.explicit_environment,
        "selected_environment": policy.selected_environment,
        "selected_scopes": sorted(policy.selected_scopes),
        "counts": {
            "candidate_gap_rows": len(decisions),
            "resolved_gap_rows": sum(1 for item in decisions if item.status == "resolved"),
            "semantic_decisions": len(semantic),
            "resolved_semantic_decisions": sum(
                1 for item in semantic if item.get("status") == "resolved"
            ),
            "ambiguous_semantic_decisions": sum(
                1 for item in semantic if item.get("status") == "ambiguous"
            ),
            "unresolved_semantic_decisions": sum(
                1 for item in semantic if item.get("status") == "unresolved"
            ),
        },
    }
    return semantic, audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aisl-s2t",
        description="Build deterministic S2T from one exact published AISL revision.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build S2T from a pinned AISL revision")
    build.add_argument("--system-id", required=True)
    build.add_argument("--revision-id", required=True)
    build.add_argument("--output", required=True, help="Output CSV path")
    build.add_argument(
        "--environment-policy",
        help="Consumer-owned JSON policy mapping environment roles to observed scope identities",
    )
    build.add_argument(
        "--environment-observations",
        help="JSON observations mapping placeholder/value pairs to observed scope identities",
    )
    build.add_argument(
        "--environment",
        help="Optional environment role override; defaults to policy default_environment (production by default)",
    )
    args = parser.parse_args(argv)

    if args.command != "build":
        parser.error("unsupported command")

    try:
        inputs = load_revision_inputs(
            system_id=args.system_id,
            revision_id=args.revision_id,
        )
        environment_resolutions, environment_audit = _resolve_environment(
            inputs.mapping_gaps,
            policy_path=args.environment_policy,
            observations_path=args.environment_observations,
            explicit_environment=args.environment,
        )
        result = build_deterministic_s2t(
            inputs.mapping_rows,
            mapping_gaps=inputs.mapping_gaps,
            environment_resolutions=environment_resolutions,
            target_fields=inputs.target_fields,
        )
        output = Path(args.output)
        audit = _audit_path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_build_outputs(
            result,
            csv_path=output,
            audit_path=audit,
            system_id=args.system_id,
            revision_id=args.revision_id,
        )
        _attach_audit_sections(
            audit,
            retrieval=inputs.retrieval,
            environment=environment_audit,
        )
    except (RevisionSourceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"S2T: {output}")
    print(f"Audit: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
