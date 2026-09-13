# API readback и revision: проверенный открытый сценарий

Все пути и response schemas задаёт `../public-contracts/knowledge.selected.openapi.json`, tool bindings — `tools.selected.json`. Точные входы/ответы открытого прогона находятся в `../examples/api-readback.reference.json`. Пример не задаёт универсальные literal revision IDs: они принадлежат конкретной публикации.

## Revision и ошибки

Базовый путь `/api/knowledge/v1/systems/{system_id}`. Чтения выполняются с явным query `revision_id`; implicit latest запрещён.

| Запрос к `/sql/joins` | HTTP | Наблюдение |
|---|---|---|
| Нет revision_id | 422 | request_validation_failed, отсутствует обязательный query parameter |
| revision_id=latest | 400 | literal latest не разрешён |
| revision_id=missing | 404 | неизвестная revision не подменяется активной |
| Существующая revision, offset=0/3/6, limit=3 | 200 | 8 JOIN в трёх страницах; page.total=8, ID не повторяются |

Error body содержит schema_version, code, message, details, request_id; полная форма и конкретные codes — в exact ответах и OpenAPI. Не унифицировать все ошибки в 400. Validation details могут зависеть от зафиксированной версии HTTP/runtime validator; правила нормализации должны быть явно определены до scored run.

## JOIN endpoints различаются

В эталоне F4.95 query/column context публикует output_columns, output_contract_status, output_contract_basis, output_contract_wildcard_provenance; scope relation дополнительно содержит source_scope_ids. Эти поля берутся из опубликованного knowledge, не выводятся consumer по имени relation. Точная форма — текущая OpenAPI projection и API example.

Bulk `/sql/joins` сохраняет `expression_links` для expression JOIN. Query context вызывается через `/sql/query-context?revision_id=...&repo_id=...&query_id=...`; query_id не является сегментом пути. Его `joins` — отдельная projection с `column_pairs`, но без `expression_links`. Нельзя использовать bulk record как точную схему context или объявлять expression links потерянными во всём API. Для полного expression evidence клиент выбирает bulk endpoint.

## Публикация и неизменность

Повторный import одного и того же bundle возвращает `already_published` и прежний revision ID. Это internal import result, не HTTP endpoint response. При публикации второго bundle с base_revision_id первой revision и изменённой publication metadata создаётся новая revision. Повторное чтение первой остаётся побитово тем же JSON для выбранной страницы; новая revision указывает свой ID и читает те же knowledge rows, если продукты не изменились.

Чтение опубликованной revision продолжается после того, как исходный repository и рабочие KLC файлы недоступны по исходным путям. Данные читаются из опубликованного artifact store; повторный анализ source для GET не допускается.

## Предел доказательства

Открытый сценарий использует настоящие Core/KLC процессы, bundle builder/importer и HTTP handlers в ASGI test client. Он не доказывает внешнее TCP deployment, полный KCP planning/authorization, KCP publication adapter или корректность реализации DeepSeek. Не проверены пока malformed bundle import/atomic failure, неизвестная base revision, полный набор filters/limits, пустая конечная страница и declared object → field evidence consumer journey. Эти проверки обязательны для дальнейшей готовности среза.
