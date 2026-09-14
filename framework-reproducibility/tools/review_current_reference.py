"""Export current-reference drift and coverage using the Framework's existing owners.

Historical F4.95 learner/oracle files are deliberately not relabelled or overwritten.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from derive_reference import dump, module
from probe_production import REFERENCE_SHA, REFERENCE_COMMIT


def review(source, archive, old_source, dependencies, output):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != REFERENCE_SHA:
        raise ValueError("reference ZIP SHA mismatch")
    owner = module("current_integrity", source / "tools/build-aisl-deliveries.py")
    current = owner.read_source_manifest(source)
    old_owner = module("old_integrity", old_source / "tools/build-aisl-deliveries.py")
    old_owner.read_source_manifest(old_source)
    sys.path[:0] = [str(dependencies)] + [str(p / "src" if (p / "src").is_dir() else p)
        for p in sorted((source / "packages").iterdir()) if p.is_dir()]
    os.environ["AISL_INTEGRATION_CONTENT_DIR"] = str(source / "integration-content")
    from knowledge_integration.semantic_coverage import semantic_knowledge_coverage_report
    coverage = semantic_knowledge_coverage_report(source)
    if coverage["status"] != "pass":
        raise ValueError("canonical semantic coverage gate failed")
    def files(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}
    before, after = files(old_source), files(source)
    changes = [{"path": p, "before_sha256": before.get(p), "after_sha256": after.get(p),
                "change": "added" if p not in before else "deleted" if p not in after else "modified"}
        for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    report = {"from": "F4.95", "to": "F4.103", "commit": REFERENCE_COMMIT,
        "source_sha256": REFERENCE_SHA, "source_bytes": archive.stat().st_size,
        "source_manifest_entries": len(current["files"]), "changes": changes,
        "change_count": len(changes), "framework_modified": False,
        "interpretation": "full SDD rebase pending; old F4.95 outputs retain original provenance",
        "coverage_owner": "knowledge_integration.semantic_coverage.semantic_knowledge_coverage_report",
        "coverage_is_runtime_acceptance": False}
    owner.read_source_manifest(source)
    dump(output / "REBASE_REVIEW.json", report)
    dump(output / "SEMANTIC_COVERAGE.json", coverage)
    print(json.dumps({"manifest":len(current["files"]),"changes":len(changes),
        "coverage":coverage["status"], "framework_modified":False}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ["source", "archive", "old-source", "dependencies", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    sys.dont_write_bytecode = True
    review(**{k:v.resolve() for k,v in vars(args).items()})
