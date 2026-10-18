# AISL DataMarts Knowledge Tools — research alpha

A single tool catalog for one LLM (GLM) using **published, pinned** AISL revisions. This package does not contain a second LLM, an application-specific knowledge base, source-code parsers, or manually curated formulas.

## Search dependencies

- **SQLite FTS5**, an upstream-maintained full-text engine included in supported SQLite builds. Its **trigram** tokenizer supports substring matching in underscored SQL identifiers.
- **RapidFuzz >=3.14,<4**, third-party MIT-licensed matching/ranking library. Suggested fuzzy names **do not** prove entity identity.

The FTS index is **in memory and rebuilt from public Knowledge API** SQL relations and optional declared-model / TSA observed mapping records; it is not a durable or authoritative knowledge store. No handwritten fuzzy algorithms or tokenizers.

## Installation

```sh
python -m pip install ./datamarts-knowledge-tools
```

## Tools

`search_objects`, `find_change_locations`, `get_dependencies`, `get_object_details`, `get_attribute_lineage`, `get_calculation_logic`, `get_evidence`. One level of tool access, no task template and no fixed prompts. GLM decides which operation to use, and can call tools repeatedly.

Machine-readable tool descriptions:

```sh
aisldm tools-json
```

Example against a running AISL server with an already imported revision:

```sh
aisldm --base-url http://127.0.0.1:8080 --system datamart-profile-fl-gate0-20261017 --revision rev-54f4efa0fc7278fc9a606465 search_objects --query birth_dt

aisldm --system datamart-profile-fl-gate0-20261017 --revision rev-54f4efa0fc7278fc9a606465 get_attribute_lineage --relation epk_client --column birth_dt

aisldm --system datamart-profile-fl-gate0-20261017 --revision rev-54f4efa0fc7278fc9a606465 find_change_locations --relation epk_client --column birth_dt
```

## Proof and limitations

- `get_dependencies`: published upstream SQL target-column lineage **plus downstream target discovery candidates**. Candidate targets are not asserted as confirmed lineage edges. The API's reported gaps remain visible.
- `find_change_locations`: strictly SQL files found in evidence, marked as **candidates**. Workflow/config files may also be needed. The application never claims a complete edit plan.
- `get_calculation_logic`: exact public query context; requires a published `query_id` and `repo_id`, returned in evidence or lineage.
- `search_objects`: indexes SQL relation/field records and, when explicitly configured, UCP declared model `types`/`fields` and TSA logical-physical mapping record sets. It performs exact and fuzzy candidate discovery, **not** automatic cross-revision semantic mapping. Inventory is outside this alpha scope; all revisions must be pinned.
- A syntactically successful search/lineage response never certifies Spark execution, business equivalence, or live deployed inventory.
- `get_evidence` follows existing published evidence identifiers; raw source files are not read.
- There are no two access modes, no required task description, and no duplicate Knowledge Layer.

Acceptance: deterministic tests 10/10 PASS; full local AISL Server real HTTP E2E 10/10 PASS with pinned revisions. GLM provider invocation was not executed: model access is not configured in the test environment. End-to-end exhaustive replica graph coverage is not proven.


## Optional multi-revision search

For queries spanning physical TSA replicas and logical source models, add the pinned
revision flags to any `aisldm` invocation:

```sh
--model-system ucp-data-model --model-revision rev-c39ad2888fc29779cf411bd9 \
--replica-system ucp-tsa-v4 --replica-revision rev-5a16127953b6774b18dd8268
```

`search_objects` indexes **only observed/public** declared types/fields and
physical replica mappings from those revisions. Every result carries its
`system_id`, `revision_id`, `object_id`, `source` and available provenance.
No names are silently mapped across revisions. `get_object_details` optionally
accepts `--object-id` to disambiguate search results.

`get_dependencies` now pages all target-candidates at the API's maximum
100 records per page. Downstream candidates are explicitly not confirmed edges.

## LLM self-check A3 (2026-10-17)

A real local AISL Server with pinned UCP / TSA / Profile FL bundles exposed
three model-facing usability problems in A2:

1. `/sql/target-candidates` returns a broad discovery pool (110 entries even
   for an unknown relation). `get_dependencies` now exposes ONLY candidates
   carrying exact published `source_relation_matches`. These are still NOT
   confirmed lineage edges. `discovery_pool_count` discloses the original pool.
   When `column` is specified, relation-only candidates do not prove a field link.
2. SQL search records sometimes have empty publisher `object_id`.
   `search_objects` returns a deterministic `selection_ref`; pass it as
   `selection_ref_id` to `get_object_details`. This digest identifies exactly
   one record in a pinned search projection; it is **not** a published semantic
   object ID and does not resolve physical table ambiguity.
3. `get_calculation_logic` may return many projections. An optional exact
   `output_name` returns the selected-scope projection with source identity
   and caveats; omit it to obtain the complete public query context.
   A final SQL CAST does not establish full upstream calculation lineage.

`get_dependencies` defaults to a compact projection of **every exact
source-matched candidate**, preserving evidence matches; specify
`include_candidate_details=true` for the same tool to return the original full
public candidate metadata. This is one tool catalog, not two access tiers.

**Unresolved:** generic, evidence-complete graph of any replica across all
selected revisions; controlled GLM provider E2E; broader CTL/Inventory flows.
This alpha does not claim any of these capabilities as accepted.

## Task 49 UCP/TSA Replica ER reuse (0.1.0a4)

When both `--model-system/--model-revision` and `--replica-system/--replica-revision`
are pinned, `get_dependencies` additionally returns `replica_logical_relationships`
for an exactly observed TSA replica table. This is computed once per process and
revision pair using the published `aisl-ucp-tsa-replica-er` package and its
public AISL API loader; it is **not** a new graph or mapping resolver. The full
model is built (not a root-only outgoing closure), then indexed for both incoming
and outgoing declared relationships. For `get_object_details` on a TSA replica,
Task 49 also contributes logical identity columns, UCP field descriptions and
explicit physical-key gaps.

`replica_logical_relationships` is separate from SQL `edges` and downstream
SQL candidates. UCP-declared relationships projected onto exact TSA mappings
are **not** database FK/PK constraints, SQL joins, data movement or attribute
lineage. A column-scoped question can show these relations as contextual only,
with `column_evidence_status=not_proven_by_logical_relationship`. Unsupported
or unavailable UCP/TSA projection is declared explicitly; absence of an
exact observed TSA replica match avoids a full Task 49 model load.

Task 49 published package version: `aisl-ucp-tsa-replica-er==0.1.0a4`
(or compatible 0.1.0a4+). It depends on the existing `aisl-sdk` API client.
No source repository is read at runtime. This integration can run before the
separately planned common Discovery/Tantivy search endpoint is implemented.
