# Открытые пробелы перед scored run

Текущее приращение SP-SDD-0.4: см. CURRENT_REFERENCE.md. F4.103 drift — 169 путей;
старый learner inventory ещё F4.95 и требует re-export. S01/S05/S06 дополнены
штатными KCP planning/publication и TCP consumer-проверками в явном core-only
source-mode. Это не clean install, не проверка всех Technology Extensions и не
Agent/DeepSeek loop. Итог текущего прогона: current-reference/PRODUCTION_PROBES.json.
S02/S03, invalid transport/base/dependency atomic negatives S04, hidden S09 остаются
открытыми. S10 нельзя нормализовать или исправлять в Framework в рамках этого потока.
Удалённые после F4.95 surfaces теперь исключены, а не parked/withheld runtime;
актуальная классификация — CURRENT_REFERENCE.md. Таблица ниже — backlog полноты.

Статус SP-SDD-0.3 — declared contracts + diagnostic pipeline oracle, не завершённая SDD. S02/S03 дополнены exact Java/OpenAPI envelopes и identity vectors. S04 подтверждён server import, duplicate и successive revisions. S06 получил настоящий Core/KLC/publication/ASGI readback, но не полный KCP/consumer journey. 50 runtime assertions PASS, 34 offline tests PASS. Ни один пункт ниже не является автоматически Framework bug. S10/S11 описаны в KNOWN_CONTRACT_ISSUES.md.

| ID | Пробел | Что закрывает |
|---|---|---|
| S01 | Inventory содержит объявления и code wiring, не полный current-use proof | По каждому выбранному journey: production run → publication → API → consumer; не выдавать catalog flags за наблюдение |
| S02 | SQL field inventory не задаёт вложенные payloads, nullability и expression links; Core envelopes недостаточно формализованы | Точные schemas/examples из действующих owners, semantics каждого required field |
| S03 | Stable IDs/fingerprints и допустимое semantic remapping ещё не описаны полностью | Алгоритмы идентичности, область уникальности, канонизация, test vectors; explicit equivalence rules |
| S04 | Import round-trip, duplicate и две revisions доказаны; invalid bundle, dependency/base rejection, atomic failure ещё не проверены | Полный normative transport contract + оставшиеся black-box negative cases |
| S05 | Не зафиксированы runnable production commands и execution payload всего среза | Exact public request/CLI contract, install closure, самостоятельный end-to-end oracle |
| S06 | Java/schema/SQL, KLC, neutral publisher и API oracle есть; отсутствуют high-level KCP planning/publication adapter и полный consumer journey | Production selection/authorization → execution → publication → consumer, отдельно от диагностического стенда |
| S07 | Полный охват вне выбранного среза не специфицирован | Поэтапное расширение feature families, включая technology extensions, KCP, SDK/CLI, UI |
| S08 | Scored model/environment не зафиксированы | На дату запуска проверить публичный DeepSeek, записать точный served model ID, endpoint, режим, budgets; без секретов |
| S09 | Скрытый acceptance отсутствует | Отдельный corpus с независимыми примерами, не производными переименованиями только видимых tests |

## Замечания по эталону, не требующие изменений сейчас

1. `interaction-islands`: каталог явно сообщает `unavailable_unregistered`; исключён из target.
2. `data-model-attribute-extension`: implementation присутствует; текущая постановка внешнего продукта parked, независимый current demand не доказан. Пока withheld, не удалять из Framework в рамках side project.
3. `aisl-reporting`: отсутствует в actual delivery map F4.92; упоминание в правилах v1.7 — исторический текст, не основание восстанавливать пакет.
4. `cross-repository-attribute-lineage` и generic `system-interactions` нельзя исключать только по названию: надо отличать поддерживаемую generic workspace capability от произвольной business composition.
5. Некоторые публичные SQL ответы содержат свободные JSON records: OpenAPI alone недостаточно для реализации semantics.
6. Старые три `profile-*.json` доказывают только generator behavior. Новый `api-readback.reference.json` содержит profile реальной опубликованной revision. Ни один из них не доказывает LLM loop.

## Закрытая часть S11

Реальный readback подтвердил: bulk SQL JOIN сохраняет expression_links, query-context не включает это поле. Контрактное различие описано и проверено; blanket defect API не заявляется. Не требует изменения Framework в этом потоке.

## Следующий bounded batch

Сначала S02–S05 для selected slice, затем S06. Использовать текущие owners, а не создавать новый extraction/runtime путь в Framework. На каждом fixture проверить, что observable behavior не навязывает приватную структуру эталона. После закрытия среза — запуск benchmark, затем решение о широком покрытии. Готовая SDD должна в итоге покрывать весь живой Framework, а не навсегда ограничиться пилотом.
