# AISL Interaction Lineage

Consumer-owned deterministic composition of one `repository-topology/v5` candidate edge with
repository-local lineage from exact pinned AISL revisions.

Architecture invariant:

- `build` reads Repository Topology and exact pinned public AISL revisions only;
- `build` never reads source repositories and never invokes analysis;
- topology supplies unverified transport candidates; matching technical identifiers never prove a runtime crossing;
- each AISL revision owns repository-local observed/derived knowledge for one primary
  analyzed source, plus mechanically required dependency evidence for that revision;
- Interaction Lineage owns only the task-specific composition across those independent
  pinned revisions;
- revision discovery/binding is an upstream responsibility. `build` and `check` never
  infer `system_id` or `revision_id` from repository names;
- the application does not rediscover topology, parse code, infer renames, synthesize
  language-specific accessor facts, or create a second lineage engine;
- ambiguity and missing evidence remain typed gaps.

## Bindings

`build` requires an explicit deterministic binding file:

```json
{
  "schema_version": "interaction-lineage-aisl-bindings/v1",
  "repositories": [
    {
      "repository_id": "example-repo",
      "system_id": "example-system",
      "revision_id": "revision_123"
    }
  ]
}
```

`revision_id` must be an exact immutable revision, never `active` or `latest`.

`selected_repo_ids`, when present, are revision-internal evidence scope only (for example
a mechanically prepared Maven/source dependency needed to understand the primary
repository revision). They are not a mechanism for combining independent system
revisions. Cross-revision composition is performed by this application over separate
explicit bindings.

## Check

`check` is a **cheap admission preflight**. It validates exact pinned revisions,
the pinned `resolve_attribute_path` entry in `/revision-tools`, and whether Topology
contains observed field hints for the requested roles. The output is
`interaction-lineage-readiness/v1` with `readiness_scope: repository_revision_tools_only`.
`prerequisites_satisfied` means **only that deeper verification can be attempted**;
it does not establish field-anchor availability, external-origin resolution, or
any actual crossing. The explicitly non-blocking
`attribute_path_resolution_deferred` diagnostic records this limitation.
Missing bindings, revisions, revision tools and Topology field probes retain their
typed diagnostics. No source acquisition or analysis is attempted.

Use `check --deep` to run the previous detailed readiness check: it resolves
field anchors and examines material external-origin evidence, retaining preparation
hints such as `needs_external_source` and `material_semantic_gap`.
`prepare` continues to run this detailed evaluation internally; `build` continues
to resolve per-field paths as before. Neither changes semantic behavior.

```bash
interaction-lineage check \
  --topology topology.json \
  --edge-id repository_edge_... \
  --bindings bindings.json \
  --aisl-base-url http://127.0.0.1:8080 \
  --output readiness.json
```

Detailed diagnostics: add `--deep` to the command above.

## Build

```bash
interaction-lineage build \
  --topology topology.json \
  --edge-id repository_edge_... \
  --bindings bindings.json \
  --aisl-base-url http://127.0.0.1:8080 \
  --output lineage.json
```

The output contract is `interaction-attribute-lineage/v1`.

## Task 51 bounded prepare and observability

`prepare` is explicitly bounded **across all selected edges** by `--max-preparations`
(default `1`, `0` means no KCP calls) and `--max-kcp-steps` (default `1`,
allowed `1..32`). The latter is passed to the KCP public preparation contract,
not merely enforced by the client. Every KCP invocation consumes one budget
unit before dispatch, including timeout/failure. A **single** `prepare` now
re-checks pinned AISL readiness after each completed preparation wave and
continues to *newly observed*, materially relevant external-source groups in
that same command. It never traverses every POM dependency by default.
The exact source boundary is selected by the public readiness evidence; KCP owns
Nexus G:A:V acquisition, reuse and publication. Already attempted unchanged
boundaries are not retried merely because a revision ID changed.
When the budget is exhausted, pending groups are preserved in `deferred_groups`
with `preparation_budget_exhausted`; blocked or no-progress KCP outcomes retain
unattempted groups with `previous_preparation_stopped`. A KCP `step_limit` can
admit a *different* newly observed boundary but cannot resubmit the same one.
The command-scoped budget is shared across `--all-edges`. No candidate edge is
silently removed. Individual source gaps may still remain explicit PARTIAL/BLOCKED.

