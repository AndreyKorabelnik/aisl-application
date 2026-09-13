"""Reviewer-only export from a pinned baseline; not a framework registry or parser.

Uses the existing integrity owner, capability trace and Integration Profile generator.
Source code is never copied into the learner directory.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib

BASELINE = "F4.95"
SHA = "fb3b7134194eddb9d6ac25b184ef046516b368b1aec513c2a29d61a397cd88f3"
SOURCE_DRIVE_ID = "1xwrSdDAHaIimizq1mdy40-ufmC_i7EE5"
RUNTIME = "packages/knowledge-control-plane/src/knowledge_control_plane/resources/runtime_contracts/"
SELECTED_TOOLS = {
    "list_sql_joins", "get_sql_query_context", "get_sql_column_usage_context",
    "get_sql_target_column_lineage", "list_sql_placeholder_binding_resolutions",
    "get_declared_data_model_summary", "search_declared_data_objects",
    "get_declared_data_object", "get_data_model_object_context", "get_knowledge_item",
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def literal(path, name):
    # Python's production AST, not regexp/manual source parsing.
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"literal not found: {name}")


def project_openapi(source, paths):
    result = {"openapi": source["openapi"], "info": source["info"], "paths": paths}
    pending = [result]
    components = {}
    while pending:
        obj = pending.pop()
        if isinstance(obj, dict):
            ref = obj.get("$ref")
            if ref:
                if not ref.startswith("#/components/"):
                    raise ValueError(f"unsupported ref needs review: {ref}")
                _, _, category, name = ref.split("/")
                if name not in components.setdefault(category, {}):
                    definition = source["components"][category][name]
                    components[category][name] = definition
                    pending.append(definition)
            pending.extend(obj.values())
        elif isinstance(obj, list):
            pending.extend(obj)
    result["components"] = components
    return result


def derive(root: Path, archive: Path, target: Path):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA:
        raise ValueError("wrong baseline archive; explicit rebase required")
    owner = module("reference_delivery_owner", root / "tools/build-aisl-deliveries.py")
    manifest = owner.read_source_manifest(root)
    dump(target / "reviewer/REFERENCE_SOURCE_MANIFEST.json", manifest)
    provenance = []

    def observe(rel):
        data = (root / rel).read_bytes()
        provenance.append({"source_path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        return data

    def read(rel):
        return json.loads(observe(rel))

    knowledge = read(RUNTIME + "knowledge-catalog.json")
    mats = read(RUNTIME + "knowledge-materialization-catalog.json")
    evidence = read(RUNTIME + "core-evidence-contract-catalog.json")
    analysis = read(RUNTIME + "core-analysis-catalog.json")
    delivery = read("SOURCE_TO_DELIVERY_MAP.json")
    trace = module("reference_capability_trace", root / "tools/capability_trace.py")
    observe("tools/capability_trace.py")
    caps = sorted({c for row in mats["materializations"] for key in ("capabilities", "conditional_capabilities") for c in row["outputs"].get(key, [])})
    traces = [trace.build_capability_trace(source_root=root, capability=c) for c in caps]
    dump(target / "reviewer/capability-traces.json", traces)
    os.environ["AISL_INTEGRATION_CONTENT_DIR"] = str(root / "integration-content")
    sys.path.insert(0, str(root / "packages/knowledge-integration"))
    from knowledge_integration import canonical_tool_definitions, generate_integration_profile
    tools = canonical_tool_definitions()
    openapi = read("packages/knowledge-api/schemas/knowledge-v1.openapi.json")
    ops = []
    for path, item in openapi["paths"].items():
        for method, op in item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            ops.append({"path": path, "method": method.upper(), "operation_id": op.get("operationId"),
                        "parameters": op.get("parameters", []), "requestBody": op.get("requestBody"), "responses": op.get("responses", {})})
    by_mid = {m["materialization_id"]: m for m in mats["materializations"]}
    families = []
    for row in knowledge["knowledge_types"]:
        mid = row.get("materialization", {}).get("materialization_id")
        capset = set(row.get("materialization", {}).get("capabilities", []))
        consumers = sorted(n for n, t in tools.items() if capset.intersection(t.get("required_capabilities", [])))
        status = "candidate_needs_journey_acceptance"
        if row["knowledge_id"] == "interaction-islands":
            status = "excluded_unregistered_parked"
        if row["knowledge_id"] == "data-model-attribute-extension":
            status = "withheld_pending_current_demand_review"
        families.append({"knowledge_id": row["knowledge_id"], "materialization_id": mid,
                         "scope_status": status, "catalog_availability": row.get("availability"),
                         "producer_sources": row.get("sources"), "knowledge_inputs": row.get("knowledge_inputs"),
                         "capabilities": sorted(capset), "consumer_tool_candidates": consumers,
                         "outputs": by_mid.get(mid, {}).get("outputs"),
                         "current_run": {"executed": "not_observed", "published": "not_observed", "real_consumer": "not_observed"}})
    dump(target / "reviewer/CONTRACT_INVENTORY.json", {
        "baseline": BASELINE, "status": "derived_review_inventory_not_runtime_owner",
        "knowledge_families": families, "materializations": mats["materializations"],
        "evidence_contracts": evidence["contracts"], "analysis_catalog": analysis,
        "tools": tools, "api_operations": ops,
    })
    packages = []
    for rel in sorted({p for d in delivery["deliveries"].values() for p in d["source_modules"]}):
        if (root / rel / "pyproject.toml").exists():
            pp = tomllib.loads(observe(rel + "/pyproject.toml").decode())
            p = pp["project"]
            packages.append({"source_module": rel, "name": p["name"], "version": p.get("version"), "requires_python": p.get("requires-python"),
                             "dependencies": p.get("dependencies", []), "entry_points": p.get("scripts", {}), "build_system": pp.get("build-system", {})})
        else:
            p = read(rel + "/package.json")
            packages.append({"source_module": rel, "name": p["name"], "version": p["version"], "dependencies": p.get("dependencies", {}), "entry_points": p.get("bin", {}), "engines": p.get("engines", {})})
    dump(target / "reviewer/BUILD_INVENTORY.json", {"delivery_composition": delivery, "packages": packages})
    for path in sorted((root / "packages/knowledge-integration/knowledge_integration").glob("*.py")):
        observe(path.relative_to(root).as_posix())
    for path in sorted((root / "integration-content").rglob("*")):
        if path.is_file():
            observe(path.relative_to(root).as_posix())

    selected = {n: tools[n] for n in sorted(SELECTED_TOOLS)}
    dump(target / "learner/public-contracts/tools.selected.json", selected)
    paths = {}
    for t in selected.values():
        b = t["api_binding"]
        path, method = b["path_template"], b["method"].lower()
        paths.setdefault(path, {})[method] = openapi["paths"][path][method]
    # Discovery and publication are part of the slice; all other routes remain reviewer-only.
    suffixes = ("/revisions", "/revisions/{revision_id}", "/capabilities", "/public-knowledge-catalog", "/llm-integration-profile")
    for path, item in openapi["paths"].items():
        if "/systems/{system_id}/" in path and path.endswith(suffixes):
            paths[path] = item
        if path in {"/api/knowledge/v1/systems", "/api/knowledge/v1/health"}:
            paths[path] = item
    dump(target / "learner/public-contracts/knowledge.selected.openapi.json", project_openapi(openapi, paths))
    for rel in ["packages/knowledge-integration/knowledge_integration/schemas/llm_integration_profile_v1.schema.json",
                "packages/knowledge-integration/knowledge_integration/schemas/aisl_public_knowledge_catalog_v1.schema.json",
                "packages/knowledge-layer-core/schemas/knowledge-layer-manifest-v1.schema.json",
                "packages/knowledge-layer-core/schemas/knowledge-layer-build-request-v1.schema.json"]:
        dst = target / "learner/public-contracts" / Path(rel).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(observe(rel))
    # Schema data are projected with the standard AST, without copying production code.
    rel = "packages/knowledge-layer-core/knowledge_layer_core/sql_analysis_schema.py"
    observe(rel)
    tree = ast.parse((root / rel).read_text())
    facts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SqlFactSchema":
            name, identity, fields = [ast.literal_eval(x) for x in node.args]
            facts.append({"fact_type": name, "id_field": identity, "fields": list(fields)})
    dump(target / "learner/public-contracts/sql.fact-fields.json", {"schema_version": "knowledge_layer_sql/v2", "field_names_only": True, "facts": facts,
          "warning": "Not a full nested JSON Schema. Nullability, nested records and identifier algorithms remain gaps; do not infer them."})
    for name, caps_for_case in [("sql", ["common.sql-analysis"]), ("declared", ["common.code-declared-data-model"]), ("empty", [])]:
        profile_id = "data-model/v1" if name == "declared" else "sql-analysis/v1"
        ctx = {"system_id": "fixture-system", "revision_id": "revision-001", "capabilities": caps_for_case, "knowledge_artifacts": []}
        profile = generate_integration_profile(ctx, profile_id=profile_id).to_dict()
        dump(target / f"learner/examples/profile-{name}.json", {"input": ctx, "profile_id": profile_id, "expected": profile,
            "evidence_level": "current_generator_run_synthetic_context_not_published_revision"})
    baseline = {"source_checkpoint": BASELINE, "source_sha256": SHA, "source_bytes": archive.stat().st_size,
                "source_drive_file_id": SOURCE_DRIVE_ID, "source_manifest_verified": len(manifest["files"]),
                "rules": {"version": "1.10", "drive_file_id": "1WjK8qsEaIJDjcwTn62HJndAliEYGUj6i"},
                "framework_modified": False, "model_policy": "latest publicly available DeepSeek at first scored run; pin exact served model for the experiment",
                "selected_model_id": None, "scored_run_status": "NOT_RUN_SPEC_INCOMPLETE"}
    dump(target / "reviewer/BASELINE.json", baseline)
    exports = []
    for path in sorted((target / "learner/public-contracts").glob("*")):
        if path.name == "knowledge.selected.openapi.json":
            origins = ["packages/knowledge-api/schemas/knowledge-v1.openapi.json"]
            transform = "selected operations with transitive local component reference closure"
        elif path.name == "tools.selected.json":
            origins = [r["source_path"] for r in provenance if r["source_path"].startswith(("packages/knowledge-integration/knowledge_integration/", "integration-content/"))]
            transform = "10 selected exact outputs of canonical_tool_definitions"
        elif path.name == "sql.fact-fields.json":
            origins = ["packages/knowledge-layer-core/knowledge_layer_core/sql_analysis_schema.py"]
            transform = "Python AST projection of SqlFactSchema declarative arguments; not nested schema"
        else:
            origins = [r["source_path"] for r in provenance if Path(r["source_path"]).name == path.name]
            transform = "byte-for-byte public schema copy"
        if not origins:
            raise ValueError(f"export missing provenance: {path.name}")
        exports.append({"export": path.relative_to(target).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "source_paths": sorted(set(origins)), "transformation": transform})
    dump(target / "reviewer/PROVENANCE.json", {"baseline_sha256": SHA, "sources": sorted(provenance, key=lambda r: r["source_path"]), "exports": exports})
    stats = {"knowledge_families": len(families), "materialization_contracts": len(mats["materializations"]),
             "core_evidence_contracts": len(evidence["contracts"]), "tools": len(tools), "api_paths": len(openapi["paths"]), "api_operations": len(ops),
             "delivery_modules": len(packages), "capabilities_traced": len(traces), "selected_tools": len(selected),
             "selected_api_paths": len(paths), "sql_fact_kinds": len(facts), "profile_examples_executed": 3}
    dump(target / "reviewer/COUNTS.json", stats)
    # Reuse the existing owner after all read-only probes to prove the baseline stayed intact.
    owner.read_source_manifest(root)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    derive(args.source.resolve(), args.archive.resolve(), args.output.resolve())
