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
