# Test status

Version: 0.1.0a8
Date: 2026-09-07

- full package pytest on clean working source: 42/42 PASS;
- `repository-topology/v3` JSON Schema validation: PASS;
- synthetic 1595-repository zero-half-wire diagnostic acceptance: PASS;
- synthetic 1595-repository mixed match/mismatch diagnostic acceptance: PASS;
- wheel build with `pip wheel --no-deps --no-build-isolation`: PASS;
- wheel SHA-256: `f728073e92383b932928b59e3df69d0e5e0fef281a799e89e8c8b5f22573c7c4`;
- clean venv install/import: PASS;
- installed CLI help: PASS;
- frozen Source ZIP manifest verification after extraction: PASS;
- pytest from extracted frozen Source ZIP: 42/42 PASS.

Harness note: `python -m build` is unavailable in the current environment (`No module named build`). Production source was not changed; wheel construction used another standard frontend over the same setuptools build backend.
