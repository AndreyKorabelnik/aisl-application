# Repository Topology

`repository-topology` is a generic consumer of `repository-inventory-reduced/v3` artifacts from independently analysed repositories. It derives explainable repository edges, islands, exact-name attribute routes and diagnostic matching observability. It never reads repository source code and has no parser/framework dependencies.

Current topology contract: `repository-topology/v3`.

## Build topology

Explicit files:

```bash
repository-topology build \
  --inventory repo-a/repository_inventory_reduced.json \
  --inventory repo-b/repository_inventory_reduced.json \
  --output repository_topology.json
```

Directory mode recursively discovers `repository_inventory_reduced.json`:

```bash
repository-topology build-directory \
  --inventories ./inventory-results \
  --output repository_topology.json
```

The build now always emits `matchability_analysis`. This diagnostic projection is owned by the same `repository_topology.matching` module as edge matching and does not create fallback edges.

Useful fields for a zero-edge portfolio:

```text
summary.repository_with_half_wire_count
summary.repository_without_half_wire_count
matchability_analysis.summary.http_inbound_count
matchability_analysis.summary.http_outbound_count
matchability_analysis.summary.http_exact_eligible_inbound_count
matchability_analysis.summary.http_exact_eligible_outbound_count
matchability_analysis.summary.http_probable_eligible_outbound_count
matchability_analysis.summary.kafka_publish_count
matchability_analysis.summary.kafka_consume_count
matchability_analysis.summary.kafka_exact_eligible_publish_count
matchability_analysis.summary.kafka_exact_eligible_consume_count
matchability_analysis.unmatched_reason_counts
matchability_analysis.repository_stats
```

Each unmatched half-wire also appears in `diagnostics` with an explicit `reason`, candidate count and relevant supporting measurements. Examples include:

- `http_exact_no_inbound_same_path`;
- `http_exact_method_mismatch`;
- `http_probable_no_inbound_terminal_match`;
- `http_probable_source_request_fields_missing`;
- `http_probable_target_request_fields_missing`;
- `http_probable_request_field_overlap_below_threshold`;
- `kafka_identity_not_literal`;
- `kafka_publish_no_consumer_same_literal_topic`;
- `kafka_consume_no_publisher_same_literal_topic`.

`internal_consistency_error_*` diagnostics indicate a Topology correctness problem: the analysis found a pair that the same matching rules say should already have formed a Match.

## Mermaid repository graph

```bash
repository-topology mermaid \
  --topology repository_topology.json \
  --output repository_topology.mmd
```

Mermaid is a deterministic representation of the existing topology. Edge labels include REST method/path or Kafka topic and canonical exact-name attributes. Exact edges are solid; probable edges are dashed.

## Attribute path

```bash
repository-topology attribute-path \
  --topology repository_topology.json \
  --attribute sberProfileId \
  --output sberProfileId-path.json \
  --mermaid-output sberProfileId-path.mmd
```

`--from-repository` and `--to-repository` are optional independently. With neither, the complete directed crossing subgraph for the exact attribute name is returned. Attribute names are case-sensitive; rename inference is forbidden. This is a name-preserving repository route, not code-level lineage.

## CSV export for Excel

```bash
repository-topology csv \
  --topology repository_topology.json \
  --output repository_topology.csv \
  --delimiter semicolon
```

CSV contract: `repository-topology-csv/v2`.

The long-form CSV includes `record_type` rows for:

- `topology`, `island`, `repository`, `edge`, `attribute`;
- `matchability_summary`;
- `matchability_reason`;
- `identity_status`;
- `transport_identity_kind`;
- `repository_matchability`;
- `diagnostic`.

Nested evidence/provenance remains available in deterministic JSON columns. UTF-8 BOM, CRLF and formula-injection-safe plain-text cells are retained for Excel.

## Matching policy

Matching rules are unchanged by the diagnostic work:

- HTTP exact: resolved single outbound path == resolved single inbound path and method exact;
- HTTP probable: outbound `ambiguous_declared_config`, exact method, matching terminal path segment and request-field Jaccard >= 0.8;
- Kafka exact: publish/consume with the same resolved single literal topic.

No fallback matching, fuzzy path matching, repository-name evidence or semantic rename inference is performed.
