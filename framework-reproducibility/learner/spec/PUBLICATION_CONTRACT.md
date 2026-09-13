# Producer-neutral публикация: descriptor и bundle

Статус 0.2. Builder/validator реально выполнены; правила server import и composition изучены по canonical owner, но не проверены живым сервером. Не смешивать эти уровни evidence.

## Канонизация и fingerprints

JSON для hash: UTF-8, object keys сортируются, без пробелов после `,` и `:`, Unicode не превращается в ASCII escape. Массивы не сортируются общим serializer. SHA-256 даёт 64 lowercase hex. Правила для exotic numbers/Unicode edge cases ещё требуют отдельного тестового корпуса; общее требование — валидный JSON.

Product `content_fingerprint` — hash всего product object без самого `content_fingerprint`. Descriptor `publication_fingerprint` — hash всего descriptor без самого fingerprint. Manifest `bundle_fingerprint` — аналогично всего manifest без самого fingerprint. Это три разных hash; hash ZIP и hash pretty JSON-файла также отличаются.

При записи descriptor/manifest в ZIP используется pretty JSON с indent=2, sorted keys, literal Unicode и финальным LF. Byte identity этого файла входит в manifest, а semantic fingerprint считается по компактной форме. Не подставлять один hash вместо другого.

## Descriptor `aisl_publication_descriptor/v1`

Обязательная структура builder output:

- `schema_version`, `producer` (`producer_ref`, `producer_contract_ref`), `system` (`system_id`, `display_name`);
- `base_revision_id`: exact ID либо null;
- непустой `products`;
- `publication_defaults`: boolean `activate`, sorted unique `labels`, JSON object `metadata`;
- `publication_fingerprint`.

Product содержит `artifact_id`, `model_kind`, `schema_version`, `product_slot_id`, `origin_kind=observed|derived`, producer refs, непустой `physical_artifacts`, capabilities, coverage, diagnostics, provenance, exact_dependency_product_ids, upstream_dependencies и content_fingerprint. `producer_operation_ref` опционален и отсутствует, если не задан.

Artifact IDs и slot IDs уникальны в публикации; physical roles уникальны внутри продукта. Capabilities и exact dependency IDs сортируются и дедуплицируются builder; готовый descriptor validator требует уже канонические списки. Self-dependency запрещена.

AISL identifier начинается ASCII буквой/цифрой, далее только ASCII буквы/цифры и `._:-`; длина 1–240. Schema/producer refs — непустой текст, не обязательно этот identifier pattern. Hash — 64 lowercase hex. Physical artifact задаёт role, safe relative member_path, sha256, non-negative byte_size, media_type, filename-basename и опциональный schema_version. Нельзя путать роль logical product и роль физического файла.

Upstream dependency либо `aisl_product` с точными system/revision/artifact/content fingerprint, либо `external_artifact` с absolute URI, SHA и media type (schema version опциональна). Reference на upstream не означает разрешения пересчитать его или взять latest.

## Bundle `aisl_publication_bundle/v3`

ZIP содержит `bundle-manifest.json`, `payload/publication-descriptor.json` и перечисленные physical payload files. Manifest имеет `schema_version`, `descriptor` (path, SHA, bytes, schema version), `members` (path, SHA, bytes) и bundle_fingerprint. `members` включает descriptor, но не сам manifest; поэтому member count результата builder на единицу меньше числа файлов ZIP.

Builder сортирует products по `(product_slot_id, artifact_id)`, artifacts — по role. Индексы в путях начинаются с 1 и имеют минимум 3 цифры. Формат: `payload/products/{product_index}-{slug(artifact_id)}/{artifact_index}-{slug(role)}-{slug(filename)}`. Slug заменяет последовательности символов вне ASCII letters/digits/`._-` на `_`, обрезает `._-` по краям, использует `item` для пустого результата и максимум 80 символов. Отсортированные ZIP entries имеют timestamp 1980-01-01 00:00:00, file mode 100644 и deflate. Функциональная совместимость не требует идентичного deflate потока иной ZIP-библиотеки; member bytes и manifest integrity требуют точности.

Builder использует временный ZIP и замену target после успешной записи. Это не доказательство транзакционности server publication. Абсолютные локальные пути не входят в descriptor/manifest.

## Server validation и revision composition

Обнаруженные по коду ошибки import: manifest missing/invalid/schema unsupported — 400; manifest fingerprint mismatch — 409; unsafe member path — 400; duplicate member metadata — 409; ZIP member set mismatch — 409; symlink payload — 400; member SHA/size mismatch — 409. Точные codes приведены в reviewer report; полный HTTP error oracle ещё нужен.

Descriptor и publication request должны совпадать по system, producer, publication fingerprint, base revision, labels/metadata, набору продуктов, semantic fields и physical identities. Отличия приводят к 409 с конкретным code, а не молча нормализуются.

При заданном base revision сервер берёт только revision той же system. Unknown base: 409 `publication_base_revision_unknown`. Продукты новых slot IDs добавляются; продукты уже существующих slot IDs заменяются; остальные продукты base удерживаются. Результат сортируется по `(product_slot_id, artifact_id)`. Duplicate artifact IDs и отсутствующие exact dependencies — 409. Capabilities revision — sorted union опубликованных продуктов. Upstream AISL dependency проверяется по exact revision и content fingerprint.

`base_revision_id` не следует трактовать как требование «равен текущей active revision»: в рассмотренном composition path такого условия нет. CAS storage означает content-addressed storage; compare-and-swap active head — другое утверждение, не подтверждённое этим контрактом.

Revision ID: `rev-` + первые 24 hex SHA-256 compact canonical JSON объекта с `system_id`, полным `publication` request object, `publication_descriptor_sha256`, sorted unique labels, metadata, и base_revision_id только если non-null. `activate` в этом материале отсутствует. Exact shape publication request задан публичной OpenAPI schema. Повторная публикация того же revision ID возвращает существующую revision; activation может менять active selection, но не состав уже опубликованных продуктов.

Pinned reads: пустой revision ID — 400 `revision_id_required`; literal `active`/`latest` — 400 `invalid_revision_binding`; неизвестная exact revision — 404 `revision_not_found`. Active сначала разрешается отдельной операцией; knowledge query получает exact ID.

## Исполненные проверки

`../examples/publication.reference.json` содержит exact descriptor/manifest/physical identity для одного синтетического продукта, bytes payload и errors пяти негативных builder/validator cases. Повторная сборка дала идентичные ZIP bytes в одной среде. Это ещё не полный publish/readback и не schema для всех Knowledge Products.
