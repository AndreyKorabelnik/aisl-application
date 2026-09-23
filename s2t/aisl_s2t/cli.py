from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .builder import build_deterministic_s2t, write_build_outputs
from .revision_source import RevisionSourceError, load_revision_inputs


def _audit_path(csv_path: str | Path) -> Path:
    path = Path(csv_path)
    if path.suffix:
        return path.with_suffix(".audit.json")
    return path.with_name(path.name + ".audit.json")


def _attach_retrieval_audit(path: Path, retrieval: dict[str, object]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["retrieval"] = retrieval
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    args = parser.parse_args(argv)

    if args.command != "build":  # argparse owns command validation.
        parser.error("unsupported command")

    try:
        inputs = load_revision_inputs(
            system_id=args.system_id,
            revision_id=args.revision_id,
        )
        result = build_deterministic_s2t(
            inputs.mapping_rows,
            mapping_gaps=inputs.mapping_gaps,
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
        _attach_retrieval_audit(audit, inputs.retrieval)
    except RevisionSourceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"S2T: {output}")
    print(f"Audit: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
