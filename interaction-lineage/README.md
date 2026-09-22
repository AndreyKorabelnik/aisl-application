# AISL Interaction Lineage

Consumer-owned deterministic composition of one `repository-topology/v4` edge with
repository-local lineage from exact pinned AISL revisions.

MVP invariant:

- `build` reads Repository Topology and the public AISL Knowledge API only;
- `build` never reads source repositories and never invokes analysis;
- topology owns the repository/transport edge;
- AISL owns repository-local direct value flow and bounded path traversal;
- the application does not rediscover topology, parse code, infer renames, or create a
  second lineage engine;
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

## Prepare

`prepare` is the only source-reading mode. It does not implement Git acquisition or a
second producer pipeline. It reuses the existing Knowledge Control Plane source registry
and freshness path:

`registered remote Git -> resolve current HEAD -> immutable commit snapshot -> pinned checkout -> Runner -> AISL publication bundle`.

The publication bundle is imported by the existing canonical `knowledge-api import`
command. For this MVP, `prepare` therefore runs in an environment where that admin CLI
is configured for the same AISL Server storage that `--aisl-base-url` exposes. A remote
HTTP bundle-import API is deliberately not invented by this application.

```bash
interaction-lineage prepare \
  --topology topology.json \
  --edge-id repository_edge_... \
  --aisl-base-url http://127.0.0.1:8080 \
  --kcp-base-url http://127.0.0.1:8000 \
  --output preparation.json
```

Repository source identity is resolved only from exact KCP
`metadata.analysis_repository_id`; names/similarity are not used. Repositories prepared
without a pre-existing AISL binding use the topology `repository_id` as the stable AISL
`system_id`. The preparation output embeds exact `interaction-lineage-aisl-bindings/v1`
bindings and can be passed directly back as `--bindings preparation.json` to `check` or
`build`.

The first MVP recipe prepares only the already-existing `attribute-lineage` Knowledge
Product (`repository-value-flow`, `workspace.attribute-path-resolver`). SQL and
persistence enrichment stay outside this first `/cpcGet` acceptance and are reconsidered
only after the mandatory STOP/REASSESS.

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
role
start_attribute
source_repository
source_origin
source_transformation
crossing_attribute
transport
target_repository
target_transformation
target_destination
gap
full_attribute_path
```

`crossing_attribute` is the exact topology transport field. `start_attribute`,
transformations, destinations and gaps are projected only from the already-published
journey evidence. Technical anchor-selection and crossing-basis fields stay in the JSON
and are intentionally omitted from the human CSV.

