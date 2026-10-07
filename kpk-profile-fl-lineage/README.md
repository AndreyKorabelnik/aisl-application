# KPK service → CPC crossing → UCP → Profile FL lineage bridge

`aisl-kpk-profile-fl-lineage` is a bounded consumer-side composition application.
It does **not** analyze source code and does not create a universal cross-revision
lineage engine.

## Inputs

1. Task 43 `interaction-lineage` human CSV for the relevant service interaction.
   This is the owner of the mechanically proven final `consumer_attribute` in the
   KPK service. `crossing_attribute` remains an intermediate CPC/UCP interaction
   attribute and is never renamed to `kpk_attribute`.
2. mechanically grounded CPC crossing → UCP evidence with exact
   `crossing_attribute`, `ucp_semantic_path` and `endpoint_key`;
3. three independently pinned AISL revisions already used by
   `aisl-data-model-datamart-lineage`: UCP model, TSA and Profile FL.

The application exact-joins the two left-side inputs on Task 43
`crossing_attribute`, then calls the existing Task 46 builder for each exact UCP
endpoint. The UCP→Profile side is confirmed only when the **full UCP semantic
path** is identical.

`--consumer-output-root` is a fail-closed selector for the external service output surface. A Task 43 `consumer_attribute` outside that root remains provenance only and cannot become `kpk_attribute`.

A known UCP→Profile path is not sufficient to claim a KPK mapping. If Task 43 does
not publish a final consumer attribute for the selected KPK service, the row is
`unresolved_kpk_egress` even when the downstream Profile FL column is known. This
prevents claims such as `clientInfo.names.fullName == epk_client.last_name` and
`clientInfo.ucpID == epkid_2_epkid.merge_epk_id` when the KPK service does not
mechanically expose those crossing fields as final response attributes.

## Example

```bash
kpk-profile-fl-lineage build \
  --aisl-base-url http://aisl-server:8080 \
  --crossing-ucp-evidence crossing-ucp-evidence.csv \
  --interaction-lineage-csv interaction-lineage.csv \
  --consumer-repository cpc_efs_gateway_get_cards_by_client_id \
  --consumer-output-root bankAcctRecs \
  --interaction "HTTP POST /cpcGet" \
  --source-system ucp-data-model \
  --source-revision rev-c39ad2888fc29779cf411bd9 \
  --bridge-system ucp-tsa-v4 \
  --bridge-revision rev-5a16127953b6774b18dd8268 \
  --target-system datamart_profile_fl \
  --target-revision rev-150997201317410ecf2dd2ef \
  --output-json result.json \
  --output-csv result.csv
```

`crossing-ucp-evidence.csv` is an input contract, not a hidden matcher. It must
already contain exact UCP semantic-path facts with provenance. The bridge does
not infer UCP correspondence from similar names.

The output JSON contract is `kpk-profile-fl-lineage/v2`. The CSV explicitly
contains both `kpk_attribute` (final Task 43 consumer) and
`cpc_crossing_attribute` (intermediate `/cpcGet` crossing) so these identities
cannot be silently conflated again.
