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
    (ROOT / "reviewer/TEST_RESULTS.txt").write_text(
        f"Python {platform.python_version()}\ncommand: python -B -m unittest discover -s tests -v\nexit_code: {run.returncode}\n"
        + run.stdout + run.stderr + "\nStructural checks (not pipeline acceptance):\n"
        + json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    if any("reference" in p.relative_to(ROOT).parts or p.suffix in {".zip", ".whl"} for p in files):
        raise ValueError("reference archives or dependencies must not be embedded in side source")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 9, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or len(z.infolist()) != len(files):
            raise ValueError("ZIP verification failed")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    counts = json.loads((ROOT / "reviewer/COUNTS.json").read_text())
    checkpoint.write_text(f"""# {version} — Framework reproducibility side project

Дата: 2026-09-12. Статус: FOUNDATION / DRAFT; NOT READY FOR SCORED RECONSTRUCTION.

## Канонический результат этого потока

- ZIP: `source-canonical.zip`
- SHA-256: `{sha}`
- Размер: {archive.stat().st_size} bytes; файлов: {len(files)}; ZIP CRC: PASS.
- Stream: `External Apps/framework-reproducibility`; родитель Drive `1cf--S87lMmj073oDbc9fCqeI7M_ACIUl`.
- Checkpoint folder: https://drive.google.com/drive/folders/{drive_folder_id}
- Здесь только source/docs/tooling side project. Это НЕ новый Framework checkpoint и НЕ implementation DeepSeek.

## Reference и неизменность Framework

{baseline['source_checkpoint']}, SHA-256 `{baseline['source_sha256']}`, {baseline['source_bytes']} bytes.
Source Drive file: https://drive.google.com/file/d/{baseline['source_drive_file_id']}/view
Штатный integrity owner проверил 828/828 файлов до и после извлечения контрактов.
Правила: v1.10, canonical Drive file `1WjK8qsEaIJDjcwTn62HJndAliEYGUj6i`, полностью прочитаны и readback подтвердил те же bytes. Основной source, rules, main plan и ACTIVE task не изменялись.
Original Framework source/wheels, recovery и корпоративные архивы в ZIP не включены. Новые Framework deliveries не собирались.

## Состав и acceptance

- Русскоязычный архитектурный и функциональный draft; протокол DeepSeek, эквивалентность, access boundary, acceptance matrix, gaps и дальнейший план.
- Candidate inventory: {counts['knowledge_families']} knowledge families, {counts['materialization_contracts']} materialization contracts, {counts['core_evidence_contracts']} Core evidence contracts.
- Полный reviewer inventory: {counts['tools']} tools, {counts['api_operations']} API operations / {counts['api_paths']} paths, {counts['delivery_modules']} delivery modules, {counts['capabilities_traced']} capability traces.
- Learner subset: {counts['selected_tools']} tools, {counts['selected_api_paths']} API paths, 4 public schemas, {counts['sql_fact_kinds']} SQL fact field catalogs. Nested SQL schemas ещё неполны.
- 3 exact Integration Profile outputs получены текущим штатным generator на синтетических context; это НЕ публикация revision.
- {unit_count}/{unit_count} side-project unit/pack tests PASS. {checks['local_refs_resolved']} local schema/OpenAPI references resolved; tool API binding checks PASS.
- Дополнительно 16/16 probes штатных owners: 8 Core JOIN scenarios, 19 fact shards repeat-equal, publication builder determinism и 5 negative cases. Подробно reviewer/CONTRACT_PROBES.json.
- {pipeline['check_count']}/{pipeline['check_count']} reference diagnostic pipeline assertions PASS на F4.95: Runner → реальные Core/KLC процессы → neutral publication builder/importer → ASGI API. Проверены 14 HTTP responses по OpenAPI, 2 KLC manifest, profile и public catalog; duplicate publish, новая revision, неизменность старой и readback без producer paths.
- High-level KCP planning/publication adapter, внешний TCP server и полный consumer journey НЕ проверены. Diagnostic pipeline не является scored acceptance.
- Перебазирование F4.92 → F4.95: 36 изменённых файлов, 4 targeted checks PASS. Подробно reviewer/REBASE_F495.json и REBASE_DECISION.md. Reference contracts и текущие oracle outputs пересозданы на F4.95, старые PASS не переименованы в новые.
- DeepSeek НЕ запускался, hidden corpus ещё не подготовлен, model ID ещё не выбран.

## Зависимости и воспроизведение

Локальные side unit tests: Python 3.11+, только stdlib; проверено Python {platform.python_version()}. Core SQL probes дополнительно использовали PyYAML 6.0.3 и pure-Python sqlglot 30.13.0 wheel; first-party reference находился вне side source.
После распаковки: `python -B -m unittest discover -s tests -v`; `python -B tools/validate_pack.py`.
Для reference export нужен отдельно полученный exact F4.95; команда в README. Для pipeline — Python 3.12.14 и 43 pinned third-party distributions из reviewer/runtime-requirements.txt. First-party source не выдаётся learner.
Latest publicly available DeepSeek выбирается по официальным источникам на дату первого scored run, затем точный provider/model/config фиксируется. Бюджеты и tool permissions фиксируются до запуска.

## Ограничения

Это проверенное начальное приращение, не завершённая SDD для восстановления всего Framework.
S01–S06 остаются частично открыты: полный KCP/consumer journey; nested contracts/оставшиеся IDs; negative transport cases; learner-only install. Java/OpenAPI/SQL evidence, KLC и API oracle получены; существование этого диагностического пути не доказывает product liveness всех families.
S07–S09: полный функциональный охват; точный experiment config; hidden corpus.
`interaction-islands` исключён как unregistered/parked; `data-model-attribute-extension` withheld до current-demand review. Generic cross-repository capabilities не исключены автоматически.
S10: reversed inequality orientation issue — pair columns переставлены, operator не инвертирован; compatibility decision не принято. S11 readback выполнен: expression_links сохранены bulk endpoint и не включены в query-context projection. Framework не менялся.
Нельзя передавать DeepSeek весь checkpoint: reviewer содержит внутреннюю traceability; разрешён только готовый learner pack после readiness audit.

## Continuation scope

Пользователь явно возобновил работу: «Да, ты занимаешься только твоим side project!!!!». Это разрешение дано текущему потоку/чату. Глобальный PROJECT_CONTINUATION остаётся у основного Framework S2T consumer-contract потока; мы его не переключали. Старое side PAUSED metadata предшествует этому явному разрешению. Новый checkpoint не назначает side project глобальной continuation. См. reviewer/CONTINUATION_SCOPE.md.

## HANDOFF_NEXT_CHAT

1. Прочитать текущие canonical Drive rules и PROJECT_CONTINUATION; для нового общего чата generic «продолжаем» не выбирает этот side stream. В явно выбранном side project читать README, reviewer/WORK_PLAN.md, GAPS.md и benchmark/PROTOCOL.md.
2. Работать только в явно выбранном side project; не править Framework, общие rules/plan и чужие задачи.
3. Следующий batch SP-SDD-0.4: nested contracts/оставшиеся IDs, full KCP/publication adapter, declared consumer journey и negative transport cases. Учесть S10 без автоматического исправления Framework.
4. Использовать существующих semantic/parser/packaging owners pinned F4.95; проверять manifest штатным owner. Будущий drift сверять отдельно, не перебазировать незаметно.
5. Затем подготовить скрытый acceptance, пройти readiness audit и только после этого запускать DeepSeek.
6. Сохранять следующие immutable side checkpoints двумя файлами в этом stream, с readback. Merge — отдельное решение.
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
