# Current state

Version: 0.1.0a8
Topology contract: repository-topology/v3
Attribute-path result: repository-attribute-path/v2
CSV representation: repository-topology-csv/v2
Input: repository-inventory-reduced/v3 only

Scope:
- HTTP exact + bounded probable repository correlations;
- Kafka exact correlation for resolved literal topic identities only;
- consolidated repository edges and deterministic connected-component islands;
- explicit-file and recursive directory input;
- canonical pair-preserving `attribute_flows` on repository edges;
- deterministic Mermaid repository graph with APIs/topics and attributes;
- exact case-sensitive directed attribute-path query with optional source/target bounds;
- deterministic Excel-friendly long-form CSV export;
- diagnostic `matchability_analysis` explaining transport fact coverage and every unmatched half-wire without adding fallback matching.

`matchability_analysis` reports:
- repositories with/without any transport half-wire;
- HTTP/Kafka counts by direction and identity status;
- exact/probable eligibility counts under the current matcher rules;
- matched vs unmatched half-wire counts;
- per-repository transport counts;
- aggregated unmatched reason counts;
- detailed unmatched half-wire diagnostics with candidate counts and, where relevant, maximum request-field overlap.

Source parsing: forbidden/not present.
Fallback matching: forbidden.
Rename inference: forbidden.
Attribute route semantics: name-preserving repository route, not code-level data lineage.
Diagnostic semantics: explanation of current matching policy only; diagnostics do not create edges or weaken matcher requirements.
CSV semantics: representation only; no matching, graph or inference logic.
