# AISL Data Model → Datamart Lineage

Bounded deterministic consumer for Task 46.

It composes three independently pinned public AISL revisions:

1. source declared data model;
2. TSA logical→replica observed mapping;
3. datamart repository-local SQL lineage.

It does not parse raw source and does not implement SQL lineage. Cross-revision matching is intentionally bounded: exact FQCN/field, exact replica relation, and anchored `_hist`/`_delta` representations only.

## CLI

```bash
data-model-datamart-lineage build \
  --aisl-base-url http://127.0.0.1:8080 \
  --source-system ucp-data-model \
  --source-revision <revision> \
  --bridge-system ucp-tsa-v4 \
  --bridge-revision <revision> \
  --target-system datamart_profile_fl \
  --target-revision <revision> \
  --source-object com.sbt.bm.ucp.retail.model.individual.BirthDate \
  --source-field value \
  --output birthdate.csv
```


`--source-field` is optional. When omitted, the command attempts all declared fields of the exact selected source object and preserves confirmed branches, explicit gaps, and ambiguities in the same CSV.

The CSV is a consumer projection, not a new knowledge owner. It includes:

- `relation_path`: source→target relation/stage path resolved through public relation-materialization records;
- `lineage_depth`: public recursive lineage depth;
- `transformation_path`: source→target transformation expressions;
- `path_segments_json`: structured UCP / TSA / Profile FL segments with raw lineage and materialization evidence;
- `provenance_json`: revision-local evidence, target resolution, candidates, and gaps.

A ranked physical target recommendation may be shown in `target_relation`, but unresolved physical ambiguity remains explicit in `status` / `gap`; the application never upgrades a probable recommendation to confirmed.
