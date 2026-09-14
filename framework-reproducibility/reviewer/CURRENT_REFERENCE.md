# Текущая точка SDD: аудит F4.103 и production journey

Дата: 2026-09-14. Только `framework-reproducibility`, статус DRAFT / NOT READY.

Правила v1.21 прочитаны полностью. Глобальный PROJECT_CONTINUATION = NONE / REASSESS;
этот чат продолжает ранее явно выбранный пользователем side project. Общие правила,
Current Plan, Framework и соседний repository-topology не изменяются.

## Два разных вида evidence

- Текущий reference: F4.103, commit `ecb6ae4833049cc382316bd11f9d2a6c7bb0b006`,
  tree `d66c79f70c1b82ef36c3e99d54490c675e75e2af`, ZIP SHA-256
  `dae19d29160b464b91235652c3b012cf96a2becc8c0ded25ec4ca1ca81b40557`.
  Drive source ID `177WUstK97c8gL_qiQDo_U8lPSt4VHGQw`; 2,479,832 bytes;
  штатный integrity owner: 799/799 exact.
- Файлы `BASELINE.json`, старые inventory/projections и `PIPELINE_PROBES.json`
  остаются evidence F4.95. Их 50 PASS не являются новым runtime acceptance F4.103.
  Они нужны текущим offline tests и ещё не заменённым разделам draft.
  Полное обновление learner pack на F4.103 НЕ завершено.

## Решение по дрейфу

От F4.95: 169 путей изменены (130 modified, 34 deleted, 5 added).
Exact before/after SHA находятся в `current-reference/REBASE_REVIEW.json`.
F4.97 был предварительным reference до продолжения сессии; его незавершённые
source-mode пробы не используются как acceptance текущего Framework.

Нельзя просто заменить version label. Из целевого полного охвата исключены
удалённые interaction-islands, dedicated Attribute Extension, legacy data-model
compatibility и structured-file-shape-evidence. Сохраняются generic SQL, модели,
lineage и consumer-owned report/s2t/v1. logical-physical-mapping теперь supporting-only:
прямой выбор запрещён, зависимость effective-data-model разрешена.
Stand-aware SQL selector и attribute-lineage/v1 требуют отдельных SDD obligations.

`current-reference/SEMANTIC_COVERAGE.json` получен вызовом существующего
`knowledge_integration.semantic_coverage.semantic_knowledge_coverage_report`.
Результат: 14 selectable Knowledge IDs, 24 publishable types, 12 resources,
8 profiles, все 6 failure categories пусты. Это structural reachability,
не runtime liveness всех 14 families и не новый SDD registry.

## Граница production probe

`tools/probe_production.py` вызывает штатные KCP CLI и Runner/Core/KLC subprocesses,
KCP publication adapter, server import CLI и настоящий TCP Knowledge API.
Consumer проверяет revision pinning, pagination, errors и declared object/field evidence.
Он детерминированный; LLM/Agent loop не запускался.

Deployment явно core-only через поддерживаемый `AISL_TECHNOLOGY_EXTENSION_POLICY`.
Входы — открытые синтетические Java/OpenAPI/SQL примеры. Корпоративные extensions
им не требуются. Штатная bundled policy требует установленных distributions;
её ранний отказ классифицирован как source-mode environment limitation.
Policy эталона не изменялась. Console launchers механически проецируют
`project.scripts` в отдельный временный каталог. Это НЕ clean wheel/install acceptance.

Raw state, DB, bundles и stdout хранятся вне Git source; в source остаётся лишь
минимальный итоговый report. Framework manifest проверяется до/после работы.

## HANDOFF_NEXT_CHAT

1. Прочитать текущие Drive rules и Current Plan; продолжать этот stream только при
   явном выборе пользователя, уже действующем в этом чате.
2. Восстановить GitHub commit/tree этого приращения. Framework F4.103 читать только
   как pinned reference; новый дрейф оценивать явно.
3. Закрыть re-export selected learner contracts на F4.103, nested SQL payload/IDs,
   missing-base/dependency/corrupt bundle atomic negatives. Не запускать LLM до readiness.
4. Перенести обязательства из current semantic coverage в полную feature matrix,
   сохраняя отдельные structural / runtime / consumer доказательства.
5. Подготовить learner-only install и скрытый acceptance вне public GitHub.
   На дату scored run зафиксировать последнюю публичную DeepSeek и бюджет.
6. Не менять Framework, repository-topology или project-level continuation.
