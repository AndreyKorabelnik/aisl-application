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

## A5: published cross-revision and execution-context access

`get_dependencies` now reuses the published **Task 46** `aisl-data-model-datamart-lineage` consumer library for a **selected exact TSA replica column** and returns its paths separately in `cross_revision_lineage`. Pass both `--model-system/--model-revision` and `--replica-system/--replica-revision`, in addition to the Profile FL `--system/--revision`. For example:

```shell
# Replace the URL with the actual AISL Knowledge API host in the target environment.
aisldm --base-url http://localhost:8080 \
  --system datamart_profile_fl --revision rev-150997201317410ecf2dd2ef \
  --model-system ucp-data-model --model-revision rev-c39ad2888fc29779cf411bd9 \
  --replica-system ucp-tsa-v4 --replica-revision rev-5a16127953b6774b18dd8268 \
  get_dependencies --relation com_sbt_bm_ucp_retail_model_individual_birthdate --column value
```

The exact `column` is required for Task 46 source-to-target paths. If omitted, `cross_revision_available_fields` provides published TSA-to-UCP field mappings and `cross_revision_lineage_status=requires_exact_replica_column`. Mapping ambiguity or missing publication is explicit. Task 46 physical-target ambiguities **remain ambiguous**. For all original path provenance and segments, pass `--include-cross-revision-details`. No Task 46 algorithm is copied into this package.

For SQL target lineage, the ordinary reply is a **20-edge identity/summary page**, not an unbounded multi-megabyte LLM context. `edge_page` reports the exact total, offset, and `next_offset`. Use `--edge-offset`, `--edge-limit`, and `--include-edge-details` to read *every* original lineage edge with transformations and provenance, one page at a time. Pagination of the read response does not silently truncate the Knowledge API source retrieval.

Execution context is an explicit opt-in with `--include-execution-context`: exact published query IDs and workflow files are used to retrieve SQL JOINs, materializations, workflow bindings, and reachable-file observations. The response includes category counts and limited samples, with the public API route and exact selection keys to retrieve the full records. These contexts are **not** additional proved data-flow edges.

CTL associations require an **explicit CTL entity ID**, e.g. `--ctl-entity-id 935120601`. The tool looks up the unique published CTL product and joins CTL flow-to-entity records by **exact CTL entity ID**. It does not assume the published CTL entity and SQL physical target with different schema names are the same object. No Topology product is manufactured when it is absent from the selected revisions; other revisions are not implicitly inspected.

A5 integration is consumer-side only. It does not parse source, infer new intersystem mappings, upgrade logical relations into physical JOINs, or run an LLM. The Task 34 Discovery/Tantivy HTTP search endpoint remains a separate pending integration.

## A6: cross-revision lineage and provenance routed by purpose

`get_attribute_lineage` retrieves the original, already published SQL target lineage
and, for an exact TSA replica field in a pinned UCP/TSA pair, the accepted Task46
cross-revision UCP→TSA→datamart lineage. It reuses the same deterministic composer
as `get_dependencies`, without SQL parsing or inferred correspondence.

`get_evidence --relation <replica> --column <field> --evidence-source task46 --record-index 0`
retrieves the full Task46 path and `provenance_json` for one zero-based branch.
Use `--evidence-source task49 --record-index 0` for a projected declared
UCP/TSA relationship; it is explicitly **not** proof of a physical SQL JOIN/FK.
Default SQL evidence is now paged (20 entries) to avoid unbounded weak-LLM payloads.
The default `get_attribute_lineage` SQL projection has 20 compact rows with
`sql_page.next_offset`, and supports `--sql-offset`, `--sql-limit`,
`--include-sql-details` to page through every original published row.
The zero-based record index is scoped to the same immutable revisions, relation,
column, and source family; it is not an AISL published object ID.
