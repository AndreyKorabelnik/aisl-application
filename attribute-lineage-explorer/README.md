# AISL Attribute Lineage Explorer — Task 52 (local integration candidate)

This is a browser-only, read-only consumer of **published** `interaction-attribute-lineage/v1`
(single) and `interaction-lineage-candidate-batch/v1` (multi-edge) JSON files.
It does **not** analyze source repositories, query AISL, operate Nexus, or infer
undocumented inter-system semantics. `candidate` crossing edges remain candidates,
and absent/terminal anchors are shown as gaps without invented edges.

## Status and repeatable delivery

Browser-only static source module in `aisl-application`. It has no frontend/build
package dependencies; the release is produced by the single tracked stdlib builder:

```sh
python3 attribute-lineage-explorer/tools/build_clean_delivery.py \
  --output /tmp/aisl-attribute-lineage-explorer.zip
```

The output is a self-contained, deterministically ordered ZIP with only public
runtime assets, sample JSON and `INSTALL_RU.md`, `LICENSE`, notices, plus an
asset SHA-256 manifest. The builder itself and tests are intentionally **not**
part of the end-user delivery. Full Russian deployment instructions are in
`INSTALL_RU.md`, also included in each release archive. Local demo hosting is supported by the included Python standard-library launcher.
Bank production security acceptance remains separate.

## Run / deliver

For the **current demo on one computer**, extract the clean ZIP and run
`py -3 start_local.py` (Windows) or `python3 start_local.py` (macOS/Linux).
Open `http://127.0.0.1:8080/` in your browser; no pre-existing bank server is assumed.
The local launcher uses Python's standard library and binds **only** to loopback.
See `INSTALL_RU.md` for complete steps. A bank-managed HTTP(S) server is only a
possible future deployment target and requires separate authorization.

Developer smoke on a machine that already has Python or another HTTP server:

```sh
cd attribute-lineage-explorer
python3 start_local.py
# Open http://127.0.0.1:8080/ with a modern browser
```

Deterministic test suite on a developer machine with Node >=20 (not required by end users):

```sh
node tests/test-core.mjs
node tests/test-web.mjs
```

## UI

- **Обзор систем**: four synthetic system areas and interaction summary.
- **Поток атрибутов**: focus, directed upstream/downstream traversal, journeys,
  evidence and explicit gaps.
- **Паутина**: all typed nodes and links, click to highlight directed incoming and
  outgoing reachability, search, fit/zoom and presentation view; candidate crossings
  are dashed and may be excluded from traversal.
- Use local JSON upload to replace the included synthetic data, in memory only.
  Example labels and `synthetic` banner apply to the bundled demo only.

Sample batch: 3 interactions, 15 journeys, 86 unique local nodes, 64 local edges,
13 candidate crossings with two anchors, 16 diagnostic gap records; 9 weakly
connected components. These counts are checks for the **synthetic** sample, not
requirements for any actual customer data.

## Security and licensing

All scripts/styles/fonts/icons are local; the static app uses standard browser
HTML, CSS, SVG, and JavaScript without third-party packages. See `LICENSE` and
`THIRD_PARTY_NOTICES.md`. CSP in `index.html` disables network connections, inline
script execution and form posting. User-provided content is rendered with DOM text
nodes, not interpreted as HTML. User JSON is neither uploaded nor persisted in
browser storage.

**Deployment acceptance is not complete:** confirm CSP on the actual internal
web server, supported browser versions, supply-chain/OSS review and asset network
behavior in the target bank environment before declaring production readiness.

## Ownership

Independent external consumer module within `aisl-application`; it does not change
`interaction-lineage` producer or its public JSON contract. The source material is
synthetic only. Task 51 remains the project-level `PROJECT_CONTINUATION` owner.