Use `--progress-jsonl progress.jsonl` to receive flushed, timestamped progress
both on stderr and in a local JSONL audit trail. Each KCP group has a start and
completion event including elapsed time, outcome, returned job IDs and selected
source IDs. Re-evaluation events (`preparation.readiness_rechecked`) show how
many *new* requirement groups were discovered, and `preparation.finished` emits
the final status. `framework_preparations[*].requested_boundary`, `steps`, and
`published_dependency_revisions` preserve the mechanical reason and pinned
knowledge references in the result JSON. This does **not** expose intra-job
Nexus progress to the client:
server KCP runtime logging records Nexus G:A:V starts/completions and elapsed
seconds (from Runner), source digests, analysis-job state changes and AISL
publication. Consult the KCP runtime log / job logs while the synchronous
`prepare` request is running. Logs must be sanitized before export.

KCP preparation requests directly select Knowledge Product `attribute-lineage`
with `execution_scope=workspace`, through the supported generic
`/api/v1/preparations/run` API. No Knowledge Profile or Published Capabilities
registry is involved. The selection produces source-local value-flow evidence,
not an eager full-portfolio interaction graph. Nexus sources are admitted only
through bounded, observed external-source demands. A KCP runtime that does not
support this request contract must fail closed; it is not automatically adapted.

These controls do not guarantee a wall-clock/CPU bound **within** one KCP job.
Operators must also configure/verify server-side Runner/Nexus limits before real
bank execution; do not use `prepare --all-edges` as an unbounded analysis probe.

A `prepare` invocation invalidates its previous `missing-revisions.json`,
`resolved-bindings.json`, and executable `prepare-missing-bundles.sh` in the
chosen output directory *before* contacting AISL. If the invocation fails
(including a failure while rendering the bundle plan), no old/manual bundle
script survives. The `preparation.json` result records the failure; a new
manual script is available only after a successful planning pass. Operators
must not reuse saved scripts from earlier invocations.

## Prepare (transitional lifecycle)

`prepare` is retained only because the current accepted production journey still needs a
generic Framework/KCP preparation entry point before exact pinned bindings exist. It is
**not** the target ownership boundary for Interaction Lineage.

The target lifecycle is:

`Unified AISL Discovery / generic preparation -> exact pinned bindings -> check -> build`.

Until that upstream discovery/preparation path is available for this journey, `prepare`
continues to reuse the existing Knowledge Control Plane source registry and freshness
path rather than implementing Git/Nexus/source analysis locally:

`registered remote Git -> resolve current HEAD -> immutable commit snapshot -> pinned checkout -> Runner -> AISL publication bundle`.

```bash
interaction-lineage prepare \
  --topology topology.json \
  --edge-id repository_edge_... \
  --aisl-base-url http://127.0.0.1:8080 \
  --kcp-base-url http://127.0.0.1:8000 \
  --max-preparations 12 --max-kcp-steps 8 \
  --progress-jsonl preparation-progress.jsonl \
  --output preparation.json
```

The historical bootstrap rule that assigns `system_id = repository_id` when no binding
exists remains a **transitional compatibility behavior only**. It must be removed when
Unified AISL Discovery supplies the exact repository -> system/revision binding; new
consumer logic must not depend on that naming equality.

For already pinned revisions, preparation may still request mechanically required
external package/source evidence (for example Nexus/Maven dependencies) through the
generic Framework path. Such dependencies remain evidence of the primary revision; they
do not become independent system revisions or application-owned source knowledge.

The preparation output embeds exact `interaction-lineage-aisl-bindings/v1` bindings and
can be passed to `check` or `build`. The command reports READY (`prepared` or
`already_prepared`), PARTIAL (`budget_exhausted`, `step_limit` or `no_progress`),
or BLOCKED (`blocked`) rather than claiming exhaustive discovery of all runtime
links. A newly observed external dependency is followed only when a fresh
public AISL check supplies an exact mechanical preparation requirement. Interaction Lineage itself owns no Git/Nexus client,
source parser, repository discovery heuristic, or publication implementation.

## Human CSV

The canonical result remains `interaction-attribute-lineage/v1` JSON. A compact
human-readable CSV can be rendered deterministically from that JSON without calling
AISL Server or KCP:

```bash
interaction-lineage csv \
  --input lineage.json \
  --output lineage.csv
```

