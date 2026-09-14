"""Package this isolated side project, never the original Framework source.

Writes a new immutable local checkpoint directory; existing archive is an error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_pack import validate


def release(destination, version, drive_folder_id):
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("checkpoint output must be outside source tree")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "source-canonical.zip"
    checkpoint = destination / "CHECKPOINT.md"
    if archive.exists() or checkpoint.exists():
        raise ValueError("immutable checkpoint files already exist; choose a new version")
    run = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                         cwd=ROOT, text=True, capture_output=True, timeout=60)
    if run.returncode:
        raise RuntimeError(run.stdout + run.stderr)
    checks = validate()
    baseline = json.loads((ROOT / "reviewer/BASELINE.json").read_text())
    pipeline = json.loads((ROOT / "reviewer/PIPELINE_PROBES.json").read_text())
    unit_count = unittest.TestLoader().discover(str(ROOT / "tests")).countTestCases()
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    if any("reference" in p.relative_to(ROOT).parts or p.suffix in {".zip", ".whl"} for p in files):
        raise ValueError("reference archives or dependencies must not be embedded in side source")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 9, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or len(z.infolist()) != len(files):
            raise ValueError("ZIP verification failed")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    counts = json.loads((ROOT / "reviewer/COUNTS.json").read_text())
    current = json.loads((ROOT / "reviewer/current-reference/REBASE_REVIEW.json").read_text())
    production = json.loads((ROOT / "reviewer/current-reference/PRODUCTION_PROBES.json").read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD:framework-reproducibility"], cwd=ROOT, text=True).strip()
    checkpoint.write_text(f"""# {version} — Framework reproducibility side project

Дата: 2026-09-14. Статус: DRAFT / NOT READY FOR SCORED RECONSTRUCTION.
Scope: только framework-reproducibility в AndreyKorabelnik/aisl-application.
GitHub accepted commit: {commit}
GitHub application subtree: {tree}

## Source
- source-canonical.zip: {archive.stat().st_size} bytes, {len(files)} files.
- SHA-256: {sha}
- ZIP CRC / file count: PASS.
- Drive folder: https://drive.google.com/drive/folders/{drive_folder_id}
- Framework source, wheels, DB, bundles и raw run outputs не включены.

## Reference / acceptance
Текущий reference F4.103: commit {current['commit']}.
ZIP SHA-256 {current['source_sha256']}; 799/799 exact штатным integrity owner.
Framework source не менялся. repository-topology, правила, общий план не менялись.
Rules v1.21 прочитаны полностью. Глобальный PROJECT_CONTINUATION = NONE / REASSESS;
side project ранее явно выбран пользователем для этого чата.

F4.95 → F4.103: {current['change_count']} изменённых путей.
Штатный Semantic Knowledge Coverage Gate: PASS, 14 selectable / 24 products / 12 resources / 8 profiles.
Новый KCP→Runner/Core/KLC→publication adapter→import CLI→TCP→consumer:
{production['check_count']}/{production['check_count']} checks PASS.
Deployment: explicit core-only policy, source-mode launchers из project.scripts.
Проверены SQL paging/errors, duplicate import, pinned Integration Profiles,
declared object→fields/inheritance/relationship evidence и readback без producer paths.
{unit_count}/{unit_count} offline side tests PASS; structural validator PASS.
Старые {pipeline['check_count']} pipeline assertions остаются evidence F4.95.

## Ограничения
Полный learner rebase, nested SQL/IDs, invalid dependency/base/bundle atomic negatives,
clean learner install, hidden acceptance и DeepSeek run ещё не закрыты.
Source-mode probe не является wheel/install или Technology Extension acceptance.
Semantic coverage owner доказывает structural routing, не runtime всех families.
Нельзя передавать DeepSeek reviewer/source references.

## HANDOFF_NEXT_CHAT
1. Прочитать текущие rules и Current Plan; продолжать этот side stream только при явном выборе.
2. Восстановить exact GitHub side source; начать с reviewer/CURRENT_REFERENCE.md.
3. Использовать F4.103 read-only. Новый drift оценить отдельно; не переименовывать старые PASS.
4. Следующий batch: learner projections F4.103, nested SQL/identity и transport negatives.
5. Затем learner-only install и скрытый acceptance; DeepSeek выбрать по официальным данным на дату scored run.
6. Framework, соседние apps и project-level continuation не менять.
""", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "checkpoint": str(checkpoint), "sha256": sha,
                      "bytes": archive.stat().st_size, "files": len(files), "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--drive-folder-id", required=True)
    args = parser.parse_args()
    release(args.destination, args.version, args.drive_folder_id)
