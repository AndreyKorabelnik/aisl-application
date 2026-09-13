# T8 Matchability diagnostics acceptance

Version: repository-topology 0.1.0a8
Date: 2026-09-07

## Problem

A real portfolio topology built from 1595 Reduced Inventory artifacts produced 0 edges and 1595 singleton islands. The previous `repository-topology/v2` artifact did not contain enough information to distinguish an upstream Inventory transport-fact coverage gap from matcher rejection.

## Accepted change

`repository-topology/v3` adds `matchability_analysis` and detailed unmatched half-wire diagnostics. The same `repository_topology.matching` module owns both matching and diagnostic classification.

No matching rule was broadened. No fallback or second matcher was added.

## Diagnostic coverage

The artifact reports:

- repository count with/without transport half-wires;
- HTTP inbound/outbound counts and identity-status distribution;
- HTTP exact/probable eligibility counts under the existing rules;
- Kafka publish/consume counts, identity-kind distribution and exact-literal eligibility counts;
- matched/unmatched half-wire counts;
- per-repository transport counts;
- aggregate unmatched reason counts;
- one detailed diagnostic per unmatched half-wire with candidate counts and bounded evidence such as maximum request-field overlap.

Representative reasons accepted by tests:

- `http_exact_no_inbound_same_path`;
- `http_exact_method_mismatch`;
- `http_probable_request_field_overlap_below_threshold`;
- `kafka_identity_not_literal`;
- `kafka_publish_no_consumer_same_literal_topic`;
- `kafka_consume_no_publisher_same_literal_topic`.

Matched half-wires are not emitted as unmatched diagnostics.

## CSV closure

`repository-topology-csv/v2` adds filterable rows for matchability summary/reasons/status/kinds/per-repository counts and richer diagnostic columns. CSV remains a view over an already-built topology and performs no matching.

## Acceptance evidence

- full pytest: 42/42 PASS;
- repository-topology/v3 JSON Schema validation: PASS;
- synthetic 1595-repository zero-half-wire portfolio: PASS; correctly reports 1595 repositories without half-wires and 0 edges;
- synthetic 1595-repository mixed portfolio: PASS; reports one exact edge plus independent method-mismatch/no-path reasons;
- wheel build via `pip wheel --no-deps --no-build-isolation`: PASS;
- clean wheel install/import/CLI smoke: PASS.

The local Python environment lacks the optional `build` frontend module. Production code was not changed for this harness limitation.
