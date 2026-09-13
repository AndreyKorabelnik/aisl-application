# Решение о baseline SP-SDD-0.3

Принят reference F4.95 после явного возобновления пользователем. ZIP получен с Drive, SHA `fb3b7134194eddb9d6ac25b184ef046516b368b1aec513c2a29d61a397cd88f3`, 2596556 bytes. Штатные integrity owners проверили оба дерева F4.92/F4.95 (828/828), исходники не изменены.

Сравнение показало 36 изменённых файлов; полный список с hashes — REBASE_F495.json. Количество включает docs, versions, generated SDK/OpenAPI и runtime. Source composition owner/build boundaries не изменены; four-delivery build не нужен для данного side batch.

Семантически значимые изменения:

1. Control-flow embedded SQL, структурно принятый существующим SQL parser, попадает в canonical analysis; assignment/logging не автоматически повышаются до SQL. Два соответствующих штатных owner tests выполнены.
2. При unqualified binding hint/read occurrence не делает единственный declared FROM/JOIN source неоднозначным. Выполнен соответствующий штатный owner test.
3. Query/column context теперь публикует output_columns, output_contract_status/basis/wildcard_provenance; scope relation также source_scope_ids. OpenAPI пересоздан из F4.95; реальный query-context прошёл response schema validation.
4. list_sql_relation_materializations gated exact `common.sql-relation-materialization`; проверены наличие и отсутствие инструмента с/без этой capability. Полный tool catalog есть в reviewer inventory. Learner selected subset остаётся 10 tools: новый scope не добавлялся только из-за drift. Перед расширением среза добавить недостающий selected public contract явно.

Reference exporter, Core SQL/builder probes и diagnostic pipeline повторно выполнены на F4.95. Все текущие generated contracts/oracles относятся к F4.95. Исторические SP-SDD-0.1/0.2 immutable на Drive сохранены; новый checkpoint не является переименованным старым PASS.

Результаты: 16 Core/builder checks, 50 pipeline checks, 4 targeted rebase checks; 34 offline pack tests. SQL reversed inequality S10 не исправлен. S11 описывает разные endpoint projections; bulk expression_links сохраняются. Все оценки относятся к открытым синтетическим inputs, не к скрытому или DeepSeek acceptance.
