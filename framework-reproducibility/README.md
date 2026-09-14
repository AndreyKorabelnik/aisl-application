# Воспроизводимость Framework по SDD — side project

Текущее приращение: **SP-SDD-0.4**, 2026-09-14. Статус: **F4.103 rebase review + production journey / draft, NOT READY FOR SCORED RECONSTRUCTION**.

Начать с `reviewer/CURRENT_REFERENCE.md` и `learner/spec/PRODUCTION_JOURNEY.md`.
Новый read-only reference — F4.103. Штатный integrity owner: 799/799 exact;
semantic coverage: 14 selectable Knowledge IDs / 24 publishable types, PASS.
`reviewer/current-reference/` содержит новый drift audit и текущий production report.
Полное обновление learner contracts ещё требуется. Ниже данные и команды F4.95
сохраняют исходную provenance; старые PASS не переименованы в F4.103.

Working source: `AndreyKorabelnik/aisl-application/framework-reproducibility`.
Drive freeze: `PROJECT_DATA/04_Source_Checkpoints/External Apps/framework-reproducibility/Checkpoints/`.
Framework и соседние приложения не меняются. Глобальный `PROJECT_CONTINUATION`
остаётся NONE / REASSESS; side project явно выбран пользователем для этого чата.

Новый production probe использует отдельно полученный F4.103:

```bash
python -B tools/review_current_reference.py --source /absolute/f4103/source --archive /absolute/f4103/source-canonical.zip --old-source /absolute/f495/source --dependencies /absolute/sdd-dependencies --output reviewer/current-reference
python -B tools/probe_production.py --source /absolute/f4103/source --archive /absolute/f4103/source-canonical.zip --dependencies /absolute/sdd-dependencies --pack . --work /absolute/new-evidence-directory
```

Вторая команда создаёт новый отдельный evidence directory и явную core-only
deployment policy; reference source проверяется до/после. Это production CLI/TCP
в source-mode, не wheel/install acceptance и не scored LLM run.

SP-SDD-0.1 и 0.2 сохранены отдельно и не изменены. В 0.3 добавлены DECLARED_MODEL_CONTRACT и API_READBACK_CONTRACT, точные Java/OpenAPI evidence, 14 API request/response примеров, 2 настоящих KLC materializations и опубликованные revisions. 50 diagnostic probes PASS; 34 offline side-project tests PASS. Подтверждено endpoint-specific различие JOIN projections (S11). S10 — reversed inequality orientation — остаётся без compatibility decision; Framework не исправлялся.

Цель: подготовить русскоязычную спецификацию, по которой последняя публичная DeepSeek сможет независимо реализовать наблюдаемое поведение всего живого Framework без доступа к его исходникам. Пилот проверяет вертикальный срез; он не подменяет конечную цель полного функционального охвата.

Эталон: Framework F4.95, SHA-256 `fb3b7134194eddb9d6ac25b184ef046516b368b1aec513c2a29d61a397cd88f3`.
Основной код, правила и основной план не изменялись. Этот проект не является новым runtime-компонентом Framework.

Работа этого чата явно возобновлена пользователем только для side project. Глобальный PROJECT_CONTINUATION не переключён; см. reviewer/CONTINUATION_SCOPE.md. Перебазирование F4.92 → F4.95 и 4 targeted checks описаны в reviewer/REBASE_DECISION.md. Все текущие generated contracts и oracle outputs повторно получены на F4.95.

## Что уже сделано

- Исходный ZIP получен с Drive; SHA и 828 файлов проверены существующим integrity owner до и после извлечения контрактов.
- Получены карта всех knowledge-кандидатов, Core evidence, materializations, API, tools и package dependencies. Это evidence inventory, не новый runtime registry и не доказательство production liveness.
- Трассировка capabilities выполнена существующим `tools/capability_trace.py`, без нового owner.
- Подготовлены архитектурная SDD, правила эквивалентности, начальная функциональная спецификация и протокол эксперимента.
- Выделены публичные контракты для первого среза; OpenAPI-проекция сохраняет точные операции и транзитивно замыкает `$ref`.
- Получены три точных результата штатного генератора Integration Profile на синтетических контекстах: SQL, declared model и отсутствие capabilities. Это текущий generator acceptance, не полный pipeline.
- Есть минимальный строгий JSON comparator, его unit tests и проверка состава пакета. 34 offline side-project tests проверяют comparator и сохранённые vectors; это не новый runtime run.
- Выполнен `Runner diagnostic plan → Core subprocess → KLC subprocesses → neutral publication builder/importer → ASGI API`. 50 assertions включают schema validation, pagination, errors, duplicate publish, две revisions и readback без producer paths. Это не full KCP journey и не DeepSeek acceptance.

