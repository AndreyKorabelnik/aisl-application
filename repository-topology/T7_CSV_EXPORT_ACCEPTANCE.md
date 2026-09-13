# T7 — CSV topology export acceptance

Date: 2026-09-07
Version: repository-topology 0.1.0a7
Status: ACCEPTED

## Need

Export all information from an already built repository topology into one CSV suitable for analysis in Excel.

## Boundary

CSV rendering is owned by `repository-topology` as a deterministic representation of `repository-topology/v2`. It does not read source code or Reduced Inventory and does not perform matching, island construction or attribute inference.

## Contract

Representation identifier: `repository-topology-csv/v1`.

Rows are long-form and distinguished by `record_type`: topology, island, repository, edge, attribute, diagnostic. This preserves isolated repositories and diagnostics that an edge-only CSV would silently lose.

Nested provenance/basis remains in deterministic canonical JSON columns. Attribute rows use canonical `attribute_flows`, one exact attribute name per row.

## Excel behavior

- UTF-8 BOM;
- CRLF line endings;
- comma default;
- optional semicolon/tab delimiters;
- formula-like plain-text cells are apostrophe-prefixed;
- canonical `record_json` retains exact original values.

## Acceptance evidence

- all record types present on synthetic topology with one connected pair plus one isolated repository: PASS;
- API/method/protocol/classification/confidence columns: PASS;
- request and response attributes with directed flow columns: PASS;
- diagnostics: PASS;
- full edge half-wire/basis JSON: PASS;
- deterministic repeated output: PASS;
- semicolon locale mode: PASS;
- formula-injection protection and exact-value retention: PASS;
- CLI: PASS;
- wrong topology format rejected: PASS;
- full package regression after feature: 35/35 PASS.