The CSV is a projection only; it creates no new lineage claims. One row represents one
interaction attribute journey and is rendered in actual data-flow direction. The columns
are:

```text
interaction
role
producer_repository
producer_attribute
crossing_attribute
consumer_repository
consumer_attribute
gap
full_attribute_path
```

`producer_attribute` is the normalized local origin before the transport crossing when
one is mechanically resolved. `crossing_attribute` is the exact topology transport
field. `consumer_attribute` is the deepest mechanically proven meaningful semantic
consumer available from the published target-side evidence; it is not limited to the
first technical node after the crossing. An unresolved producer/consumer anchor is left
empty and described in `gap`. Human `gap` values are rendered in Russian while
`full_attribute_path` intentionally keeps the original machine gap code for audit and
cross-reference with the canonical JSON. Detailed operations, transformations, branch
provenance, confidence and anchor-selection evidence remain in the canonical JSON and
are intentionally not duplicated as separate human CSV columns.


## Recall-first Topology v5: candidate batch (Task 51)

Topology v5 supplies *candidate interactions*, not proven attribute crossings.
The consumer obtains provisional field probes from Inventory half-wire field names/paths
only. Local AISL resolution of a field does **not** establish the remote runtime target;
all crossings remain `candidate` until independent exact transport-crossing evidence exists.
Zero observed fields yield `candidate_fields_not_observed`, not an empty READY result.

Batch `check --all-edges` performs only a command-scoped **cheap prerequisite**
assessment: one cached revision/capability read per unique pinned revision, no
attribute-path resolution and no repository value-node traversal. Its positive
per-edge status is `prerequisites_satisfied`, **not** `ready`; its summary and
diagnostics explicitly label attribute-path evidence as `deferred`. Use
`check --deep --all-edges` when full anchor and external-origin diagnostics are
needed. A successful cheap check does not prove any candidate transport crossing.

For read-only `check --all-edges` / `build --all-edges`, exact pinned AISL reads
are reused within the command. The cache key includes system/revision identity,
selected repository IDs, direction, field/source and pagination/filter parameters.
Transient API errors are not cached; `prepare` never enables read caching because it
may publish new knowledge. The batch output `summary.aisl_api_cache` records backend
calls, cache hits and entries by API operation. Cache state does not persist to disk.

`check`, `prepare`, and `build` accept either `--edge-id ID` or explicit
`--all-edges`; all-edges produces a complete candidate-edge ledger. The sole
operation authorized to invoke Framework/KCP (including demand-driven Nexus source
preparation) remains `prepare`. Revisions returned by a successful preparation
are reused for later edges within that same batch; no v4 compatibility mode is kept.

```bash
interaction-lineage check \
  --topology topology-v5.json --all-edges \
  --bindings bindings.json --aisl-base-url http://aisl-server:8080 \
  --output readiness-all.json

# Optional: retain the previous full, higher-cost evidence diagnostics
interaction-lineage check \
  --topology topology-v5.json --all-edges --deep \
  --bindings bindings.json --aisl-base-url http://aisl-server:8080 \
  --output readiness-deep-all.json

interaction-lineage prepare \
  --topology topology-v5.json --all-edges \
  --aisl-base-url http://aisl-server:8080 \
  --kcp-base-url http://knowledge-control-plane:8000 \
  --max-preparations 1 --max-kcp-steps 1 \
  --progress-jsonl preparation-progress.jsonl \
  --output preparation-all.json

interaction-lineage build \
  --topology topology-v5.json --all-edges \
  --bindings bindings.json --aisl-base-url http://aisl-server:8080 \
  --output lineage-all.json
```

`complete` in the batch envelope means that all selected candidate records were
processed; it does **not** mean that runtime interactions were proven. An unresolved
field, unavailable revision, source version mismatch or Nexus provenance gap must
remain visible rather than converting into a negative assertion or a false crossing.

### Source selection and provenance

The preparation pipeline reuses available published AISL knowledge and requests
missing source analysis through the existing Framework/KCP lifecycle. Normal
source acquisition uses the latest available repository source (as requested by
the consumer); exact identities of the analyzed revisions and any Nexus
G:A:V dependencies are retained in their published provenance.

Topology v5 `source_snapshot_fingerprint` and KCP source fingerprints are
**not interchangeable**. Neither fingerprint controls whether a needed analysis
can be started. A field or interaction remains a `candidate` until sufficiently
supported by the published evidence; absence of a field probe remains an
explicit gap, not a proven negative interaction.

