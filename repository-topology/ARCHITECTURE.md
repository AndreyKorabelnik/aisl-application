# Architecture

## Boundary

`Repository Inventory (one repo) -> repository-inventory-reduced/v3 -> Repository Topology (N repos) -> repository-topology/v3 -> graph/path/CSV views`

Inventory owns repository-local observed facts. Topology owns cross-repository correlation, connected components and diagnostic explanation of its own matching decisions.

Hard invariants:

- no source reads;
- no parser dependencies;
- no cross-repository matching in Inventory;
- no AISL/Core/Runner/KLC dependency;
- one matcher owner: `repository_topology.matching`;
- diagnostics explain that matcher; they are not an alternate matcher or verifier;
- no fallback matching;
- repository names are never matching evidence;
- explicit-file and directory CLI modes feed the same `build_topology()` path;
- Mermaid, attribute-path and CSV are views/queries over the same topology artifact.

## Repository matching policy

HTTP exact: resolved single outbound path == resolved single inbound path and method exact.

HTTP probable: source `ambiguous_declared_config`, exact method, matching terminal route segment, request-field Jaccard >= 0.8.

Kafka exact: publish/consume, both topic identities `resolved`, both identity kinds `literal`, exact single topic equality.

Connected components are mechanical projections of emitted edges.

## Matchability diagnostics

`repository-topology/v3` adds `matchability_analysis`, produced by the same matching module that owns `match_all()`.

It does not attempt additional correlations. It only classifies the existing input half-wires against the exact same eligibility rules and threshold constants. Its purpose is to distinguish:

1. upstream fact-coverage gaps (few/no half-wires);
2. identity-resolution gaps;
3. exact method/path/topic mismatches;
4. bounded probable-rule failures such as missing request fields or insufficient field overlap;
5. correct lack of a counterpart in the supplied repository set;
6. internal consistency failures where the same rules imply a Match should already exist.

The analysis uses indexed counterpart lookup instead of a second all-pairs matching pass. Every unmatched half-wire is represented once in `diagnostics`; aggregate reason counts and per-repository counts are projections of those same facts.

## Canonical attribute flows

Each repository edge stores pair-preserving `attribute_flows` derived only after a Match exists. Exact case-sensitive field names are intersected per actual matched pair:

- HTTP request: caller -> callee;
- HTTP response: callee -> caller;
- Kafka payload: publisher -> consumer.

`name_comparison = exact_case_sensitive`; `rename_inference = forbidden`.

## Views

Mermaid reads `repository-topology/v3` and renders existing nodes/edges only.

Attribute-path reads canonical `attribute_flows`; its result contract remains `repository-attribute-path/v2` and explicitly does not claim code-level lineage.

CSV reads `repository-topology/v3`; its contract is `repository-topology-csv/v2`. It adds filterable matchability/diagnostic rows but performs no graph or matching logic.
