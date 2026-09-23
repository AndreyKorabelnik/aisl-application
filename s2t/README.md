# aisl-s2t 0.1.0a6

Consumer-owned deterministic S2T application over one exact immutable AISL revision.

`aisl-s2t` lives in the separate `aisl-application` repository. It is not part of
AISL Core/KLC and does not write consumer policy back into AISL knowledge.

## Boundary

```text
repository
   ↓
knowledge-control-plane
   --knowledge-profile sql-source-inventory-v1
   ↓
AISL publication bundle
   ↓
aisl-server / Knowledge API
   ↓
(system_id, revision_id)
   ↓
aisl-sdk + sql-analysis/v1
   ↓
aisl-s2t
   ↓
S2T.csv + deterministic audit
```

The application does not import Core, Runner or KLC, does not read AISL storage,
and does not read repository source. The public Python `aisl-sdk` is the only AISL
transport/integration dependency.

## Product CLI

The caller supplies only the system, exact revision and output CSV path:

```bash
aisl-s2t build \
  --system-id <system-id> \
  --revision-id <revision-id> \
  --output s2t.csv
```

The audit sidecar is written automatically next to the CSV as `s2t.audit.json`.
There are no public `--mappings`, `--mapping-gaps`, `--target-fields`,
`--environment-resolution` or `--column-usage-contexts` inputs. Those facts belong
to the published AISL revision, not to the S2T caller.

Infrastructure settings are environment variables rather than business arguments:

```bash
export AISL_BASE_URL=http://127.0.0.1:8080
export AISL_TIMEOUT_SECONDS=30
```

## Required AISL revision

A revision intended for S2T is normally produced with:

```bash
knowledge-control-plane run \
  --knowledge-profile sql-source-inventory-v1 \
  --repository /path/to/repository \
  --system-id <system-id>
```

The S2T application pins the exact `(system_id, revision_id)`, loads the canonical
`sql-analysis/v1` Integration Profile and requires these published capabilities:

- `common.sql-target-resolution`;
- `common.sql-target-value-source-mapping`.

If either capability is missing, the build fails closed instead of silently creating
a reduced or guessed S2T.

## Revision-backed deterministic flow

1. `find_sql_target_candidates` is paged completely. `rank` is never treated as
   confidence or finality. Explicit intermediate and disabled targets are excluded;
   eligible observed workflow/published targets are deduplicated by published identity.
2. For every eligible target, `list_sql_target_value_sources` is read in bounded
   target-column pages. Every `sources[]` endpoint is preserved independently.
3. A physical target relation is used only when AISL reports
   `target_relation_recommendation_status=confirmed_unique`; otherwise the observed
   logical workflow target identity is preserved without guessing a physical schema.
4. Only `source_relation_role=driver_path` can populate primary `T-src*` fields.
   Enrichment, driver candidates and unknown roles never replace a missing primary
   source.
5. `target_expression_refs` are resolved only against the page's published
   `target_expressions`. Resolved non-direct expressions may populate `T-src-f`;
   expression refs are never interpreted as confidence or ranking.
6. `sources=[]` and unresolved source evidence retain a truthful target-only row.
7. Exact visible 26-column duplicates are removed deterministically; distinct source
   endpoints remain distinct rows.
8. Public gaps are retained in the audit sidecar. Truncated gap pages are reported in
   retrieval audit metadata rather than guessed or reconstructed from source.

## Output

CSV uses the canonical `report/s2t/v1` 26-column contract exactly. The second record
contains the canonical column descriptions. Values not supported by public AISL
evidence remain empty.

The audit sidecar contains:

- exact `system_id` and `revision_id`;
- deterministic row provenance and typed residual gaps;
- mapping IDs used for visible rows;
- Integration Profile id and required capabilities;
- target discovery/page counts;
- skipped intermediate/disabled target counts;
- per-target retrieval counts and gap truncation indicators.

## Tests

```bash
python -m pytest tests -q
```

Revision adapter tests cover exact revision pinning, capability gating, target
selection without rank-based winner choice, multiple real source endpoints,
expression references, target-only gaps and fail-closed malformed public contracts.
Production code contains no acceptance-corpus names or paths.
