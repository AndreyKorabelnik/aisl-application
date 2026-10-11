#!/usr/bin/env python3
"""Reproducible, dependency-free static release archive for AISL Attribute Lineage Explorer.

Usage: python3 tools/build_clean_delivery.py --output /path/to/release.zip
Only allowlisted application assets/docs are packaged. No npm install, CDN, or server runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

PROJECT = Path(__file__).resolve().parents[1]
ASSETS = (
    "index.html",
    "styles.css",
    "app.mjs",
    "graph-core.mjs",
    "demo-data.mjs",
    "INSTALL_RU.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "demo/lineage.json",
    "demo/lineage-all-edges.json",
)
STABLE_DATE = (2020, 1, 1, 0, 0, 0)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical_json(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def zip_entry(name: str, data: bytes) -> tuple[ZipInfo, bytes]:
    entry = ZipInfo(name, STABLE_DATE)
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    entry.compress_type = ZIP_DEFLATED
    return entry, data


def build(output: Path) -> dict:
    payload: dict[str, bytes] = {}
    for name in ASSETS:
        source = PROJECT / name
        if source.is_symlink() or not source.is_file() or source.resolve().parent != (PROJECT / name).parent.resolve():
            raise ValueError(f"Invalid or missing source asset: {name}")
        data = source.read_bytes()
        if not data:
            raise ValueError(f"Empty source asset: {name}")
        payload[name] = data
    for marker in (b"https://fonts.googleapis.com", b"https://cdn.", b"<script src=\"http"):
        if any(marker in payload[x] for x in ("index.html", "app.mjs", "styles.css")):
            raise ValueError(f"External runtime asset reference prohibited: {marker!r}")
    manifest = {
        "format": "aisl-attribute-lineage-explorer-static/v1",
        "app": "AISL Attribute Lineage Explorer",
        "runtime": "static-browser-only",
        "assets": {
            name: {"sha256": digest(data), "size": len(data)}
            for name, data in sorted(payload.items())
        },
    }
    payload["SHA256SUMS.json"] = canonical_json(manifest)
    output = output.expanduser().resolve()
    if output.is_relative_to(PROJECT):
        raise ValueError("Output archive must be outside the source module")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with ZipFile(temporary, "w", compresslevel=9) as bundle:
            for name, data in sorted(payload.items()):
                zi, buf = zip_entry(name, data)
                bundle.writestr(zi, buf, compress_type=ZIP_DEFLATED, compresslevel=9)
        with ZipFile(temporary, "r") as verify:
            actual = verify.namelist()
            assert actual == sorted(payload), "Unexpected/duplicate ZIP entries"
            for name, expected in payload.items():
                assert verify.read(name) == expected, f"Archive content differs: {name}"
            parsed = json.loads(verify.read("SHA256SUMS.json"))
            assert parsed == manifest
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"archive": str(output), "sha256": digest(output.read_bytes()), "size": output.stat().st_size, "assets": len(payload), "manifest": manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Destination ZIP (outside module)")
    args = parser.parse_args()
    result = build(args.output)
    print(canonical_json({k: v for k, v in result.items() if k != "manifest"}).decode(), end="")


if __name__ == "__main__":
    main()
