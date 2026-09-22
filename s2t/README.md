# aisl-s2t 0.1.0a5

Consumer-owned deterministic S2T application over pinned public AISL evidence.

`aisl-s2t` lives in the separate `aisl-application` repository. It is not part of
AISL Core/KLC and must not write consumer policy back into AISL knowledge.

Current bounded scope: deterministic environment selection, primary/upstream source
collapse, canonical 26-column deterministic row assembly, and typed residual-gap
classification. LLM question generation/ranking is deliberately not part of this
version.

## Boundary

```text
AISL / Knowledge API / public artifacts
             ↓
        aisl-sdk / export
             ↓
           aisl-s2t
             ↓
 deterministic S2T + typed gaps
```

The application does not import Core, Runner or KLC, does not read AISL storage,
and does not read repository source.

## Environment policy v1

Environment choice is a deterministic S2T policy, not an AISL fact.

1. Explicit caller/input environment wins.
2. Otherwise `default_environment = production`.
3. Environment roles map to exact observed environment-scope identities supplied
   by caller/configuration/evidence.
4. Production is never inferred from schema names, cluster names, array order,
   `prod/prom` substrings or repository-specific naming conventions.
5. A placeholder resolves only when the selected environment yields exactly one
   mechanically observed candidate value.
6. An exact placeholder-valued candidate may be composed through one already-published
   environment binding in the selected scope (for example `outer -> ${inner} -> value`).
   Arbitrary template/expression evaluation is not performed.
7. One concrete literal candidate is deterministic without environment selection.
8. Multiple matching values or no matching value remain unresolved.
9. PA/deployment/non-production is selected only by explicit context.
10. Every decision retains resolution basis for audit.

CLI:

```bash
aisl-s2t resolve-environment \
  --gaps gaps.json \
  --environment-observations environment-observations.json \
  --policy environment-policy.json \
  --output environment-resolution.json
```

Use `--environment <role>` for an explicit override. Without it,
`default_environment` is used and defaults to `production`.

The output contains per-diagnostic decisions plus semantically deduplicated source
decisions. Several workflow contexts may describe the same source decision; a
resolved identity is accepted only when all resolved contexts agree. Conflicting
resolved identities remain ambiguous.

## Primary/upstream source policy v1

Current `sql-target-source-mapping/v2` distinguishes observed branch structure
(`branch_relation_name`) from the derived terminal driver relation
(`driver_relation_name`). S2T uses the producer-established driver as the primary
source. No file/path keywords are interpreted.

Rules:

1. A `resolved` current `driver_relation_name` is the primary source identity.
2. A `partial` driver relation is preserved literally when only an environment/
   placeholder dimension remains unresolved; the row retains an
   `UNRESOLVED_PLACEHOLDER` gap rather than losing the observed source table/field.
3. An `ambiguous` or `unresolved` current driver is never replaced by
   `branch_relation_name`.
4. Legacy serialized inputs that predate explicit driver status may still use
   `branch_relation_name` as the mechanically published primary identity.
5. Different producer-established driver identities remain separate S2T value-source rows.
6. Syntactically different templates that deterministically resolve to the same exact
   relation are deduplicated.
7. Non-primary roles such as lookup contributions are not folded into driver sources.

CLI:

```bash
aisl-s2t collapse-primary-sources \
  --mappings sql-target-source-mapping.json \
  --environment-resolution environment-resolution.json \
  --output primary-sources.json
```

## Deterministic builder + typed gaps v1

The builder consumes serialized **public AISL evidence only**. It does not discover
candidate sources from source code and does not rank ambiguous producers.

```bash
aisl-s2t build-deterministic \
  --mappings sql-target-source-mapping.json \
  --mapping-gaps sql-target-source-mapping-gaps.json \
  --environment-resolution environment-resolution.json \
  --target-fields explicit-target-fields.json \
  --column-usage-contexts column-usage-contexts.json \
  --system-id <system-id> \
  --revision-id <revision-id> \
  --csv-output deterministic-s2t.csv \
  --audit-output deterministic-s2t.audit.json
```

`--mapping-gaps`, `--environment-resolution`, `--target-fields`, and
`--column-usage-contexts` are optional. Target fields may come from explicit caller
scope or separately accepted public target evidence; the builder does not select
targets by naming convention. Column-usage contexts are raw public
`get_sql_column_usage_context` responses keyed by their published usage IDs.

Output rules:

1. CSV uses the existing `report/s2t/v1` 26-column contract exactly.
2. Every resolved primary branch becomes its own row. Multiple real value branches
   remain separate.
3. Lookup/enrichment never replaces a proven primary source. Lookup-only evidence
   leaves `T-src*` blank and is retained as `CONSUMER_CONVENTION` in the audit sidecar.
4. `driver_candidate`/`unknown` are never promoted to primary sources.
5. An unresolved upstream template is never replaced by a concrete downstream terminal.
6. `T-src-f-name` is filled only when the source field identity is explicitly present
   in public mapping evidence; matching target/source names are not assumed.
7. `T-src-f` accepts only explicitly linked, resolved, non-direct target expressions.
   Raw SQL text is not reinterpreted by this application.
8. Exact visible 26-column duplicates are removed; provenance is merged in the audit
   sidecar.
9. Observed target fields with unresolved source identity remain as truthful
   target-only CSV rows.
10. For an `ambiguous_unqualified` SQL usage, the optional public column-usage
    context may shrink the candidate set only by negative evidence: a relation is
    excluded when its output contract is `complete` and the referenced column is
    absent. Partial/unknown contracts survive. The consumer never selects a survivor
    and never promotes a single survivor to `T-src` unless AISL itself publishes that
    resolved source.

Typed residual categories currently emitted by the deterministic classifier use the
Task-23 taxonomy, including `UNRESOLVED_PLACEHOLDER`, `ENVIRONMENT_AMBIGUITY`,
`BOUNDED_PRODUCER_AMBIGUITY`, `CONSUMER_CONVENTION`, and
`INSUFFICIENT_EVIDENCE`. A bounded ambiguity is classified only from candidate
identities already published by AISL or from a deterministic survivor set over public
`get_sql_column_usage_context` facts using the complete-output-contract negative rule
above. Classification does **not** mean LLM eligibility and no candidate is ranked or
selected here.

The audit sidecar retains deterministic row provenance, mapping IDs, primary
relation templates, source public gap IDs, bounded candidate IDs, and gap counts.

## Tests

```bash
python -m pytest tests -q
```

The suite includes metamorphic input-order and file/path-rename checks, multiple
branch preservation, fail-closed primary-source cases, bounded-candidate gap
classification, ambiguous-unqualified survivor generation, and the exact 26-column
CSV contract. Production code contains no acceptance-corpus names or paths.


## Clean delivery

The reproducible clean-delivery owner is `tools/build-aisl-s2t-delivery.py`, following
the same project convention as Framework and Repository Inventory deliveries.

The delivery contains only install/runtime artifacts and metadata: one first-party
`aisl-s2t` wheel, manifest, versions, README and SHA-256 checksums. Source trees,
tests, build residue and third-party wheels are not included. Any declared third-party
dependencies are resolved by pip from the configured package index.

From the `s2t/` source directory inside a Git checkout:

```bash
python tools/build-aisl-s2t-delivery.py . ./delivery-out
```

For an unpacked/non-Git source tree, pass the exact owning repository identity:

```bash
python tools/build-aisl-s2t-delivery.py . ./delivery-out \
  --source-commit <COMMIT> \
  --source-tree <TREE>
```
