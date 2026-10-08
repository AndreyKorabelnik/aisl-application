# AISL CTL Topology

Consumer-only deterministic CTL composition using pinned public AISL products.

```bash
aisl-ctl-topology build --aisl-base-url http://aisl-server:8080 \
  --revision datamart_profile_fl=REV_PROFILE \
  --revision custom_b2c_insurance=REV_INSURANCE \
  --output-json ctl-topology.json --output-csv ctl-topology.csv \
  --output-mermaid ctl-topology.mmd
```

Requires Knowledge API support for the published typed-record endpoint. Each of the 8
`ctl-orchestration/v1` tables is read using a pinned system/revision/artifact;
no private server database is opened. JSON retains all source rows (including
schedules, locks, provenance, and gaps) plus derived cross-revision projections.
CSV and Mermaid are projections from the same JSON. Cross-revision dependencies
require exact profile/entity ID *and* explicitly supported published statistic.
A named flow is never selected silently when multiple candidates exist. Missing
producer evidence is represented as a half-wire, not an absence claim.
