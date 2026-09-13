# Acceptance matrix — черновик обязательств

Ни одна строка не прошла **scored DeepSeek acceptance**. Открытые reference observations для части обязательств получены в 0.2/0.3 и перечислены ниже; они не равны полному покрытию строки. Unit tests comparator не являются runtime acceptance. Скрытый корпус ещё не создан.

| SDD obligation | Acceptance ID | Проверяемое свойство / негативный случай |
|---|---|---|
| A01 | OWN-01 | Один semantic owner каждого контракта; нет независимо изменяемых дубликатов |
| A02 | EV-01 | Candidate/ambiguous/unresolved статусы не повышаются до confirmed |
| A03 | EV-02 | Пустой результат и not_observed не утверждают отсутствие возможности |
| A04 | EV-03 | Факт сохраняет source provenance, basis/confidence и diagnostics во всей цепочке |
| A05 | REV-01 | pinned revision остаётся неизменной после публикации следующей; неизвестная revision не читает latest |
| A06 | CAP-01 | Allowed/selected/executed/published различаются; capability разрешена только контрактным путём |
| A07 | RUN-01 | Missing required input/unsupported schema дают явный failure или предусмотренный gap |
| A08 | RUN-02 | Optional enrichment не становится обязательным prerequisite базового запроса |
| A09 | READ-01 | API readback не запускает новый анализ вместо чтения published products |
| A10 | SQL-04, CFG-01 | Нет догаданных JOIN pairs и unresolved placeholder substitution |
| A11 | BUILD-01 | Корректные delivery boundaries; отсутствует удалённый standalone reporting |
| A12 | PROFILE-04 | Отсутствие обязательного внешнего content даёт явную ошибку, а не packaged fallback |
| J01 | JAVA-01 | Declaration, inheritance, annotations и span; declared type не объявлен физической таблицей |
| J02 | JAVA-02 | Одинаковые type names в разных namespace дают ambiguity, не произвольный выбор |
| SC01 | SCHEMA-01 | Local ref, required, nullable/type variants, inline object |
| SC02 | SCHEMA-02 | Same-name schemas в разных файлах не склеены; external ref без поддержки не загружен |
| SQL01–SQL02 | SQL-01 | Один JOIN с двумя column pairs; фильтр константы не превращается в пару |
| SQL02 | SQL-02 | Range operators и роли сохранены |
| SQL03 | SQL-03 | USING даёт пару; CROSS JOIN подтверждён без придуманного ключа |
| SQL04 | SQL-04 | Unqualified ambiguity: partial и нет физического подтверждения |
| SQL05 | SQL-05 | CTE logical JOIN не становится physical JOIN |
| SQL06 | SQL-06 | Expression JOIN сохраняет выражение и зависимости, не разбивается на ложные equality edges |
| SQL07 | SQL-07 | INSERT target и recursive terminal origins сохраняют lineage и пробелы |
| CFG01 | CFG-01 | Только resolved binding с exact environment; иначе literal placeholder |
| API01 | API-01 | Exact path/method, required revision, filters, limits, response envelope |
| API02 | API-02 | Несколько страниц, page.total, пустая последняя страница, нет потери/дублирования records |
| API03 | API-03 | Capability missing vs empty, wrong revision, repeated/unknown query parameters |
| PROFILE01 | PROFILE-01 | Exact scope/artifacts/capabilities/fingerprints соответствуют revision |
| PROFILE02 | PROFILE-02 | Capability gating tools, а не разрешение по имени retrieval profile |
| PROFILE03 | PROFILE-03 | Embedded context не внешний HTTP tool; empty capabilities допускают только соответствующие безусловные tools |
| PROFILE04 | PROFILE-04 | Локализованный content и exact machine projection/fingerprint policy |
| Consumer JOIN | CONSUMER-01 | Все опубликованные JOIN pairs со статусами в CSV, без model-inferred pairs |
| Consumer declared | CONSUMER-02 | Search → exact object → field evidence в одной revision |

Дополнительно нужны publication failures: invalid bundle/descriptor, неверная base revision и partial failure. Повторная публикация и неизменность старой revision проверены в 0.3. Exact HTTP/CLI semantics не следует выводить из названий этих случаев: gap S04.

## Открытая reference validation SP-SDD-0.3

| Acceptance IDs | Исполненный probe | Остаток |
|---|---|---|
| REV-01 | duplicate_publish_idempotent; second_revision_distinct; old_revision_unchanged_after_new_publish | Invalid base/dependencies и atomic rejection |
| READ-01 | api_read_independent_of_producer_paths | Production deployment; отсутствие side effects других GET |
| JAVA-01 | java_three_types; java_four_fields; exact envelope/identity offline tests | Полный набор declarations/spans/ambiguity |
| SCHEMA-01/02 | schema_external_ref_gap; schema_partial_not_complete; exact local/inline refs | Cross-file collision и остальные providers |
| API-01/03 | 14 exact HTTP responses + JSON Schema validation; missing revision=422, latest=400, unknown=404 | Полная матрица filters/invalid limits/query validation |
| API-02 | eight_api_joins; pagination_unique_ids; 3 страницы | Пустая последняя страница и иные page sizes |
| SQL-06 | api_expression_links_preserved; context_projection_omits_expression_links | Независимые held-out expressions |
| PROFILE-01 | Profile/catalog read из реальной revision и schema validation | Полная consistency матрица capabilities/fingerprint |

Report: reviewer/PIPELINE_PROBES.json (50 checks). Все fixtures видимые; learner получает собственные examples, но не reference исходники, execution harness или reviewer inventories. Старый CONTRACT_INVENTORY.current_run относится к статическому экспортному проходу 0.1, не к этой диагностической публикации; его флаги не обновляются выдуманным high-level journey.

Anti-hardcoding: held-out cases изменяют имена/namespace/раскладку файлов, порядок declarations и размер страниц; expected results получаются независимо через canonical oracle. Метаморфические преобразования применяются только когда сохранение смысла доказано, а не предполагается. Не использовать scored cases в development или втором прогоне после раскрытия.
