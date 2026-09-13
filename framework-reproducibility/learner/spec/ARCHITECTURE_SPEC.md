# SDD: архитектура и границы ответственности

Версия 0.1. Статус: draft. Нормативная цель полного охвата; доступные machine contracts пока покрывают только первый срез. Неполнота не является разрешением угадывать.

## Назначение и критерий воспроизведения

Система принимает репозитории, извлекает наблюдаемые факты зрелыми парсерами, производит проверяемые знания и публикует immutable revisions. Человек и LLM читают уже опубликованное knowledge. Бизнес-смысл не должен появляться вследствие неподтверждённой догадки.

Нужна функциональная совместимость по контрактам, а не одинаковые файлы, классы и число строк. Требование «весь Framework» означает все подтверждённые текущие семейства функций. Независимые продукты Repository Inventory, Benchmark Miner, external-s2t, repository-topology в него не входят.

## Слои

| Слой | Вход | Ответственность и выход | Граница |
|---|---|---|---|
| Source syntax | Файл, его формат и source identity | Зрелый parser owner; структурные наблюдения | Не выводит бизнес-смысл |
| Core | Snapshot репозитория, явный analyzer request | Typed evidence artifacts, coverage, diagnostics и provenance | Не владеет KLC materialization |
| Runner | Запрос knowledge, evidence contracts, доступные inputs | План зависимостей, запуск Core/KLC, результат исполнения | Не дублирует семантику producers |
| KLC | Типизированные evidence и уже произведённое knowledge | Derived knowledge, lineage, ambiguities и gaps | Не использует имя сценария как скрытый semantic selector |
| KCP | Пользовательский запрос производства | Управление исполнением и передача явного контекста в существующий pipeline | Не второй analyzer/resolver |
| Publication | Готовые Knowledge Products и artifacts | Producer-neutral descriptor и integrity-checked bundle; immutable revision | Не анализирует исходный репозиторий |
| Prepared Runtime / Knowledge API | Точно выбранная revision | Типизированные read-only ответы и discovery | Не запускает Core/Runner/KLC для чтения |
| Knowledge Integration / content | Revision metadata, capabilities, внешний контент | Integration Profile с guidance, tools и bindings | Не исполняет новый task router |
| SDK, CLI, UI | Public API и pinned scope | Пользовательские операции; Agent Runtime во внутреннем UI | Специфические решения принадлежат consumer |

Наличие общего вычислителя взаимодействий или lineage между репозиториями внутри поддерживаемого workspace не следует путать с произвольной бизнес-композицией разных systems/revisions. Первая функция может быть текущей generic capability; вторая остаётся снаружи. Не запрещать существующую функцию только по слову «cross-repository».

## Инварианты

| ID | Обязательство | Acceptance scenario |
|---|---|---|
| A01 | Один семантический owner каждого контракта; производные копии не редактируются независимо | OWN-01: traceability + drift check |
| A02 | Не смешивать observed, supported inference, ambiguity и unresolved | EV-01: неоднозначный вход не становится confirmed |
| A03 | `not_observed` не означает доказанное отсутствие | EV-02: неполная coverage сохраняется в API |
| A04 | Сохранять provenance, basis/confidence и diagnostics, включая частичный результат | EV-03: source → publication → API |
| A05 | Все consumer knowledge reads привязаны к точному system/revision | REV-01: смена active revision не меняет pinned reads |
| A06 | Capability revision определяется опубликованными metadata, не установленным кодом или таблицей БД | CAP-01: нет публикации — нет разрешённого tool |
| A07 | Missing required input/unsupported schema — явный failure или предусмотренный contract gap | RUN-01: недостающий prerequisite |
| A08 | Отсутствующий optional input не превращается в обязательную зависимость | RUN-02: базовый запрос без enrichment |
| A09 | Read boundary не производит новые claims и не требует исходников | READ-01: чтение после удаления доступа к source |
| A10 | Нет скрытых parser fallback, guessed JOIN, schema или placeholder value | SQL-04 / CFG-01 |
| A11 | Новая реализация может менять внутреннюю структуру, но сохраняет согласованные public boundaries | BUILD-01: запуск только по инструкциям |
| A12 | Внешний integration-content обязателен там, где его требует runtime; packaged fallback не подставляется | PROFILE-04: отсутствие контента — явная ошибка |

Acceptance IDs здесь обозначают требования к будущим исполняемым проверкам. Таблица сама по себе не означает PASS.

## Parser ownership

Java: Tree-sitter + grammar Java. SQL: sqlglot; PostgreSQL procedural grammar имеет отдельный зрелый owner. JSON: стандартный parser; YAML/XML/TOML — соответствующие стандартные/зрелые библиотеки. Proto, HOCON, Java Properties — зрелые специализированные библиотеки. Для уже поддерживаемого формата нельзя заменять owner регулярными выражениями или самописным tokenizer.

В нормативной реализации анализа репозитория LLM не участвует. DeepSeek используется для написания альтернативной реализации; LLM в consumer/UI — отдельная роль.

## Публикация и чтение

Semantic declaration: `aisl_publication_descriptor/v1`; transport: `aisl_publication_bundle/v3`. Продукт имеет тип/schema, origin, идентичность и явные physical artifacts. Same-system incremental publication с заданным `base_revision_id` создаёт новый immutable snapshot; product slots определяют замену. Зависимости задаются точно, без угадывания latest.

Публичный envelope: `knowledge_api/v1`; prefix `/api/knowledge/v1`. Точный interface subset находится в `../public-contracts/knowledge.selected.openapi.json`. Это выбранная проекция общего интерфейса, а не весь Framework API.

Один публичный ресурс может быть read-only POST; нельзя считать все POST операциями изменения данных.

## Полный целевой функциональный охват

Помимо первого среза должны быть рассмотрены effective/declared data model, physical model, storage usage, persistence и value lineage, logical-storage/physical correspondence, reference data, system description, system interactions/field contracts, technology extensions, SDK/CLI/UI и производственные сценарии. Для каждого требуется собственный consumer journey и измеримая проверка. Dead/parked механизмы не восстанавливаются.

Отчёты в целевой системе — задачи общего Agent Runtime по Report Templates и Integration Profiles/tools. Отдельный reporting engine, HTTP service, dataset/renderer lifecycle не требуется.
