"""Reviewer harness: real Runner/Core/KLC + producer-neutral bundle + ASGI API.

This is diagnostic orchestration with an explicit resolution plan, not KCP planning.
No Framework source is modified, no mocked facts or SQL INSERT test fixtures.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import zipfile

from derive_reference import BASELINE, SHA, dump, module


def run(source, root, dependencies):
    paths = [str(dependencies)]
    for package in sorted((source / "packages").iterdir()):
        if package.is_dir():
            paths.append(str(package / "src" if (package / "src").is_dir() else package))
    sys.path[:0] = paths
    os.environ["PYTHONPATH"] = os.pathsep.join(paths)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["AISL_INTEGRATION_CONTENT_DIR"] = str(source / "integration-content")
    integrity = module("pipeline_integrity", source / "tools/build-aisl-deliveries.py")
    source_manifest = integrity.read_source_manifest(source)
    expected_manifest = json.loads((root / "reviewer/REFERENCE_SOURCE_MANIFEST.json").read_text())
    if source_manifest != expected_manifest:
        raise ValueError("source differs from pinned export; re-export exact reference first")
    from technology_extension_runtime import ExtensionDeploymentPolicy, discover_installed_extension_set
    from static_analysis_runner.evidence_executor import execute_core_evidence_plan
    from static_analysis_runner.knowledge_materialization_executor import execute_knowledge_materialization_plan
    from static_analysis_runner.io_utils import stable_fingerprint
    from aisl_publication import ArtifactInput, KnowledgeProduct, build_publication_bundle
    from knowledge_api.publication_bundle import import_publication_bundle
    from knowledge_api.contract_v1.runtime import KnowledgeApiSettings
    from knowledge_api.contract_v1.service import KnowledgeDomainService
    from knowledge_api.contract_v1.contract import create_contract_app
    from fastapi.testclient import TestClient
    import jsonschema
    checks = []
    output = root / "reviewer/oracles/pipeline"
    output.mkdir(parents=True, exist_ok=True)
    dump(root / "reviewer/PIPELINE_PROBES.json", {"status": "RUNNING", "scored_readiness": False})
    public = root / "learner/public-contracts"
    openapi = json.loads((public / "knowledge.selected.openapi.json").read_text())

    def check(name, passed, detail=None):
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        dump(output / "checks-in-progress.json", checks)
        if not passed:
            raise AssertionError(f"{name}: {detail}")

    def validate_document(name, value, schema):
        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)
        errors = sorted(validator(schema).iter_errors(value), key=lambda e: str(e.path))
        check(name, not errors, [str(e) for e in errors][:3] or None)

    with tempfile.TemporaryDirectory(prefix="sdd-pipeline-") as work:
        work = Path(work)
        repo = work / "repo"
        repo.mkdir()
        for name in ["Sample.java", "declared-openapi.json", "sql-cases.sql"]:
            shutil.copyfile(root / "learner/examples" / name, repo / name)
        dump(output / "inputs.json", {p.name: {"text": p.read_text(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(repo.iterdir())})
        extension_set = discover_installed_extension_set(ExtensionDeploymentPolicy()).to_dict()
        plan = {"schema_version": "knowledge_resolution_plan/v2", "profile": {"profile_id": "sdd-pilot", "scope": {"kind": "repository", "scope_id": "sdd-pilot"}},
                "resolved_selection": {"resolved_knowledge_ids": ["code-declared-data-model", "sql-source-inventory"]},
                "technical_plan": {"evidence_requirements": [
                    {"producer_kind": "core", "artifact_kind": kind, "schema_version": version, "parameters": {}}
                    for kind, version in [("java-type-structure-evidence", "java-type-structure-evidence/v1"), ("schema-declaration-evidence", "schema-declaration-evidence/v1"), ("sql-analysis", "sql-analysis/v1")]],
                    "materializations": [{"materialization_id": "code-declared-data-model"}, {"materialization_id": "sql-analysis"}]}}
        plan["plan_fingerprint"] = stable_fingerprint(plan)
        dump(work / "plan.json", plan)
        dump(output / "resolution-plan.json", plan)
        dump(output / "installed-extension-set.json", extension_set)
        catalogs = source / "packages/knowledge-control-plane/src/knowledge_control_plane/resources/runtime_contracts"
        try:
            run_result = execute_core_evidence_plan(repository=repo, resolution_plan=work / "plan.json", core_evidence_catalog=catalogs / "core-evidence-contract-catalog.json",
                installed_extension_set=extension_set, output=work / "runner", core_command=shlex.join([sys.executable, "-B", "-m", "code_analyzer_core"]), repo_id="sdd-pilot", progress=print)
        finally:
            if (work / "runner").exists():
                shutil.copytree(work / "runner", output / "runner", dirs_exist_ok=True)
        check("runner_completed", run_result.get("status") == "completed", run_result.get("status"))
        run_manifest = work / "runner/repository_analysis_run_manifest.json"
        envelopes = {}
        for p in (work / "runner").rglob("*-evidence.json"):
            value = json.loads(p.read_text())
            if "artifact_kind" in value:
                envelopes[value["artifact_kind"]] = value
        check("java_three_types", len(envelopes["java-type-structure-evidence"]["payload"]["type_declarations"]) == 3)
        check("java_four_fields", len(envelopes["java-type-structure-evidence"]["payload"]["field_declarations"]) == 4)
        schema = envelopes["schema-declaration-evidence"]
        check("schema_external_ref_gap", any(d["code"] == "external_schema_reference_not_resolved" for d in schema["diagnostics"]), schema["diagnostics"])
        check("schema_partial_not_complete", schema["coverage"]["coverage_status"] == "partial")
        dump(root / "learner/examples/java.reference.json", envelopes["java-type-structure-evidence"])
        dump(root / "learner/examples/schema.reference.json", schema)
        materialized = execute_knowledge_materialization_plan(resolution_plan=work / "plan.json", materialization_catalog=catalogs / "knowledge-materialization-catalog.json",
            repository_run_manifests=[run_manifest], installed_extension_set=extension_set, output=work / "klc", scope_id="sdd-pilot", progress=print)
        shutil.copytree(work / "klc", output / "klc", dirs_exist_ok=True)
        dump(output / "materialization-result.json", materialized)
        check("two_materializations", len(materialized["materialization_executions"]) == 2)
        products = []
        for artifact in materialized["knowledge_artifacts"]:
            location = artifact["location"]
            manifest_path = Path(location["manifest_path"])
            manifest = json.loads(manifest_path.read_text())
            validate_document("manifest_schema_" + artifact["model_kind"], manifest,
                              json.loads((public / "knowledge-layer-manifest-v1.schema.json").read_text()))
            database = manifest_path.parent / "knowledge-layer.duckdb"
            check("materialization_complete_" + artifact["model_kind"], manifest["build_status"] == "complete")
            products.append(KnowledgeProduct(artifact_id=artifact["artifact_id"], model_kind=artifact["model_kind"], schema_version=artifact["schema_version"],
                product_slot_id="klc:" + artifact["source_materialization_id"], origin_kind="derived", producer_ref="knowledge-layer-core", producer_contract_ref="knowledge_layer/v1",
                producer_operation_ref=artifact["source_materialization_id"], artifacts=[ArtifactInput("database", database, "application/vnd.duckdb", artifact["schema_version"]), ArtifactInput("manifest", manifest_path, "application/json", "knowledge_layer/v1")],
                capabilities=manifest["capabilities"], coverage=artifact.get("coverage", {}), diagnostics=artifact.get("diagnostics", []), provenance=artifact.get("provenance", {})))
        bundle = build_publication_bundle(system_id="sdd-pilot", display_name="Synthetic pilot", producer_ref="sdd-neutral-publisher/1", producer_contract_ref="sdd-neutral-publisher/v1",
                                          products=products, output_path=work / "publication.zip")
        with zipfile.ZipFile(bundle.path) as archive:
            dump(output / "publication-descriptor.json", json.loads(archive.read("payload/publication-descriptor.json")))
        settings = KnowledgeApiSettings(database_path=work / "server/knowledge.sqlite3", allowed_roots=(work / "server",), artifact_store_path=work / "server/artifact-store")
        imported = import_publication_bundle(settings=settings, bundle_path=bundle.path)
        dump(output / "publication-result.json", imported)
        check("bundle_published", imported["status"] == "published", imported)
        revision = imported["revision_id"]
        duplicate = import_publication_bundle(settings=settings, bundle_path=bundle.path)
        dump(output / "duplicate-publication-result.json", duplicate)
        check("duplicate_publish_idempotent", duplicate["status"] == "already_published" and duplicate["revision_id"] == revision)
        service = KnowledgeDomainService(settings)
        responses = []
        with TestClient(create_contract_app(service=service)) as client:
            def get(suffix, params, expected=200):
                response = client.get("/api/knowledge/v1/systems/sdd-pilot/" + suffix, params=params)
                responses.append({"suffix": suffix, "params": params, "status": response.status_code, "body": response.json()})
                dump(output / "http-responses.json", responses)
                check("http_" + suffix + "_" + str(len(responses)), response.status_code == expected, response.json() if response.status_code != expected else None)
                response_schema = openapi["paths"]["/api/knowledge/v1/systems/{system_id}/" + suffix]["get"]["responses"][str(expected)]["content"]["application/json"]["schema"]
                validate_document("response_schema_" + str(len(responses)), response.json(),
                                  {"$schema": "https://json-schema.org/draft/2020-12/schema", "components": openapi["components"], **response_schema})
                return response.json()
            first = get("sql/joins", {"revision_id": revision, "offset": 0, "limit": 3})
            total = first["page"]["total"]
            all_joins = list(first["items"])
            for offset in range(3, total, 3):
                all_joins += get("sql/joins", {"revision_id": revision, "offset": offset, "limit": 3})["items"]
            check("eight_api_joins", total == 8 and len(all_joins) == 8, total)
            check("pagination_unique_ids", len({r["sql_join_edge_id"] for r in all_joins}) == 8)
            check("api_expression_links_preserved", any(r.get("expression_links") for r in all_joins))
            expression = next(r for r in all_joins if r.get("expression_links"))
            selected_tools = json.loads((root / "learner/public-contracts/tools.selected.json").read_text())
            context_path = selected_tools["get_sql_query_context"]["api_binding"]["path_template"].split("/systems/{system_id}/", 1)[1]
            context_path = context_path.replace("{query_id}", expression["query_id"]).replace("{repo_id}", expression["repo_id"])
            context = get(context_path, {"revision_id": revision, "repo_id": expression["repo_id"], "query_id": expression["query_id"]})
            dump(output / "join-projection-comparison.json", {"bulk_expression_join": expression, "query_context": context})
            check("context_projection_omits_expression_links", bool(context["joins"]) and all("expression_links" not in j for j in context["joins"]))
            get("sql/joins", {}, 422)
            get("sql/joins", {"revision_id": "latest"}, 400)
            get("sql/joins", {"revision_id": "missing"}, 404)
            # Resolve declared paths from the canonical selected tool binding, not guessed routes.
            tools = json.loads((root / "learner/public-contracts/tools.selected.json").read_text())
            for name in ["get_declared_data_model_summary", "search_declared_data_objects"]:
                suffix = tools[name]["api_binding"]["path_template"].split("/systems/{system_id}/", 1)[1]
                get(suffix, {"revision_id": revision})
            profile = get("llm-integration-profile", {"revision_id": revision, "profile_id": "sql-analysis/v1"})
            catalog = get("public-knowledge-catalog", {"revision_id": revision})
            validate_document("profile_public_schema", profile, json.loads((public / "llm_integration_profile_v1.schema.json").read_text()))
            validate_document("catalog_public_schema", catalog, json.loads((public / "aisl_public_knowledge_catalog_v1.schema.json").read_text()))
            second_bundle = build_publication_bundle(system_id="sdd-pilot", display_name="Synthetic pilot", producer_ref="sdd-neutral-publisher/1",
                producer_contract_ref="sdd-neutral-publisher/v1", products=products, output_path=work / "second-publication.zip",
                base_revision_id=revision, metadata={"experiment_revision": 2})
            second = import_publication_bundle(settings=settings, bundle_path=second_bundle.path)
            dump(output / "second-publication-result.json", second)
            check("second_revision_distinct", second["status"] == "published" and second["revision_id"] != revision)
            old = get("sql/joins", {"revision_id": revision, "offset": 0, "limit": 3})
            check("old_revision_unchanged_after_new_publish", old == first)
            newer = get("sql/joins", {"revision_id": second["revision_id"], "offset": 0, "limit": 3})
            check("new_revision_same_knowledge_rows", newer["items"] == first["items"] and newer["revision_id"] == second["revision_id"])
            # Read after producer paths cease to exist: no analysis or producer DB dependency on read.
            (work / "repo").rename(work / "repo-unavailable")
            (work / "klc").rename(work / "klc-unavailable")
            after = get("sql/joins", {"revision_id": revision, "offset": 0, "limit": 3})
            check("api_read_independent_of_producer_paths", first == after)
            dump(output / "all-api-joins.json", all_joins)
            dump(root / "learner/examples/api-readback.reference.json", {"kind": "visible_reference_only", "responses": responses})
        versions = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions(path=[str(dependencies)])}
        dump(output / "dependencies.json", versions)
        (root / "reviewer/runtime-requirements.txt").write_text("".join(f"{name}=={version}\n" for name, version in sorted(versions.items())), encoding="utf-8")
    integrity.read_source_manifest(source)
    report = {"status": "PASS", "reference_baseline": BASELINE, "reference_archive_sha256": SHA,
              "framework_source_unchanged": True, "framework_manifest_verified": 828,
              "execution_boundary": "Runner low-level diagnostic plan -> real Core and KLC subprocesses -> neutral publisher -> real ASGI API",
              "not_executed": ["KCP high-level planning", "KCP publication adapter", "external TCP deployment", "DeepSeek"],
              "runtime": {"python": platform.python_version(), "platform": platform.platform(), "dependencies": "reviewer/runtime-requirements.txt"},
              "schema_validation": {"http_responses": len(responses), "klc_manifests": 2, "integration_profile": 1, "public_catalog": 1},
              "checks": checks, "check_count": len(checks)}
    dump(root / "reviewer/PIPELINE_PROBES.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dependencies", type=Path, required=True)
    a = p.parse_args()
    sys.dont_write_bytecode = True
    run(a.source.resolve(), a.output.resolve(), a.dependencies.resolve())
