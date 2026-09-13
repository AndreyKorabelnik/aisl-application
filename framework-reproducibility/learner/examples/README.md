# Открытые примеры SP-SDD-0.3 / F4.95

`profile-sql.json`, `profile-declared.json`, `profile-empty.json` — точные результаты Integration Profile generator F4.95 на явно заданных синтетических context. Они проверяют генерацию, но не доказывают публикацию и API readback.

Empty capabilities не означает ноль tools: безусловный exact-read `get_knowledge_item` остаётся. Имя retrieval profile само по себе не предоставляет capability.

`sql-joins.reference.json`: 8 точных Core JOIN records для отдельного SQL-only repo, repo_id=sdd-synthetic; повторно получены на F4.95. `publication.reference.json` — exact standalone builder/validator output, не server import.

`java.reference.json`, `schema.reference.json` — точные envelopes для Sample.java и declared-openapi.json, repo_id=sdd-pilot. Structured-source пример проверяет declarations, не extraction HTTP endpoints.

`api-readback.reference.json` — 14 request/response примеров после реальных Core/KLC процессов и bundle import. В этом совместном repository три входа: Java, OpenAPI, SQL; repo_id=sdd-pilot. Не сравнивать его literal IDs с SQL-only repo_id=sdd-synthetic. Revision IDs принадлежат конкретному запуску; absolute temp paths не являются частью learner contract. Это открытые development vectors, не hidden acceptance.
