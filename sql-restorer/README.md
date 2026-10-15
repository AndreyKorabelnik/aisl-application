# AISL SQL Restoration — external consumer prototype

This application reconstructs review SQL **only from the public, immutable-revision-pinned AISL Knowledge API**.

It does **not** read the original SQL source, the AISL DuckDB artifacts, or `payload_json`; no code of the original `datamart_profile_fl` is required on the consumer side.

## Usage

```bash
python -m pip install 'httpx>=0.27' 'sqlglot>=30'
python aisl_sql_restore.py \
  --api-url http://127.0.0.1:8080 \
  --system-id profile-fl-v3-prototype \
  --revision-id rev-d2897d0840cbdaaf453d39ef \
  --repo-id v3_source \
  --output-dir ./restored-sql
```

Arguments are exact runtime inputs. On another AISL catalog import the returned revision ID may differ; use the ID from `knowledge-api import` output. `active` and `latest` are rejected.

The app discovers SQL query IDs from the public `sql/relations` endpoint, resolves each query and child scope with `sql/query-context`, composes CTEs, set operations, joins, projections and filters, and saves syntactically parsed Spark SQL. Output `restoration_report.json` contains statuses and SHA-256. An unresolved scope causes an explicit diagnostic and **no SQL** for that target. Nonzero exit code indicates unresolved results.

## Real V3 experiment

- AISL system: `profile-fl-v3-prototype`.
- Locally published revision: `rev-d2897d0840cbdaaf453d39ef`.
- Input: 28 V3 SQL files only (no legacy code).
- `27 / 28` SQL queries reconstructed; independent AST comparison with reference V3, ignoring SQL comments, unquoted identifier case and equivalent `JOIN`/`INNER JOIN`: `27 / 27` reconstructed SQL structurally matches.
- `t_client_link_dzo.sql` remains unresolved. The current public query-context exposes the **generated alias** `uid` but not the `LATERAL VIEW EXPLODE(SPLIT(p.ucpids, ';'))` expression. Generating an incomplete SELECT would be misleading. This is a MATERIAL_SEMANTIC_GAP in the published consumer view; a generic Framework improvement would be needed for full replay.
- These comparisons test SQL structural preservation, not data parity, production portability, or correctness of the V3 business hypotheses.

## Design boundaries

- Framework and AISL remain unmodified.
- The consumer accepts a pinned system/revision and remains read-only.
- Source-file paths are used **only as published result names**; expressions come from public SQL knowledge.
- A product relation named `final` or `raw_events` is not treated as a physical staging table.
- Unknown CTE/set scope, ambiguous query, incomplete projection, unresolved JOIN or generated-source expression = failure with explicit diagnostic.

## Reproduction

The attached `publication_bundle/*.aisl.zip` is the self-contained Producer output. Import it with stock `knowledge-api import`, then run the command above using the imported revision ID. The original V3 source code is independent acceptance reference and is not needed for restoration.
