# Первый функциональный срез: наблюдения → revision → consumer

Статус: draft, часть поведения ещё нуждается в точных fixtures и oracle.

## Java и структурные схемы

J01. Для Java сохранять source unit, declared types/fields, annotations, type expressions, inheritance и source references. Declaration и effective inherited field не смешиваются. Нельзя представлять любой declared type как физическую таблицу.

J02. При неоднозначной ссылке на тип сохранять кандидатов и unresolved/ambiguous status. Не выбирать класс по похожему имени. Точные алгоритмы stable IDs и source spans будут частью завершённой спецификации.

SC01. Первый structured source — JSON-документ OpenAPI 3.1. Для схем сохранять свойства, required, nullable/type variants, inline object и точный local `$ref`. Это поддержка структурных declarations; endpoint extraction из этого примера не требуется.

SC02. Одинаковое имя схемы в разных файлах не объединяет их identity. Если внешняя ссылка не разрешена поддерживаемым owner, сохранить literal ref и диагностировать её. Не загружать ресурс из сети по догадке.

Выходной declared model: `code-declared-data-model/v1`. Machine projection публичных объектов/полей присутствует в OpenAPI. Это не полный контракт входных evidence payloads: данный пробел должен быть закрыт до запуска DeepSeek.

## SQL JOIN и lineage

SQL01. Единица наблюдения JOIN — `sql_join_edge`; одна запись может содержать несколько `column_pairs`. JOIN edge и пара атрибутов — разные сущности.

SQL02. Для `a.id=b.a_id AND a.code=b.code` сохранить обе пары. Для `a.dt>=b.start_dt AND a.dt<b.end_dt` сохранить оба оператора и range/temporal роли. Сопутствующий фильтр `b.enabled=1` не является второй парой колонок.

SQL03. `USING(id)` даёт пару одноимённых атрибутов, когда relations определены. `CROSS JOIN` может быть подтверждённым JOIN без единой column pair; нельзя придумывать ключ.

SQL04. Для неоднозначного `ON id=b.id` не выбирать левую колонку молча. Сохранить partial status, reasons и отсутствие физического подтверждения согласно контракту.

SQL05. JOIN с CTE может быть логически подтверждён, но `physical_join_confirmed=false`. Нельзя объявлять CTE физической таблицей или заменять наблюдаемый JOIN домысленной транзитивной связью.

SQL06. Expression JOIN, например конкатенация двух полей, должен сохранять выражение и все наблюдаемые зависимости. Не превращать его в независимые equality JOIN по каждому входному полю. Exact nested shape `expression_links` — открытый gap S02.

SQL07. Lineage результата INSERT/SELECT различает target binding, direct source и recursive terminal origin. Переименование не означает потерю provenance; missing physical origin не заполняется догадкой.

CFG01. Placeholder substitution допустима только по опубликованному `resolution_status=resolved` с доказанным контекстом. Иначе сохраняется literal placeholder. Явный selector окружения относится к production request; consumer не смешивает значения из разных конфигураций.

## Публичное чтение

API01. JOIN bulk read: `GET /api/knowledge/v1/systems/{system_id}/sql/joins` с обязательным `revision_id`. Фильтры, пределы, envelope и operation ID заданы в OpenAPI и tool binding.

API02. Consumer, запросивший «все JOIN», читает страницы до полного покрытия `page.total`. Точный offset/limit не заменяет несуществующим cursor. При неполном результате нельзя утверждать, что перечислены все JOIN.

API03. Отсутствующая capability отличается от существующего пустого набора; неизвестная revision — не повод читать active revision. Коды HTTP и errors нужно проверить на canonical oracle, а не придумать по этим предложениям.

## Integration Profile

PROFILE01. Profile содержит exact `scope.system_id`, `scope.revision_id`, `revision_binding=pinned`, capabilities, artifact summaries, tools с API bindings, guidance и fingerprints.

PROFILE02. Tools выбираются по capabilities revision через существующий структурный каталог. Имя retrieval profile не является самостоятельным разрешением на tool. Эту особенность важно сохранить: «SQL profile» не означает автоматически право на любой SQL endpoint.

PROFILE03. `get_knowledge_context` — embedded profile context, не внешний HTTP tool. Синтетические примеры `../examples/profile-*.json` содержат текущие outputs штатного генератора, включая отсутствие недопустимых tools в empty case.

PROFILE04. Пользовательские описания из Integration Content — русский язык; machine IDs, argument names, paths и protocol tokens сохраняются. Точные cryptographic fingerprints требуют точных правил канонизации, которые ещё должны быть выписаны (S03).

## Consumer scenario и отчёт

Первый scenario: все наблюдаемые JOIN-пары и статусы на одной pinned revision. Второй: поиск declared objects и чтение поля с provenance. CSV — тестовый consumer результат, не новая встроенная product-specific функция Framework.

Agent Runtime JSON action envelope и пользовательское содержимое ответа различаются. Требование пользователя «только CSV» не отменяет внутренний transport contract. Полная UI/Agent Runtime реконструкция относится к расширению после базового среза, а не считается выполненной по двум SDK queries.
