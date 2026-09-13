"""Side-project structural checks, not a JSON Schema validator or runtime acceptance."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.compare import loads


def check(condition, message):
    if not condition:
        raise ValueError(message)


def resolve_local_refs(document):
    pending = [document]
    count = 0
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                check(ref.startswith("#/"), f"external ref needs review: {ref}")
                target = document
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
                count += 1
            pending.extend(value.values())
    return count


def validate(root=ROOT):
    documents = {p.relative_to(root).as_posix(): loads(p.read_text(encoding="utf-8")) for p in root.rglob("*.json")}
    required = ["README.md", "learner/spec/ARCHITECTURE_SPEC.md", "learner/spec/FUNCTIONAL_SLICE.md",
                "learner/spec/BUILD_AND_RUNTIME_SPEC.md", "learner/spec/IMPLEMENTATION_FREEDOM.md",
                "learner/spec/EQUIVALENCE.md", "reviewer/GAPS.md", "benchmark/PROTOCOL.md"]
    for name in required:
        check((root / name).is_file(), f"missing document: {name}")
    check(not list((root / "learner").rglob("*.py")), "implementation code in learner pack")
    baseline = documents["reviewer/BASELINE.json"]
    check(baseline["source_manifest_verified"] == 828, "baseline manifest mismatch")
    check(baseline["framework_modified"] is False, "unexpected framework mutation claim")
    check(baseline["scored_run_status"] == "NOT_RUN_SPEC_INCOMPLETE", "draft must not claim scored readiness")
    spec = documents["learner/public-contracts/knowledge.selected.openapi.json"]
    refs = resolve_local_refs(spec)
    for name, doc in documents.items():
        if name.endswith(".schema.json"):
            refs += resolve_local_refs(doc)
    selected = documents["learner/public-contracts/tools.selected.json"]
    for name, tool in selected.items():
        binding = tool["api_binding"]
        operation = spec["paths"][binding["path_template"]][binding["method"].lower()]
        check(operation["operationId"] == binding["operation_id"], f"binding drift: {name}")
        check(binding["revision_binding"]["value_from"] == "scope.revision_id", f"unpinned binding: {name}")
    profile_count = 0
    for name, doc in documents.items():
        if not name.startswith("learner/examples/profile-"):
            continue
        profile_count += 1
        profile = doc["expected"]
        ctx = doc["input"]
        check(profile["scope"]["revision_id"] == ctx["revision_id"], "profile revision drift")
        check(profile["scope"]["system_id"] == ctx["system_id"], "profile system drift")
        check(profile["scope"]["revision_binding"] == "pinned", "profile not pinned")
        check(profile["capabilities"] == ctx["capabilities"], "profile capabilities drift")
        for tool in profile["tools"]:
            check(set(tool["required_capabilities"]) <= set(ctx["capabilities"]), "tool exceeds fixture capability")
            check(tool["name"] != "get_knowledge_context", "embedded context wrongly externalized")
        if not ctx["capabilities"]:
            check({t["name"] for t in profile["tools"]} == {"get_knowledge_item"}, "empty profile tool drift")
    inventory = documents["reviewer/CONTRACT_INVENTORY.json"]
    families = {x["knowledge_id"]: x for x in inventory["knowledge_families"]}
    check(families["interaction-islands"]["scope_status"] == "excluded_unregistered_parked", "parked feature included")
    check(all(x["current_run"]["published"] == "not_observed" for x in families.values()), "false runtime acceptance")
    counts = documents["reviewer/COUNTS.json"]
    check(len(selected) == counts["selected_tools"], "tool count drift")
    check(len(spec["paths"]) == counts["selected_api_paths"], "API count drift")
    check(profile_count == counts["profile_examples_executed"], "profile count drift")
    pipeline = documents.get("reviewer/PIPELINE_PROBES.json")
    if pipeline:
        check(pipeline["status"] == "PASS", "latest pipeline probe is incomplete or failed")
        check(all(c["status"] == "PASS" for c in pipeline["checks"]), "failed pipeline assertion")
        check(pipeline["check_count"] == len(pipeline["checks"]), "pipeline count drift")
    return {"status": "PASS", "kind": "side_project_structural_checks_only", "json_files": len(documents),
            "local_refs_resolved": refs, "selected_tools": len(selected), "selected_api_paths": len(spec["paths"]),
            "profile_fixture_checks": profile_count, "scored_readiness": False,
            "full_json_schema_validation": "not_performed_by_this_validator",
            "reference_pipeline": {"status": pipeline["status"], "boundary": pipeline["execution_boundary"],
                                   "checks": pipeline["check_count"], "schema_validation": pipeline["schema_validation"]} if pipeline else None,
            "pipeline_acceptance": "diagnostic_reference_only" if pipeline else "not_run",
            "kcp_full_journey": "not_run", "deepseek": "not_run"}


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
