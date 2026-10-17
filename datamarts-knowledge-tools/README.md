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
