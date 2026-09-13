"""Reviewer-only probes of unchanged pinned owners; no candidate implementation."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import zipfile

from derive_reference import BASELINE, SHA, module, dump


def probe(source, output, sqlglot_wheel):
    owner = module("probe_integrity_owner", source / "tools/build-aisl-deliveries.py")
    manifest = owner.read_source_manifest(source)
    if manifest != json.loads((output / "reviewer/REFERENCE_SOURCE_MANIFEST.json").read_text()):
        raise ValueError("source differs from pinned export")
    for rel in ["packages/code-analyzer-core", "packages/source-syntax-primitives", "packages/aisl-publication"]:
        sys.path.insert(0, str(source / rel))
    sys.path.insert(0, str(sqlglot_wheel))
    from code_analyzer_core.prepared_artifacts.sql_analysis_evidence import build_sql_analysis_evidence
    from code_analyzer_core.scanners.repo_scanner import scan_analyzer_files
    from aisl_publication import ArtifactInput, KnowledgeProduct, PublicationError, build_publication_bundle, validate_publication_descriptor
    import sqlglot
    import yaml
    if sqlglot.__version__ != "30.13.0":
        raise ValueError("wrong sqlglot reference version")
    checks = []

    def check(name, condition, detail=None):
        checks.append({"name": name, "status": "PASS" if condition else "FAIL", "detail": detail})
        if not condition:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(prefix="sdd-contract-probe-") as work:
        work = Path(work)
        repo = work / "repo"
        repo.mkdir()
        shutil.copyfile(output / "learner/examples/sql-cases.sql", repo / "sql-cases.sql")
        dump(output / "reviewer/oracles/core-sql/inputs.json", {p.name: p.read_text() for p in sorted(repo.iterdir())})
        envelope = build_sql_analysis_evidence(repository=repo, files=scan_analyzer_files(repo), repo_id="sdd-synthetic",
                                               output_root=work / "core", parameters={"project_code": "SDD", "system_name": "Synthetic SDD"})
        shard_root = work / "core/evidence/sql-analysis"
        joins = [json.loads(line) for line in (shard_root / "facts/sql_join_edge.jsonl").read_text().splitlines() if line]
        # Preserve the owner's exact output, including runtime metadata; do not call it full pipeline acceptance.
        shutil.copytree(work / "core/evidence", output / "reviewer/oracles/core-sql/evidence", dirs_exist_ok=True)
        dump(output / "reviewer/oracles/core-sql/envelope.json", envelope)
        main = [j for j in joins if j["file"] == "sql-cases.sql"]
        check("core_eight_join_clauses", len(main) == 8, len(main))
        check("core_expression_link_present", any(j.get("expression_links") and not j.get("column_pairs") for j in main))
        check("core_cross_has_no_fabricated_pairs", any(j["join_type"] == "cross" and not j["column_pairs"] and j["physical_join_confirmed"] for j in main))
        check("core_ambiguous_stays_partial", any(j["resolution_status"] == "partial" and not j["physical_join_confirmed"] for j in main))
        check("core_cte_not_physical", any(j["resolution_status"] == "confirmed" and not j["physical_join_confirmed"] for j in main))
        check("core_multicolumn_join", any(len(j["column_pairs"]) == 2 and j["additional_predicates"] for j in main))
        # A second owner run proves fact shard determinism, not timestamp/envelope byte equality.
        build_sql_analysis_evidence(repository=repo, files=scan_analyzer_files(repo), repo_id="sdd-synthetic",
                                    output_root=work / "core-repeat", parameters={"project_code": "SDD", "system_name": "Synthetic SDD"})
        shards = sorted((shard_root / "facts").glob("*.jsonl"))
        check("core_fact_shards_repeat_equal", all(p.read_bytes() == (work / "core-repeat/evidence/sql-analysis/facts" / p.name).read_bytes() for p in shards), len(shards))
        dump(output / "learner/examples/sql-joins.reference.json", {"evidence_level": "current_core_sql_owner_not_klc_publication_or_api", "repo_id": "sdd-synthetic", "input_file": "sql-cases.sql", "joins": main})
        # Isolate the diagnostic fixture so it cannot shift query ordinals in learner output.
        diagnostic_repo = work / "diagnostic-repo"
        diagnostic_repo.mkdir()
        diagnostic_input = "SELECT a.id FROM event a JOIN validity b ON b.start_time > a.event_time;\n"
        (diagnostic_repo / "reversed-range.sql").write_text(diagnostic_input, encoding="utf-8")
        build_sql_analysis_evidence(repository=diagnostic_repo, files=scan_analyzer_files(diagnostic_repo), repo_id="sdd-reversed",
                                    output_root=work / "diagnostic-core", parameters={"project_code": "SDD"})
        reversed_case = [json.loads(line) for line in (work / "diagnostic-core/evidence/sql-analysis/facts/sql_join_edge.jsonl").read_text().splitlines() if line]
        dump(output / "reviewer/oracles/reversed-range-observation.json", {"status": "OBSERVATION_REQUIRES_CONTRACT_DECISION", "input": diagnostic_input, "actual": reversed_case})

        payload = work / "result.json"
        payload.write_bytes(b'{"value":1}\n')
        product = KnowledgeProduct(artifact_id="synthetic-result", model_kind="synthetic-product", schema_version="synthetic-product/v1",
                                   product_slot_id="synthetic:result", origin_kind="observed",
                                   artifacts=[ArtifactInput(role="result", path=payload, media_type="application/json")],
                                   capabilities=["synthetic.read"], provenance={"basis": "synthetic contract probe"})
        kwargs = dict(system_id="synthetic-system", display_name="Synthetic system", producer_ref="sdd-probe/1",
                      producer_contract_ref="sdd-probe/v1", products=[product], labels=["z", "a", "z"])
        result = build_publication_bundle(**kwargs, output_path=work / "bundle.zip")
        repeat = build_publication_bundle(**kwargs, output_path=work / "repeat.zip")
        check("builder_repeat_byte_equal", result.path.read_bytes() == repeat.path.read_bytes())
        with zipfile.ZipFile(result.path) as bundle:
            descriptor = json.loads(bundle.read("payload/publication-descriptor.json"))
            manifest = json.loads(bundle.read("bundle-manifest.json"))
            members = {n: {"sha256": hashlib.sha256(bundle.read(n)).hexdigest(), "bytes": len(bundle.read(n))} for n in bundle.namelist()}
        check("builder_descriptor_valid", validate_publication_descriptor(descriptor) == descriptor)
        check("builder_labels_canonical", descriptor["publication_defaults"]["labels"] == ["a", "z"])
        check("builder_no_local_path", str(work) not in json.dumps(descriptor) and str(work) not in json.dumps(manifest))
        negatives = []
        for name, bad_products in [
            ("duplicate_slot", [product, replace(product, artifact_id="another")]),
            ("duplicate_artifact_id", [product, replace(product, product_slot_id="another")]),
            ("self_dependency", [replace(product, exact_dependency_product_ids=[product.artifact_id])]),
            ("invalid_origin", [replace(product, origin_kind="guessed")]),
        ]:
            try:
                build_publication_bundle(**{**kwargs, "products": bad_products}, output_path=work / (name + ".zip"))
            except PublicationError as exc:
                negatives.append({"case": name, "error_type": "PublicationError", "message": str(exc)})
                check("builder_" + name, True)
            else:
                check("builder_" + name, False)
        tampered = json.loads(json.dumps(descriptor))
        tampered["system"]["display_name"] = "changed"
        try:
            validate_publication_descriptor(tampered)
        except PublicationError as exc:
            negatives.append({"case": "tampered_fingerprint", "error_type": "PublicationError", "message": str(exc)})
            check("builder_tampered_fingerprint", True)
        else:
            check("builder_tampered_fingerprint", False)
        dump(output / "learner/examples/publication.reference.json", {"evidence_level": "current_builder_and_validator_not_server_import", "artifact_bytes_utf8": payload.read_text(),
             "descriptor": descriptor, "bundle_manifest": manifest, "zip_members": members, "negative_cases": negatives})
    owner.read_source_manifest(source)
    sources = ["packages/aisl-publication/aisl_publication/builder.py", "packages/code-analyzer-core/code_analyzer_core/sql_profile.py",
               "packages/code-analyzer-core/code_analyzer_core/prepared_artifacts/sql_analysis_evidence.py",
               "packages/knowledge-api/knowledge_api/publication_bundle.py", "packages/knowledge-api/knowledge_api/contract_v1/service.py"]
    report = {"status": "PASS", "reference_baseline": BASELINE, "reference_archive_sha256": SHA,
              "level": "core_sql_and_bundle_builder_only", "checks": checks,
              "python": platform.python_version(), "sqlglot": sqlglot.__version__, "pyyaml": yaml.__version__,
              "sqlglot_wheel_sha256": hashlib.sha256(sqlglot_wheel.read_bytes()).hexdigest(),
              "framework_manifest_verified": 828, "pipeline_acceptance": "NOT_RUN", "server_import": "NOT_RUN",
              "provenance": [{"path": p, "sha256": hashlib.sha256((source / p).read_bytes()).hexdigest()} for p in sources]}
    dump(output / "reviewer/CONTRACT_PROBES.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sqlglot-wheel", type=Path, required=True)
    args = p.parse_args()
    sys.dont_write_bytecode = True
    probe(args.source.resolve(), args.output.resolve(), args.sqlglot_wheel.resolve())
