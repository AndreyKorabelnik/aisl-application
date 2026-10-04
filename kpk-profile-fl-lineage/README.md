# KPK → UCP → Profile FL lineage bridge

`aisl-kpk-profile-fl-lineage` is a bounded consumer-side composition application.
It does **not** analyze source code and does not create a universal cross-revision
lineage engine.

Inputs:

1. mechanically grounded KPK → UCP evidence with an exact canonical UCP endpoint;
2. three independently pinned AISL revisions already used by
   `aisl-data-model-datamart-lineage`: UCP model, TSA and Profile FL.

The application calls the existing Task 46 builder for each exact UCP endpoint and
joins the two sides only when the **full UCP semantic path** is identical. Matching
only `<type>.<field>` is intentionally insufficient because generic dictionary
leaves such as `QualityCode.code`, `NameType.code` or
`IdentificationFlagType.code` may occur under several distinct semantic roles.

A right-side path with the same endpoint leaf but a different or collapsed UCP
context produces `context_ambiguous`; it is never promoted to confirmed lineage.

Example:

```bash
kpk-profile-fl-lineage build \
  --aisl-base-url http://aisl-server:8080 \
  --kpk-ucp-evidence kpk-ucp-evidence.csv \
  --source-system ucp-data-model \
  --source-revision rev-c39ad2888fc29779cf411bd9 \
  --bridge-system ucp-tsa-v4 \
  --bridge-revision rev-5a16127953b6774b18dd8268 \
  --target-system datamart_profile_fl \
  --target-revision rev-150997201317410ecf2dd2ef \
  --output-json result.json \
  --output-csv result.csv
```

The KPK → UCP evidence file is an input contract, not a hidden matcher. It must
already contain exact `ucp_semantic_path` and `endpoint_key` facts with provenance.
The bridge does not infer them from similar names.

The output JSON contract is `kpk-profile-fl-lineage/v1`; CSV is a human projection.
