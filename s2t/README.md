# aisl-s2t 0.1.0a1

Consumer-owned deterministic S2T application over pinned public AISL evidence.

`aisl-s2t` lives in the separate `aisl-application` repository. It is not part of
AISL Core/KLC and must not write consumer policy back into AISL knowledge.

Current bounded scope: deterministic environment/stand selection for S2T source
identity resolution. Later S2T builder/gap/renderer/LLM-review components belong
here as additional consumer-owned layers.

## Boundary

```text
AISL / Knowledge API / public artifacts
             ↓
        aisl-sdk / export
             ↓
           aisl-s2t
             ↓
 deterministic S2T + typed gaps
```

The application does not import Core, Runner or KLC, does not read AISL storage,
and does not read repository source.

## Environment policy v1

Environment choice is a deterministic S2T policy, not an AISL fact.

1. Explicit caller/input environment wins.
2. Otherwise `default_environment = production`.
3. Environment roles map to exact observed environment-scope identities supplied
   by caller/configuration/evidence.
4. Production is never inferred from schema names, cluster names, array order,
   `prod/prom` substrings or repository-specific naming conventions.
5. A placeholder resolves only when the selected environment yields exactly one
   mechanically observed candidate value.
6. One concrete literal candidate is deterministic without environment selection.
7. Multiple matching values or no matching value remain unresolved.
8. PA/deployment/non-production is selected only by explicit context.
9. Every decision retains resolution basis for audit.

## CLI

```bash
aisl-s2t resolve-environment \
  --gaps gaps.json \
  --environment-observations environment-observations.json \
  --policy environment-policy.json \
  --output environment-resolution.json
```

The executable name is `aisl-s2t` (without the space shown above if your Markdown
renderer wraps it):

```bash
aisl-s2t --help
```

Equivalent module invocation:

```bash
python -m aisl_s2t.cli --help
```

Use `--environment <role>` for an explicit override. Without it,
`default_environment` is used and defaults to `production`.

The output contains per-diagnostic decisions plus semantically deduplicated source
decisions. Several workflow contexts may describe the same source decision; a
resolved identity is accepted only when all resolved contexts agree. Conflicting
resolved identities remain ambiguous.

This initial batch does not discover targets, render the canonical 26-column CSV,
call an LLM, or implement source-specific history/backup heuristics.

## Tests

```bash
python -m pytest tests -q
```

The tests include opaque environment-scope identities to prove the code is not
coupled to Insurance `stands[n]` layout.
