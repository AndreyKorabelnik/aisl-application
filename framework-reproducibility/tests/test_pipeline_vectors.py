"""Offline checks of captured canonical vectors; not a new runtime run."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def fp(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sid(prefix, *parts):
    return prefix + "_" + hashlib.sha256("\x1f".join(str(p or "") for p in parts).encode()).hexdigest()[:24]


class PipelineVectorTests(unittest.TestCase):
    def test_envelope_fingerprints(self):
        for name in ["java", "schema"]:
            e = load(f"learner/examples/{name}.reference.json")
            self.assertEqual(e["content_fingerprint"], fp({k: v for k, v in e.items() if k not in {"content_fingerprint", "artifact_id"}}))
            aid = "java_type_structure_" + e["content_fingerprint"][:24] if name == "java" else sid("schema-declaration-evidence", "sdd-pilot", e["content_fingerprint"])
            self.assertEqual(aid, e["artifact_id"])

    def test_source_snapshots(self):
        for name in ["java", "schema"]:
            e = load(f"learner/examples/{name}.reference.json")
            files = []
            for unit in e["payload"]["source_units"]:
                path = unit["repository_relative_path"]
                raw = (ROOT / "learner/examples" / path).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), unit["content_sha256"])
                self.assertEqual(len(raw), unit["bytes"])
                files.append({"path": path, "sha256": unit["content_sha256"], "bytes": unit["bytes"]})
            snapshot = e["source_snapshot"]
            self.assertEqual(snapshot["fingerprint"], fp({"source_id": "sdd-pilot", "scope": snapshot["scope"], "files": files}))

    def test_java_identity_and_resolution(self):
        e = load("learner/examples/java.reference.json")
        for row in e["payload"]["type_declarations"]:
            self.assertEqual(row["type_id"], sid("java_type", "Sample.java", row["source_ref"]["line_start"], row["simple_name"], row["type_kind"]))
        for row in e["payload"]["field_declarations"]:
            self.assertEqual(row["field_id"], sid("java_field", "Sample.java", row["owner_type_id"], row["name"], row["source_ref"]["line_start"]))
        self.assertEqual(e["coverage"]["coverage_status"], "complete")
        self.assertEqual(e["payload"]["annotation_declarations"][0]["resolution_status"], "unresolved")
        self.assertEqual(e["payload"]["inheritance_declarations"][0]["resolution_status"], "same_package")

    def test_schema_identity_and_gap(self):
        e = load("learner/examples/schema.reference.json")
        for row in e["payload"]["schema_declarations"]:
            self.assertEqual(row["schema_id"], sid("declared_schema", "declared-openapi.json", row["schema_locator"], row["schema_name"]))
        for row in e["payload"]["field_declarations"]:
            self.assertEqual(row["field_id"], sid("schema_field", "declared-openapi.json", row["owner_schema_id"], row["source_ref"]["locator"], row["name"]))
        nickname = next(r for r in e["payload"]["field_declarations"] if r["name"] == "nickname")
        self.assertTrue(nickname["nullable"])
        self.assertFalse(nickname["required"])
        self.assertEqual(e["coverage"]["coverage_status"], "partial")
        self.assertEqual(e["coverage"]["unresolved_schema_reference_count"], 1)

    def test_pipeline_evidence_boundary(self):
        p = load("reviewer/PIPELINE_PROBES.json")
        self.assertEqual(p["status"], "PASS")
        self.assertEqual(p["check_count"], len(p["checks"]))
        self.assertTrue(all(c["status"] == "PASS" for c in p["checks"]))
        self.assertEqual(p["framework_manifest_verified"], 828)
        self.assertIn("KCP high-level planning", p["not_executed"])
        self.assertIn("DeepSeek", p["not_executed"])
        self.assertEqual(p["schema_validation"]["http_responses"], 14)

    def test_api_vectors_and_projection(self):
        responses = load("learner/examples/api-readback.reference.json")["responses"]
        errors = [r["status"] for r in responses if r["status"] != 200]
        self.assertEqual(errors, [422, 400, 404])
        first = responses[0]["body"]
        self.assertEqual(first["page"]["total"], 8)
        self.assertEqual(first, responses[-1]["body"])
        comparison = load("reviewer/oracles/pipeline/join-projection-comparison.json")
        self.assertTrue(comparison["bulk_expression_join"]["expression_links"])
        self.assertTrue(comparison["query_context"]["joins"])
        self.assertTrue(all("expression_links" not in j for j in comparison["query_context"]["joins"]))

    def test_declared_counts_from_api(self):
        responses = load("learner/examples/api-readback.reference.json")["responses"]
        summary = next(r["body"] for r in responses if r["suffix"] == "data-model/declared-summary")
        self.assertEqual(summary["counts"]["type_count"], 6)
        self.assertEqual(summary["counts"]["effective_field_count"], 12)
        self.assertEqual(summary["counts"]["gap_count"], 1)

    def test_publication_revision_results(self):
        base = "reviewer/oracles/pipeline/"
        first = load(base + "publication-result.json")
        duplicate = load(base + "duplicate-publication-result.json")
        second = load(base + "second-publication-result.json")
        self.assertEqual(duplicate["status"], "already_published")
        self.assertEqual(first["revision_id"], duplicate["revision_id"])
        self.assertNotEqual(first["revision_id"], second["revision_id"])


if __name__ == "__main__":
    unittest.main()