## Граница доступа

| Каталог | Кто читает | Назначение |
|---|---|---|
| `learner/` | DeepSeek, когда пакет готов | Только спецификация, публичные контракты и открытые примеры |
| `reviewer/` | Автор SDD и оценщик | Provenance, карта исходного кода, gaps, baseline, результаты проверок |
| `benchmark/` | Оценщик | Протокол и comparator; не является production path |
| `tools/` | Автор SDD | Read-only экспорт из F4.95 и выпуск пакета |
| `tests/` | Автор SDD | Проверки side project |

**Нельзя передавать весь checkpoint DeepSeek.** Исходники Framework не включены даже в reviewer-архив, но reviewer inventory раскрывает внутренние refs. `learner/` также пока не готов: gaps перечислены явно. Скрытый корпус в этом checkpoint ещё не создан; его нельзя заменить тестами из `learner/`.

## Проверка и повторное извлечение

Python 3.11+; для локальных тестов side project достаточно стандартной библиотеки.

```bash
python -B -m unittest discover -s tests -v
python -B tools/validate_pack.py
```

Для пересоздания производных reference-файлов нужен exact F4.95, распакованный вне этого дерева:

```bash
python -B tools/derive_reference.py --source /absolute/f495/source --archive /absolute/f495/source-canonical.zip --output .
```

Экспорт `derive_reference.py` загружает штатные read-only owners Framework, но не запускает Core/Runner/KLC и не публикует AISL. Публичные schemas и tools — производные неизменённого baseline. Не редактировать их вручную.

Дополнительный reviewer probe 0.2 запускает штатный Core SQL и producer-neutral bundle builder, без Runner/KLC/server. Нужен отдельно предоставленный sqlglot 30.13.0 wheel; используется zipimport pure-Python wheel, ABI wheels не устанавливаются. Окружение probes: Python 3.12.14, PyYAML 6.0.3. Для полного pipeline требуются дополнительные штатные зависимости.

```bash
python -B tools/probe_contracts.py --source /absolute/f495/source --output . --sqlglot-wheel /absolute/sqlglot-30.13.0-py3-none-any.whl
```

Reviewer pipeline 0.3 проверен на Python 3.12.14, Linux, с изолированными 43 установленными third-party distributions. Точные версии — `reviewer/runtime-requirements.txt`; стандартные compatible wheels получены для Python 3.12, приложенные cp313 wheels не устанавливались. Это resolved probe environment, не новый Framework dependency owner и не переносимая universal lockfile.

```bash
python -m pip install --target /absolute/sdd-dependencies -r reviewer/runtime-requirements.txt
python -B tools/probe_pipeline.py --source /absolute/f495/source --output . --dependencies /absolute/sdd-dependencies
```

Эти команды предназначены автору/оценщику с доступом к эталону, не DeepSeek. Стенд использует штатные Core/KLC owners, но задаёт author-selected low-level resolution plan и producer-neutral publication вручную; не выдавать его за полную автоматизацию KCP. Raw outputs, DB, manifests, HTTP responses и версии — `reviewer/oracles/pipeline/`, результат — `reviewer/PIPELINE_PROBES.json`. Абсолютные временные пути и duration в raw logs — provenance конкретного запуска, не переносимые execution inputs. Для повторного прогона стенд создаёт новые пути.

## Следующее завершённое приращение

SP-SDD-0.4: закрыть полные nested contracts/оставшиеся IDs и добавить нормальный KCP planning/publication path, consumer object → field evidence и transport negative cases. Построить obligation-to-assertion mapping и отдельный held-out corpus. Учесть нерешённый S10; S11 уже описан по точному API readback. Лишь после readiness audit запускать DeepSeek.

Результаты хранятся отдельно: `Автоматический анализ кода / External Apps / framework-reproducibility / Checkpoints / SP-SDD-0.3`. Название External Apps обозначает место независимого потока; side project не объявляет новый компонент платформы.

Merge в Framework не выполнен и не предполагается автоматически. При будущем merge отдельно сверить дрейф от F4.95 и решить, какие документы и тесты действительно должны войти в основной source.
