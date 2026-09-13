# Current acceptance — Repository Topology 0.1.0a8

Current contracts:

- input: `repository-inventory-reduced/v3`;
- topology: `repository-topology/v3`;
- attribute route: `repository-attribute-path/v2`;
- CSV: `repository-topology-csv/v2`.

Accepted capabilities:

- HTTP exact and bounded probable cross-repository edges;
- Kafka exact resolved-literal topic edges;
- deterministic islands;
- canonical pair-preserving attribute flows;
- Mermaid repository graph;
- exact-name attribute route query with optional bounds;
- Excel-friendly complete CSV;
- matchability observability explaining input transport coverage and every unmatched half-wire.

Matching semantics are unchanged by 0.1.0a8. Diagnostics are explanatory projections owned by `repository_topology.matching`; fallback matching remains forbidden.

Current package test suite: 42/42 PASS.
See `T8_MATCHABILITY_DIAGNOSTICS_ACCEPTANCE.md` for the latest architectural acceptance.
