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

## Verified V3 experiment (Task 53 final gate)

- AISL system: `profile-fl-v3-prototype`.
- Existing locally published pinned revision: `rev-d2897d0840cbdaaf453d39ef`.
- Input: 28 V3 SQL files only (no legacy code).
- **28 / 28 SQL restored via the real HTTP Knowledge API; 28 / 28 structurally match independently supplied V3 reference SQL.** Zero unresolved queries.
- The bounded generic Knowledge API fix exposes `generator_expression` and `generator_wrapper_alias` already saved in immutable `sql_relation` knowledge; no change to original observed evidence or revision identity was necessary.
- SQL with a single unambiguous `LATERAL VIEW EXPLODE` is now reconstructable. Multiple generated aliases or generator/JOIN ordering ambiguity remain fail-closed; the current research corpus contains neither case.
- This is a structural replay test, not data parity, production readiness or a review of V3 business hypotheses.

## Design boundaries

- Uses the bounded public Knowledge API query-context projection fix; AISL revisions remain immutable.
- The consumer accepts a pinned system/revision and remains read-only.
- Source-file paths are used **only as published result names**; expressions come from public SQL knowledge.
- A product relation named `final` or `raw_events` is not treated as a physical staging table.
- Unknown CTE/set scope, ambiguous query, incomplete projection, unresolved JOIN or generated-source expression = failure with explicit diagnostic.

## Reproduction

The attached `publication_bundle/*.aisl.zip` is the self-contained Producer output. Import it with stock `knowledge-api import`, then run the command above using the imported revision ID. The original V3 source code is independent acceptance reference and is not needed for restoration.
