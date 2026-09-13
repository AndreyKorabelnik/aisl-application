# Java и OpenAPI: контракт открытого среза

Статус: уточнение SDD SP-SDD-0.3. Открытые точные примеры — `../examples/java.reference.json` и `schema.reference.json`; входы — `Sample.java`, `declared-openapi.json`, repository ID `sdd-pilot`. Это данные для разработки, не скрытый acceptance. Перечисленные ниже алгоритмы описывают эталонную идентичность; допустимое альтернативное remapping регулируется EQUIVALENCE, не предполагается автоматически.

## Evidence envelope

Java: `artifact_kind=java-type-structure-evidence`, `schema_version=java-type-structure-evidence/v1`. OpenAPI: `artifact_kind=schema-declaration-evidence`, `schema_version=schema-declaration-evidence/v1`. Обязательные верхнеуровневые разделы показаны в exact примерах: `contract_version`, `artifact_kind`, `schema_version`, `producer`, `source_snapshot`, `parameters`, `coverage`, `diagnostics`, `provenance`, `payload`, `content_fingerprint`, `artifact_id`.

`source_snapshot.revision=null` означает отсутствие исходной VCS revision; это не AISL revision и не latest. Snapshot содержит отдельный source ID, scope, file count и fingerprint. `provider_status=implemented` сообщает поддержку провайдера, а не полноту конкретного результата.

Java payload содержит семь массивов: source_units, type_declarations, field_declarations, inheritance_declarations, annotation_declarations, type_reference_observations, enum_constant_declarations. Schema payload содержит пять: source_units, schema_declarations, field_declarations, schema_reference_observations, composition_observations. Пустой массив сохраняется. Полные nested schemas и правила всех языковых вариантов ещё требуют дополнения; нельзя выводить их только из одного примера.

## Java: наблюдаемые правила

Парсинг структурный, с сохранением объявления типа, package/FQCN, вложенности, modifiers, полей, наследования, аннотаций и source spans. Нельзя заменять парсер регулярными выражениями или превращать объявленный класс в физическую SQL-таблицу по сходству имён.

У открытого входа 3 типа, 4 собственных поля, 1 extends и 1 аннотация. `Customer extends BaseEntity` разрешается как `same_package`; поле `Customer.profile` ссылается на объявленный `Profile`. `String` не создаёт вымышленного локального типа. `@Deprecated` сохраняется как annotation с `resolution_status=unresolved`, а не удаляется и не считается локально подтверждённой.

Параметры этого Java evidence: `language=java`, `include_test_sources=true`, `record_limit=null`. `source_set` определяется по пути: test/src-test сегменты имеют приоритет над main; точные шаблоны `/src/test/` или `/test/` → test, `/src/main/` или `/main/` → main, иначе unknown. Путь нормализуется на `/` и lower-case только для классификации; identity использует исходный relative POSIX path.

Source ref содержит `repository_relative_path`, 1-based `line_start`, `line_end`, `extractor=java_tree_sitter`. Для поля с аннотацией начало span может включать строку аннотации (в примере nickname: 8–9). Не сводить span к строке идентификатора.

Java coverage: отсутствие Java файлов → not_applicable; ошибки чтения/парсинга или неподдержанное объявление → partial; иначе complete. Неопределённая ссылка сама по себе не обязана понижать Java coverage; она сохраняет собственный resolution status и соответствующие счётчики. Coverage complete не означает, что разрешены все аннотации и внешние типы.

## OpenAPI: наблюдаемые правила

Документ определяется по parsed root marker OpenAPI/Swagger, не только по расширению. В выбранном примере OpenAPI 3.1.0 имеет два именованных schema и один inline object: всего 3 schema и 7 полей.

- `required` определяется принадлежностью имени поля к required массива владельца; `nullable` — отдельное свойство. Nullable true при `nullable:true` или включении `null` в type variants. Одно не выводится из другого.
- Local `#/components/schemas/Profile` разрешается на schema текущего документа. Совпадение имени с Java Profile не является основанием склеить декларации.
- Inline object получает собственные schema ID, parent/field связи и locator; его поля не теряются и не переносятся произвольно на родителя.
- External `$ref` сохраняется literal и unresolved; появляется `external_schema_reference_not_resolved`. Нельзя молча загружать URL или подставлять догаданную schema.
- Source ref OpenAPI имеет `extractor=openapi_schema_scanner`, meaningful JSON-pointer `locator`, а line_start/line_end в этом контракте равны 1. Это не утверждение точной физической строки декларации.
- При отсутствии structured source coverage not_applicable; parse failure либо unresolved schema reference → partial. В примере unresolved reference ровно 1, coverage partial, несмотря на успешное исполнение producer.

## Идентичность и fingerprint

Обозначим H(X) = lowercase SHA-256 от UTF-8 X. `ID(prefix, parts...) = prefix + '_' + H(join(parts, U+001F))[:24]`. Каждый part преобразуется в строку; отсутствующий/ложный part — пустая строка. Не использовать пробел, `|` или JSON вместо U+001F.

| Объект | Prefix | Parts в порядке |
|---|---|---|
| Java source unit | java_source_unit | relative path |
| Java type | java_type | relative path, declaration line_start, simple name, type kind |
| Java field | java_field | relative path, owner type ID, field name, declaration line_start |
| Java inheritance | java_inheritance | relative path, subtype ID, extends/implements, declared expression |
| Java annotation | java_annotation | relative path, target kind, target ID, annotation line_start, raw annotation text |
| Java field type reference | java_type_ref | relative path, field ID, referenced token, field line_start |
| OpenAPI source unit | schema_source_unit | relative path |
| OpenAPI declaration | declared_schema | relative path, locator, schema name |
| OpenAPI field | schema_field | relative path, owner schema ID, locator, field name |
| OpenAPI explicit reference | schema_ref | relative path, owner kind, owner ID, role, literal ref, locator |

Inline-reference IDs имеют отдельную последовательность parts (relative path, field ID, inline role, inline schema ID), поэтому не следует применять explicit-reference формулу ко всем строкам. Enum, composition и все остальные языковые варианты должны быть специфицированы перед включением в scored scope.

JSON fingerprint вычисляется после сортировки keys, без пробелов (`separators=(',', ':')`), с Unicode без ASCII escaping, UTF-8; порядок массивов сохраняется. Evidence content fingerprint включает весь envelope кроме artifact_id и самого content_fingerprint. Java artifact ID: `java_type_structure_` + первые 24 hex fingerprint. Schema artifact ID: `ID('schema-declaration-evidence', repo_id, content_fingerprint)` — это другая формула.

Snapshot fingerprint материал: `{source_id, scope, files}`; каждый file содержит `{path, sha256, bytes}` с хешем исходных байтов. Java scope `java_source_files`, schema scope `declared_schema_contracts`. Это не хеш всего repository и не content fingerprint envelope. Exact примеры являются проверочными векторами для обеих формул.

## После materialization

В открытом совместном Java/OpenAPI входе declared model имеет 6 типов, 11 собственных field declarations, 12 effective fields (одно унаследованное), 3 relationships и 1 model gap. Одинаково названные Java/OpenAPI Customer и Profile остаются разными типами. Complete build означает успешное построение модели, а не исчезновение gap из evidence. Значения summary и список 6 объектов доступны в `api-readback.reference.json`.

Ограничение этой версии: это не полная specification алгоритмов candidate matching, multiple inheritance, annotation expression resolution или всех providers JSON Schema/Proto/XSD. Эти ветви не объявляются воспроизведёнными по результату данного примера.
