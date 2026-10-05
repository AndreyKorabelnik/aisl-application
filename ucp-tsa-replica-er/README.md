# UCP → TSA Replica ER

`aisl-ucp-tsa-replica-er` is a bounded external AISL consumer that projects the
published UCP declared model onto published TSA replica mappings.

It answers a specific consumer question:

> Which TSA replica tables correspond to UCP entities, what UCP-declared identity
> fields map to their replica columns, and which replica tables are related by
> mechanically resolved UCP type relationships?

## Evidence boundary

The application uses only pinned public AISL revisions:

1. UCP `code-declared-data-model` public dataset: types, effective fields,
   type annotations and resolved relationships;
2. TSA `logical-physical-mapping-evidence`: exact type→replica-table and
   field→replica-column mappings.

It does not parse raw source and does not read private Core/KLC/DuckDB state.

### Important key semantics

`key_replica_columns` means **the UCP-declared logical identity field** from a
supported UCP meta annotation, mapped mechanically to an exact TSA replica column.
For example `@MetaVersionedEntity(id="id", version="version")` gives the identity
field `id`; `version` is reported separately.

This is useful ER knowledge, but it is **not proof that the physical database has a
PRIMARY KEY constraint**. `physical_constraint_status` therefore remains
`not_observed` unless a future published revision provides independent DDL evidence.

Supported UCP identity annotations in v1:

- `MetaEntity(id=...)`;
- `MetaRootEntity(id=...)`;
- `MetaVersionedEntity(id=..., version=...)`;
- `MetaDictionary(code=...)`;
- `MetaVersionedDictionary(code=..., version=...)`.

Only literal annotation arguments are accepted; no field-name guessing is used.

### Important relationship semantics

A projected replica-table relationship is emitted only when:

- UCP publishes a resolved source-type → target-type relationship;
- both endpoint types have unique exact TSA entity mappings.

The emitted edge means only **UCP declared relationship projected onto exact TSA replica tables**. The application does **not** invent a physical FK or JOIN condition. UCP model
relationships alone do not prove a physical database foreign key, therefore
`physical_join_status=not_observed` in v1.

## Outputs

- structured JSON `ucp-tsa-replica-er/v1`;
- `tables.csv` with replica relations and mapped UCP identity keys;
- `relationships.csv` with UCP relationships projected onto exact replica tables;
- Mermaid flowchart for visual inspection. The chart deliberately does not assert
  ER cardinality or physical FK conditions that are not published.

## CLI

```bash
ucp-tsa-replica-er build \
  --aisl-base-url http://aisl-server:8080 \
  --ucp-system ucp-data-model \
  --ucp-revision rev-c39ad2888fc29779cf411bd9 \
  --tsa-system ucp-tsa-v4 \
  --tsa-revision rev-5a16127953b6774b18dd8268 \
  --output-json replica-model.json \
  --tables-csv replica-tables.csv \
  --relationships-csv replica-relationships.csv \
  --output-mermaid replica-model.mmd
```

To emit only the outgoing UCP object closure from one or more roots, repeat
`--root-object` with an exact FQCN or an unambiguous simple type name, for example:

```bash
  --root-object com.sbt.bm.ucp.retail.model.individual.Individual
```
