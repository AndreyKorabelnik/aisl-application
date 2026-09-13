"""Bounded reference drift evidence; delegates integrity and tests to owners."""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile

from derive_reference import BASELINE, SHA, dump, module


def run(previous, current, dependencies, output):
    paths = [str(dependencies)] + [str(p / "src" if (p / "src").is_dir() else p) for p in sorted((current / "packages").iterdir()) if p.is_dir()]
    sys.path[:0] = paths
    os.environ["AISL_INTEGRATION_CONTENT_DIR"] = str(current / "integration-content")
    for i, root in enumerate([previous, current]):
        module("rebase_owner_" + str(i), root / "tools/build-aisl-deliveries.py").read_source_manifest(root)
    old_files = {p.relative_to(previous).as_posix(): p for p in previous.rglob("*") if p.is_file()}
    new_files = {p.relative_to(current).as_posix(): p for p in current.rglob("*") if p.is_file()}
    changes = []
    for name in sorted(old_files.keys() | new_files.keys()):
        old_sha = hashlib.sha256(old_files[name].read_bytes()).hexdigest() if name in old_files else None
        new_sha = hashlib.sha256(new_files[name].read_bytes()).hexdigest() if name in new_files else None
        if old_sha != new_sha:
            changes.append({"path": name, "old_sha256": old_sha, "new_sha256": new_sha})
    checks = []
    tests = [
        ("test_sql_script_structure.py", "test_control_flow_embedded_insert_reuses_canonical_sql_join_owner"),
        ("test_sql_script_structure.py", "test_assignment_embedded_select_remains_deferred_script_evidence"),
        ("test_sql_scoped_columns.py", "test_unqualified_column_ignores_non_binding_hint_read_when_declared_source_is_unique"),
    ]
    for index, (file, name) in enumerate(tests):
        test = module("rebase_test_" + str(index), current / "packages/code-analyzer-core/tests" / file)
        with tempfile.TemporaryDirectory(prefix="sdd-rebase-") as temp:
            getattr(test, name)(Path(temp))
        checks.append({"name": name, "status": "PASS", "owner_test": "packages/code-analyzer-core/tests/" + file})
    from knowledge_integration import generate_integration_profile
    ctx = {"system_id": "fixture-system", "revision_id": "revision-001", "capabilities": ["common.sql-analysis", "common.sql-relation-materialization"], "knowledge_artifacts": []}
    profile = generate_integration_profile(ctx, profile_id="sql-analysis/v1").to_dict()
    assert "list_sql_relation_materializations" in {t["name"] for t in profile["tools"]}
    without = generate_integration_profile({**ctx, "capabilities": ["common.sql-analysis"]}, profile_id="sql-analysis/v1").to_dict()
    assert "list_sql_relation_materializations" not in {t["name"] for t in without["tools"]}
    checks.append({"name": "materialization_tool_exact_capability_gate", "status": "PASS"})
    dump(output / "reviewer/oracles/rebase-materialization-profile.json", {"input": ctx, "with_capability": profile, "without_capability": without})
    module("rebase_final_owner", current / "tools/build-aisl-deliveries.py").read_source_manifest(current)
    dump(output / "reviewer/REBASE_F495.json", {"status": "PASS", "from": "F4.92", "to": BASELINE, "to_archive_sha256": SHA,
        "changed_file_count": len(changes), "changes": changes, "checks": checks, "framework_modified": False,
        "scope": "Read-only drift review and 3 existing owner tests plus profile capability gate; not full Framework regression"})
    print({"changes": len(changes), "targeted_checks": len(checks), "status": "PASS"})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for arg in ["previous", "current", "dependencies", "output"]:
        p.add_argument("--" + arg, type=Path, required=True)
    a = p.parse_args()
    sys.dont_write_bytecode = True
    run(a.previous.resolve(), a.current.resolve(), a.dependencies.resolve(), a.output.resolve())
