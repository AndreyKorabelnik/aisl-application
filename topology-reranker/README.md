# repository-topology-reranker 0.1.0a2

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
It accepts only frozen deterministic rerank packages produced by
`repository-inventory`.

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

## PR-C batch orchestration

The CLI adds orchestration only; it does not add a topology matcher or an embedded
provider SDK. A configured external command receives exactly one frozen package as
JSON on stdin and returns one ranking response JSON on stdout. The command is invoked
without a shell and without semantic retries.

```bash
repository-topology-reranker rerank-batch \
  --packages rerank-packages.json \
  --output-dir rerank-results \
  --adapter-executable python \
  --adapter-arg /path/to/provider_adapter.py \
  --provider external-provider \
  --model weak-model
```

`--packages` may be one package, an array of packages, or the deterministic PR-A
envelope containing a top-level `packages` array.

Each exact package hash gets one terminal result file. Re-running the same command
resumes those files mechanically and does not call the adapter again, including for
previous `PROVIDER_ERROR` or `INVALID_RESPONSE` results. Deliberate retry requires
removing that exact result file first. A zero-package batch performs zero adapter
calls and still writes an operational `run-manifest.json`.

Provider errors or invalid responses do not make the batch command fail: they are
persisted as typed non-canonical results and the CLI exits successfully. Invalid or
tampered input packages fail before any adapter call.

## Tests

```bash
python -m pytest tests -q
```
