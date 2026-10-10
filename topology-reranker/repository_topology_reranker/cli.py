from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .adapter import AdapterIdentity
from .batch import BatchInputError, ResumeStateError, load_packages, rerank_batch
from .external_command import ExternalCommandAdapter
from .validation import PackageValidationError
from .published_evidence import PublishedEvidenceError, rank_published_candidates, public_http_get_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repository-topology-reranker")
    sub = parser.add_subparsers(dest="command", required=True)
    rerank = sub.add_parser("rerank-batch", help="rerank frozen deterministic residual packages")
    rerank.add_argument("--packages", required=True)
    rerank.add_argument("--output-dir", required=True)
    rerank.add_argument("--adapter-executable", required=True)
    rerank.add_argument("--adapter-arg", action="append", default=[])
    rerank.add_argument("--provider", required=True)
    rerank.add_argument("--model", required=True)
    rerank.add_argument("--prompt-contract", default="repository-topology-rerank-prompt/v1")
    rerank.add_argument("--timeout-seconds", type=float)
    observed = sub.add_parser("shortlist-published", help="rank candidates by revision-pinned public AISL implementation evidence")
    observed.add_argument("--request", required=True)
    observed.add_argument("--base-url", required=True)
    observed.add_argument("--output", required=True)
    observed.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "shortlist-published":
        try:
            request = json.loads(Path(args.request).read_text(encoding="utf-8"))
            result = rank_published_candidates(
                request, get_knowledge_item=public_http_get_json(base_url=args.base_url, timeout_seconds=args.timeout_seconds)
            )
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except (OSError, ValueError, PublishedEvidenceError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"case_id": result["case_id"], "candidates": len(result["candidates"]), "selection_status": result["selection_status"]}, ensure_ascii=False))
        return 0
    if args.command != "rerank-batch":
        raise AssertionError(args.command)
    try:
        packages = load_packages(Path(args.packages))
        adapter = ExternalCommandAdapter(
            args.adapter_executable,
            args=args.adapter_arg,
            timeout_seconds=args.timeout_seconds,
        )
        identity = AdapterIdentity(
            provider=args.provider,
            model=args.model,
            prompt_contract=args.prompt_contract,
        )
        manifest = rerank_batch(
            packages,
            output_dir=Path(args.output_dir),
            adapter=adapter,
            identity=identity,
        )
    except (BatchInputError, ResumeStateError, PackageValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
