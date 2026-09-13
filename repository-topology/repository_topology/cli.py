from __future__ import annotations

import argparse
import json
from pathlib import Path

from .attribute_path import find_attribute_paths
from .builder import build_topology
from .csv_export import render_topology_csv
from .mermaid import render_attribute_path_mermaid, render_repository_mermaid
from .reader import discover_reduced_inventory_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repository-topology")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build repository topology from Reduced Inventory artifacts")
    build.add_argument("--inventory", action="append", required=True, type=Path, help="repository-inventory-reduced/v3 JSON; repeat for each repository")
    build.add_argument("--output", required=True, type=Path)

    build_directory = sub.add_parser(
        "build-directory",
        help="Build repository topology from recursively discovered Reduced Inventory artifacts",
    )
    build_directory.add_argument(
        "--inventories",
        required=True,
        type=Path,
        help="directory recursively containing repository_inventory_reduced.json artifacts",
    )
    build_directory.add_argument("--output", required=True, type=Path)

    csv_export = sub.add_parser("csv", help="Export repository-topology/v3 as an Excel-friendly long-form CSV")
    csv_export.add_argument("--topology", required=True, type=Path)
    csv_export.add_argument("--output", required=True, type=Path)
    csv_export.add_argument("--delimiter", choices=("comma", "semicolon", "tab"), default="comma")

    mermaid = sub.add_parser("mermaid", help="Render a Mermaid repository graph from repository-topology/v3")
    mermaid.add_argument("--topology", required=True, type=Path)
    mermaid.add_argument("--output", required=True, type=Path)

    attribute_path = sub.add_parser(
        "attribute-path",
        help="Find shortest exact-name-preserving attribute routes in repository-topology/v3",
    )
    attribute_path.add_argument("--topology", required=True, type=Path)
    attribute_path.add_argument("--attribute", required=True)
    attribute_path.add_argument("--from-repository")
    attribute_path.add_argument("--to-repository")
    attribute_path.add_argument("--output", required=True, type=Path)
    attribute_path.add_argument("--mermaid-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        payload = build_topology(args.inventory)
        _write_output(args.output, payload)
        return 0
    if args.command == "build-directory":
        payload = build_topology(discover_reduced_inventory_paths(args.inventories))
        _write_output(args.output, payload)
        return 0
    if args.command == "csv":
        payload = json.loads(args.topology.read_text(encoding="utf-8"))
        _write_text(args.output, render_topology_csv(payload, delimiter=args.delimiter))
        return 0
    if args.command == "mermaid":
        payload = json.loads(args.topology.read_text(encoding="utf-8"))
        _write_text(args.output, render_repository_mermaid(payload))
        return 0
    if args.command == "attribute-path":
        topology = json.loads(args.topology.read_text(encoding="utf-8"))
        result = find_attribute_paths(
            topology,
            attribute_name=args.attribute,
            source_repository_id=args.from_repository,
            target_repository_id=args.to_repository,
        )
        _write_output(args.output, result)
        if args.mermaid_output is not None:
            _write_text(args.mermaid_output, render_attribute_path_mermaid(result))
        return 0
    raise AssertionError(args.command)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_output(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
