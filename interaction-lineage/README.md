# AISL Interaction Lineage

Consumer-owned deterministic composition of one `repository-topology/v4` edge with
repository-local lineage from exact pinned AISL revisions.

Architecture invariant:

- `build` reads Repository Topology and exact pinned public AISL revisions only;
- `build` never reads source repositories and never invokes analysis;
- topology owns the repository/transport edge;
- each AISL revision owns repository-local observed/derived knowledge for one primary
  analyzed source, plus mechanically required dependency evidence for that revision;
- Interaction Lineage owns only the task-specific composition across those independent
  pinned revisions;
- revision discovery/binding is an upstream responsibility. `build` and `check` never
  infer `system_id` or `revision_id` from repository names;
- the application does not rediscover topology, parse code, infer renames, synthesize
  language-specific accessor facts, or create a second lineage engine;
- ambiguity and missing evidence remain typed gaps.

## Bindings

`build` requires an explicit deterministic binding file:

```json
{
  "schema_version": "interaction-lineage-aisl-bindings/v1",
  "repositories": [
    {
      "repository_id": "example-repo",
      "system_id": "example-system",
      "revision_id": "revision_123"
    }
  ]
}
```

`revision_id` must be an exact immutable revision, never `active` or `latest`.

`selected_repo_ids`, when present, are revision-internal evidence scope only (for example
a mechanically prepared Maven/source dependency needed to understand the primary
repository revision). They are not a mechanism for combining independent system
revisions. Cross-revision composition is performed by this application over separate
explicit bindings.

## Check

`check` is read-only. It validates the exact pinned revisions from the binding file,
requires the published `workspace.attribute-path-resolver` capability, and probes the
selected topology edge's boundary anchors through the same public resolver used by
`build`. Missing server/revision/capability/anchor state is returned as
`interaction-lineage-readiness/v1`; no source acquisition or analysis is attempted.

```bash
interaction-lineage check \
  --topology topology.json \
  --edge-id repository_edge_... \
  --bindings bindings.json \
  --aisl-base-url http://127.0.0.1:8080 \
  --output readiness.json
```

## Build

```bash
interaction-lineage build \
  --topology topology.json \
  --edge-id repository_edge_... \
  --bindings bindings.json \
  --aisl-base-url http://127.0.0.1:8080 \
  --output lineage.json
```

The output contract is `interaction-attribute-lineage/v1`.

## Prepare (transitional lifecycle)

`prepare` is retained only because the current accepted production journey still needs a
generic Framework/KCP preparation entry point before exact pinned bindings exist. It is
**not** the target ownership boundary for Interaction Lineage.

The target lifecycle is:

`Unified AISL Discovery / generic preparation -> exact pinned bindings -> check -> build`.

Until that upstream discovery/preparation path is available for this journey, `prepare`
continues to reuse the existing Knowledge Control Plane source registry and freshness
path rather than implementing Git/Nexus/source analysis locally:

`registered remote Git -> resolve current HEAD -> immutable commit snapshot -> pinned checkout -> Runner -> AISL publication bundle`.

```bash
interaction-lineage prepare \
  --topology topology.json \
  --edge-id repository_edge_... \
  --aisl-base-url http://127.0.0.1:8080 \
  --kcp-base-url http://127.0.0.1:8000 \
  --output preparation.json
```

The historical bootstrap rule that assigns `system_id = repository_id` when no binding
exists remains a **transitional compatibility behavior only**. It must be removed when
Unified AISL Discovery supplies the exact repository -> system/revision binding; new
consumer logic must not depend on that naming equality.

For already pinned revisions, preparation may still request mechanically required
external package/source evidence (for example Nexus/Maven dependencies) through the
generic Framework path. Such dependencies remain evidence of the primary revision; they
do not become independent system revisions or application-owned source knowledge.

The preparation output embeds exact `interaction-lineage-aisl-bindings/v1` bindings and
can be passed to `check` or `build`. Interaction Lineage itself owns no Git/Nexus client,
source parser, repository discovery heuristic, or publication implementation.

## Human CSV

The canonical result remains `interaction-attribute-lineage/v1` JSON. A compact
human-readable CSV can be rendered deterministically from that JSON without calling
AISL Server or KCP:

```bash
interaction-lineage csv \
  --input lineage.json \
  --output lineage.csv
```

The CSV is a projection only; it creates no new lineage claims. One row represents one
interaction attribute journey and is rendered in actual data-flow direction. The columns
are:

```text
interaction
role
producer_repository
producer_attribute
crossing_attribute
consumer_repository
consumer_attribute
gap
full_attribute_path
```

`producer_attribute` is the normalized local origin before the transport crossing when
one is mechanically resolved. `crossing_attribute` is the exact topology transport
field. `consumer_attribute` is the deepest mechanically proven meaningful semantic
consumer available from the published target-side evidence; it is not limited to the
first technical node after the crossing. An unresolved producer/consumer anchor is left
empty and described in `gap`. Human `gap` values are rendered in Russian while
`full_attribute_path` intentionally keeps the original machine gap code for audit and
cross-reference with the canonical JSON. Detailed operations, transformations, branch
provenance, confidence and anchor-selection evidence remain in the canonical JSON and
are intentionally not duplicated as separate human CSV columns.

