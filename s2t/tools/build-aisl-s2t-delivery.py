#!/usr/bin/env python3
"""Build the reproducible AISL S2T clean delivery.

The delivery contains one first-party wheel (aisl-s2t) plus manifests/checksums.
Third-party dependencies are never vendored; pip resolves them from the configured
package index during installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

DELIVERY_NAME = "aisl-s2t"
FIRST_PARTY_COMPONENTS = ("aisl-s2t",)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FORBIDDEN = {"src", "tests", "test", "build", ".egg-info", "__pycache__", ".pytest_cache", "node_modules"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_name(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def normalize_zip(path: Path) -> None:
    rows = []
    with zipfile.ZipFile(path) as src:
        for info in src.infolist():
            rows.append((info.filename, src.read(info.filename), info.external_attr))
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
        for name, body, attrs in sorted(rows):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = attrs or (0o644 << 16)
            dst.writestr(info, body)
    tmp.replace(path)


def build_wheel(source: Path, work: Path) -> Path:
    stage = work / "stage"
    shutil.copytree(
        source,
        stage,
        ignore=shutil.ignore_patterns(
            ".git", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache", "tests", "tools"
        ),
    )
    wheels = work / "wheels"
    wheels.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheels), str(stage)],
        check=True,
    )
    built = sorted(wheels.glob("*.whl"))
    if len(built) != 1:
        raise SystemExit(f"expected exactly one wheel, got {[p.name for p in built]}")
    normalize_zip(built[0])
    return built[0]


def wheel_row(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as zf:
        metadata = [name for name in zf.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise SystemExit("wheel must contain exactly one METADATA")
        parsed = Parser().parsestr(zf.read(metadata[0]).decode("utf-8"))
    row = {
        "file": f"wheels/{path.name}",
        "name": parsed["Name"],
        "version": parsed["Version"],
        "requires": parsed.get_all("Requires-Dist", []),
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }
    if (normalize_name(str(row["name"])),) != FIRST_PARTY_COMPONENTS:
        raise SystemExit(f"unexpected first-party component: {row['name']}")
    return row


def resolve_git_identity(source: Path, commit: str | None, tree: str | None) -> tuple[str, str]:
    if commit and tree:
        return commit, tree
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
        tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("pass --source-commit and --source-tree outside a Git checkout") from exc
    return commit, tree


def delivery_zip_name(version: str, commit: str) -> str:
    return f"aisl-s2t-clean-{version}-{commit[:8]}.zip"


def write_delivery_zip(root: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(root.parent).as_posix(), FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())


def verify_delivery(path: Path, commit: str, tree: str) -> None:
    with tempfile.TemporaryDirectory(prefix="verify-aisl-s2t-") as td:
        root = Path(td)
        with zipfile.ZipFile(path) as zf:
            if zf.testzip() is not None:
                raise SystemExit("corrupt delivery ZIP")
            zf.extractall(root)
        delivery = root / DELIVERY_NAME
        manifest = json.loads((delivery / "DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
        if manifest["source"] != {"commit": commit, "tree": tree}:
            raise SystemExit("source binding mismatch")
        if manifest["third_party_policy"] != "not_vendored_resolve_from_package_index":
            raise SystemExit("third-party policy mismatch")
        wheels = sorted((delivery / "wheels").glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit("delivery must contain exactly one first-party wheel")
        allowed = {"wheels", "DELIVERY_MANIFEST.json", "README.md", "VERSIONS.txt", "requirements.txt", "SHA256SUMS"}
        if set(p.name for p in delivery.iterdir()) - allowed:
            raise SystemExit("unexpected delivery content")
        for candidate in delivery.rglob("*"):
            if set(candidate.relative_to(delivery).parts) & FORBIDDEN:
                raise SystemExit(f"forbidden residue: {candidate.relative_to(delivery)}")
        row = manifest["components"][0]
        wheel = delivery / row["file"]
        if sha256(wheel) != row["sha256"] or wheel.stat().st_size != row["size"]:
            raise SystemExit("wheel checksum mismatch")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--source-commit")
    ap.add_argument("--source-tree")
    args = ap.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    commit, tree = resolve_git_identity(source, args.source_commit, args.source_tree)
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aisl-s2t-delivery-") as td:
        work = Path(td)
        built = build_wheel(source, work)
        delivery = work / DELIVERY_NAME
        (delivery / "wheels").mkdir(parents=True)
        wheel = delivery / "wheels" / built.name
        shutil.copy2(built, wheel)
        row = wheel_row(wheel)
        version = str(row["version"])
        manifest = {
            "schema_version": "aisl_s2t_clean_delivery/v1",
            "boundary": DELIVERY_NAME,
            "source": {"commit": commit, "tree": tree},
            "components": [row],
            "third_party_policy": "not_vendored_resolve_from_package_index",
        }
        (delivery / "DELIVERY_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (delivery / "VERSIONS.txt").write_text(f"{row['name']}=={version}\n", encoding="utf-8")
        (delivery / "requirements.txt").write_text(f"{row['name']}=={version}\n", encoding="utf-8")
        (delivery / "README.md").write_text(
            "# AISL S2T\n\n"
            f"Clean delivery for aisl-s2t {version}.\n\n"
            f"Source commit: {commit}\nSource tree: {tree}\n\n"
            "Contains only the first-party aisl-s2t wheel and delivery metadata. "
            "Third-party dependencies are not vendored.\n\n"
            "Install:\n\n"
            "    python -m pip install --find-links ./wheels ./wheels/aisl_s2t-*.whl\n"
            "    aisl-s2t --help\n",
            encoding="utf-8",
        )
        checksum_files = [p for p in sorted(delivery.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"]
        (delivery / "SHA256SUMS").write_text(
            "".join(f"{sha256(p)}  {p.relative_to(delivery).as_posix()}\n" for p in checksum_files),
            encoding="utf-8",
        )
        target = output / delivery_zip_name(version, commit)
        write_delivery_zip(delivery, target)
        verify_delivery(target, commit, tree)

    result = {
        "file": target.name,
        "sha256": sha256(target),
        "size": target.stat().st_size,
        "source_commit": commit,
        "source_tree": tree,
        "components": [f"{row['name']}=={version}"],
    }
    (output / "BUILD_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