## Task 51 Inventory → KCP selected-source registration

An optional `prepare --inventory-manifest` (repeatable) bridges **only** the selected
candidate source to KCP's existing repository registry. Use the actual
`remote_batch_manifest.json` written by the UCP/КПК Inventory discovery runs:

```bash
interaction-lineage prepare \
  --topology topology.json --edge-id '<selected-edge-id>' \
  --inventory-manifest inventories/ucp/remote_batch_manifest.json \
  --inventory-manifest inventories/kpk/remote_batch_manifest.json \
  --aisl-base-url http://localhost:8080 --kcp-base-url http://localhost:8000 \
  --max-preparations 1 --max-kcp-steps 1 \
  --progress-jsonl progress.jsonl --output preparation.json
```

The Application reads only verified successful (`completed`/`reused`) Inventory
records containing a Git URL, source repository id and exact observed commit.
It **does not** rediscover repositories using remote APIs, register every Inventory
repository, fetch code, or initiate analysis on registration. Before a budgeted
KCP preparation it checks the KCP registry for exactly one compatible source;
if missing it POSTs `/api/v1/repositories/discover` using `defer_checkout=true`,
`refresh=false`, then verifies the registered record. Conflicting/ambiguous
registrations or unavailable Inventory records stop that edge, not silently
fall back to a different remote. Without `--inventory-manifest`, the previous
explicitly pre-registered-KCP path is unchanged.

**Revision limitation:** KCP discovery tracks a Git ref and does not itself
pin the Inventory observed commit. Registration progress distinguishes
`registered_ref_unverified` from `registered_exact_snapshot`, retaining
`inventory_resolved_commit`; KCP/Runner remains responsible for immutable
source snapshots at analysis time. Do not equate `registered_ref_unverified`
with analysis of the exact Inventory commit. A moved branch needs a separate
identity audit before claiming snapshot parity.

## Manual bundles integrated into `prepare` (Task 51)

Repository Inventory/Topology is a **separate application**. The only source-discovery
input to Interaction Lineage is `topology.json`. Its `repositories[]` records may
contain an observed `repository_url` and an exact `resolved_commit` (from a matching
Inventory batch manifest). The consumer never invents Git URLs or commits.

One command runs existing bounded KCP/AISL/Nexus preparation for every selected
candidate, then gives exact manual work remaining:

```bash
interaction-lineage prepare \
  --topology topology.json --all-edges \
  --aisl-base-url http://127.0.0.1:8080 \
  --kcp-base-url http://127.0.0.1:8000 \
  --max-preparations 12 --max-kcp-steps 8 \
  --progress-jsonl results/progress.jsonl \
  --output-dir results
```

`--output` is optional with `--output-dir`; defaults to `results/preparation.json`.
On the way in, `prepare` reuses published AISL revisions with matching immutable
Git snapshot (URL and full commit), requested capability, and unambiguous binding
before starting avoidable KCP preparation. KCP remains responsible for its own
bounded generic Git/Nexus analysis, dependency reuse and publication bundle
creation. On the way out, `prepare` runs a final exact AISL catalog check and
writes these **additional** files:

- `missing-revisions.json` — full per-repository readiness, ambiguity and gap ledger;
- `resolved-bindings.json` — exact pinned revisions verified by catalog identity;
- `prepare-missing-bundles.sh` — executable commands only for missing revisions with
  verified Git URL+commit; profile `attribute-lineage-v1`.

A partial result is reported while manual bundles or source identities are
outstanding; the existing detailed edge preparation results and diagnostic ledger
are retained. A missing exact commit is an explicit gap, never a guessed branch.

**Copying bundles and importing them on AISL Server are manual.** Neither the
app nor generated script performs transfer or import. Each completed KCP CLI job
has a `publication_bundle.path` in its JSON. After manually publishing, run
**the same `interaction-lineage prepare` command again**; it checks newly
published revisions and continues with the remaining work. There is no
separate `plan-bundles` command.

The output remains bounded by the explicit KCP budget. `--all-edges` visits
all candidate edges in the provided Topology, not an exhaustive proof of every
runtime program path. Multi-edge end-to-end composition remains a separate
unaccepted Task 51 gate, not something this source change purports to solve.
