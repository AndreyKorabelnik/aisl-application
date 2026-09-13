# Next development plan

The 0.1.0a8 diagnostic observability gap is closed. Do not expand matching rules yet.

## Next justified activity: rerun the 1595-repository portfolio

Build `repository-topology/v3` from the same Reduced Inventory directory and inspect:

1. `summary.repository_with_half_wire_count` / `repository_without_half_wire_count`;
2. `matchability_analysis.summary` HTTP/Kafka direction and eligibility counts;
3. `matchability_analysis.unmatched_reason_counts`;
4. highest-volume `diagnostics` reasons and their affected repositories;
5. CSV rows `matchability_summary`, `matchability_reason`, `repository_matchability`, `diagnostic`.

Only those observed results should determine the next code owner:

- little/no transport coverage -> investigate Repository Inventory evidence coverage;
- many resolved/eligible half-wires but systematic unmatched reasons -> investigate the specific Topology matcher rule;
- expected counterparts absent from the 1595 inputs -> correct no-edge result;
- internal consistency diagnostic -> Topology correctness bug.

Do not add fuzzy path matching, semantic field matching, repository-name evidence, rename inference, alternate graph owner or fallback matching before this acceptance evidence exists.
