# SQL JOIN: уточнение наблюдаемого контракта F4.95

Статус 0.2: извлечено из producer и проверено на синтетическом Core corpus. API/KLC oracle ещё не выполнен. Полные алгоритмы query/scope/relation identity остаются открытыми; этот документ не объявляет весь S02/S03 закрытым.

## Слои представления

Core сохраняет JSONL `sql_join_edge` в `sql-analysis/v1`. KLC каталог `knowledge_layer_sql/v2` перечисляет поля и переносит структурные значения в JSON-колонки. На границе HTTP действуют response schema и projection конкретного endpoint. Это не один одинаковый payload: нельзя выдавать Core record вместо API envelope. `fact_type`, `evidence` и HTTP `evidence_refs` относятся к разным представлениям.

Открытый `../examples/sql-joins.reference.json` содержит 8 точных Core records для `sql-cases.sql`, `repo_id=sdd-synthetic`. Синтетический репозиторий содержит только этот SQL-файл: состав файлов влияет на ordinal query IDs. Результат получен текущим owner, не вручную написан как ожидаемый.

## JOIN record

Точные имена верхнего уровня перечислены в `sql.fact-fields.json`. Core дополнительно содержит `fact_type=sql_join_edge`. JOIN ordinal начинается с 1 внутри scope. `left_relation_id` равен единственному элементу `left_relation_ids`, иначе null; список left IDs может описывать несколько предыдущих rowsets. Имена relation берутся из scope, не из бизнес-справочника.

`predicate` — sqlglot-rendered ON expression с восстановленными placeholders, максимум 8000 символов; без ON — null. `using_columns` сохраняет элементы USING; CROSS/NATURAL не требуют придуманной equality-пары. `additional_predicates` — отдельные конъюнкты без подходящего межrelation pair/link. Списки reasons и temporal/range predicates удаляют повторы с сохранением первого появления.

## Прямая column pair

| Поля | Тип / значение |
|---|---|
| `left_column_usage_id`, `right_column_usage_id` | string или null; у USING оба null |
| `left_relation_id`, `right_relation_id` | string или null; unknown не заполняется догадкой |
| `left_relation_name`, `right_relation_name` | string или null |
| `left_column`, `right_column` | Наблюдаемое имя поля; unresolved binding не стирает имя |
| `operator`, `predicate` | Оператор и rendered predicate; predicate ограничен 4000 символами |
| `predicate_role` | `equality_key` для `=`/`<=>`, иначе `range_or_temporal` по текущей проекции |
| `resolution_status` | `confirmed` при двух разных разрешённых relations; иначе `partial` |

USING pair дополнительно имеет `left_relation_candidate_ids` и `left_relation_candidate_names`. При одном left relation они пусты. При нескольких left relations unique left ID/name равны null, кандидаты сохраняются; выбор не угадывается. Для обычной ON pair эти два поля могут отсутствовать: отсутствие и пустой список не нужно автоматически уравнивать.

Сравнение двух колонок одной relation — дополнительный predicate, не межrelation pair. Несколько keys одного JOIN остаются несколькими pairs одного edge. Обратная запись equality `b.id=a.id` ориентируется так, чтобы присоединяемая relation была справа.

**Неразрешённое решение совместимости:** при развороте несимметричного оператора в F4.95 наблюдается расхождение между ориентированными колонками и исходным predicate. До отдельного решения не считать такое представление корректной самостоятельной формулой и не скрывать расхождение нормализатором. В обычном неперевёрнутом range case обе границы сохраняются. Scored policy для reversed inequality пока не определена.

## Expression link

Expression JOIN не создаёт декартово множество выдуманных column pairs. Объект `expression_links[]` содержит:

- `left_expression`, `right_expression`: rendered operands, максимум 4000 символов каждый;
- `left_relation_ids`, `right_relation_ids`, `left_relation_names`, `right_relation_names`: наблюдаемые стороны выражения;
- `left_columns`, `right_columns`: списки объектов с `column_usage_id`, `relation_id`, `relation_name`, `column`, `resolution_status`;
- `operator`, `predicate`, `predicate_role`, `resolution_status`.

Role для equality: `equality_expression`, иначе `range_or_temporal_expression`. Вложенный column status — статус разрешения column usage, например `resolved`, а не обязательно `confirmed`. Он не заменяется статусом всего JOIN. Повторы column refs удаляются по тройке relation ID, column name, column usage ID; одинаковое имя с разными usage IDs не обязано схлопываться.

Link строится, когда обе стороны имеют непустые разрешённые relation ID sets без пересечения. Иначе predicate остаётся дополнительным. Source expressions и все зависимости сохраняются, но не становятся самостоятельными бизнес-ключами.

## Статусы

JOIN confirmed требует разрешённых right и left relations, отсутствия unresolved predicate columns и одного из условий: CROSS/NATURAL, подтверждённые USING pairs либо ON с непустыми подтверждёнными pairs/links. Если right разрешён, но условия не выполнены, JOIN partial; без right — unresolved.

Reasons: `right_relation_unresolved`, `left_relation_unresolved`, `predicate_column_unresolved_or_ambiguous`, `cross_relation_predicate_not_resolved`, `using_left_relation_ambiguous` — по соответствующим наблюдениям. Набор причин может быть пуст даже при partial; нельзя самостоятельно придумывать diagnostic code.

`physical_join_confirmed=true` означает confirmed JOIN и непустой набор участников, все с kind `physical` или `physical_template`. Это не доказывает разрешённость конкретного deployment placeholder. CTE может давать confirmed logical JOIN и false physical flag. `evidence_maturity_level` — отдельное поле: например observed Core output имеет JOIN `partial`, а maturity `unresolved`.

## JOIN ID

Материал: последовательно `query_id`, `scope_id`, десятичный `join_ordinal`, `right_relation_id` либо пустая строка, rendered/truncated `predicate` либо пустая строка, USING names через запятую. Шесть частей соединены символом `|`. SHA-256 UTF-8 этого материала сокращается до первых 16 lowercase hex. ID: `sql_join_edge_` + repo ID + `_` + digest16.

Это правило описывает только JOIN ID, не алгоритмы родительских IDs. Он чувствителен к rendered SQL и именам, не предназначен для произвольной semantic equivalence между разными исходными statements. Query IDs могут измениться при добавлении другого файла, поэтому fixtures должны задавать весь source snapshot.
