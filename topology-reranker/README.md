# repository-topology-reranker 0.1.0a1

External application-layer semantic reranking over frozen
`repository-topology-rerank-package/v1` evidence.

## Boundary

```text
repository-topology/v4 (canonical, deterministic)
        +
repository-topology-rerank-package/v1 (deterministic eligibility/candidates)
        ↓
repository-topology-reranker (external application)
        ↓
repository-topology-semantic-shortlist/v1 (non-canonical hypothesis)
```

The application never builds or modifies canonical topology. It does not read
repository source, Gold, deployment artifacts, AISL storage, or Inventory internals.
It accepts only the frozen deterministic rerank package produced by
`repository-inventory`.

PR-B is library-only. It intentionally does **not** provide CLI/orchestration or a
real provider implementation. Those belong to a later, separately accepted PR-C.

## Contracts

Input package: `repository-topology-rerank-package/v1`.

Provider-neutral structured response: `repository-topology-rerank-response/v1`:

- exact `package_hash` and `case_id`;
- 1..3 supplied candidate IDs only;
- `target_repository` must match the supplied candidate;
- evidence refs may only use that candidate's `supporting_interface_ids`;
- ranks must be ordered and contiguous from 1;
- free-text explanation is retained only as non-canonical model output.

Validated output: `repository-topology-semantic-shortlist/v1` with
`classification=non_canonical_hypothesis`. The artifact always retains deterministic
candidate order separately from model order. Provider and invalid-response failures
are isolated and never change deterministic topology.

## Tests

```bash
python -m pytest tests -q
```
