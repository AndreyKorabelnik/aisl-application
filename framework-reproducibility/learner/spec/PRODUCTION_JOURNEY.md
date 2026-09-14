# Производство и чтение knowledge: пилот

Статус: уточнение draft по наблюдению F4.103. Полный pack ещё не готов.

## Вход и выбор

Производство принимает system_id, выбранный Knowledge Profile, source repositories,
выделенный output path и timeout. SQL-пилот использует `sql-source-inventory-v1`
с одним repository; declared model — `data-model-v1` с workspace selection repositories.
Knowledge Profile и Integration Profile — разные контракты: первый выбирает
производимое knowledge, второй задаёт разрешённое потребление опубликованной revision.

Путь вывода должен быть отдельним дочерним каталогом разрешённого output root.
Недопустимый путь отклоняется явно (`unsafe_output_path`), без записи поверх source.
Политика Technology Extensions задаётся deployment-ом. Отсутствующая обязательная
extension не должна молча игнорироваться. Пилот с обычным Java/OpenAPI/SQL допускает
явную core-only policy без extensions.

## Результат производства

Успешный job завершает подготовку входов, планирование, выполнение и создание
self-contained publication bundle. Клиент не должен считать промежуточный output
готовой опубликованной revision. Bundle затем импортируется сервером; успешный
ответ содержит immutable revision_id. Повторный import того же bundle возвращает
`already_published` и тот же revision_id.

Внутренний порядок пакетов и устройство процессов свободны для реконструкции;
наблюдаемые состояния, ошибки, evidence и publication semantics должны сохраняться.

## Consumer journey

1. Получить Integration Profile `sql-analysis/v1` или `data-model/v1` для конкретных
   system_id/revision_id. Profile scope сохраняет эту revision.
2. Выполнять разрешённые публичные tools через их API binding с той же revision.
3. Для SQL собрать все страницы `/sql/joins`: count items согласован с page.total,
   IDs не дублируются между страницами; пустая последняя страница сохраняет total.
4. Для declared model найти объект, затем запросить detail по выданному object_id.
   Поля сохраняют source_ref и provenance; inherited field сохраняет is_inherited
   и inherited_depth. Declared relationship сохраняет target и resolution_status;
   она сама по себе не означает физический JOIN или business association.
5. Чтение после публикации работает без producer outputs и source repository.
   Нельзя повторно анализировать исходники для ответа на read-запрос.

Для проверенных GET: отсутствующий revision_id — 422; `latest` — 400;
неизвестный revision_id — 404; limit=0 — 422. Ответы должны соответствовать
публичным response schemas. Эти примеры не задают полный каталог ошибок.

Детерминированный consumer доказывает доступность данных. Способность DeepSeek
реализовать Framework по SDD требует отдельного specification-only эксперимента.
