import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ContractVectorTests(unittest.TestCase):
    def test_publication_fingerprints(self):
        fixture = json.loads((ROOT / "learner/examples/publication.reference.json").read_text())
        descriptor = fixture["descriptor"]
        manifest = fixture["bundle_manifest"]
        for value, key in [(descriptor, "publication_fingerprint"), (manifest, "bundle_fingerprint"),
                           *[(p, "content_fingerprint") for p in descriptor["products"]]]:
            self.assertEqual(value[key], fingerprint({k: v for k, v in value.items() if k != key}))

    def test_publication_payload_hash(self):
        fixture = json.loads((ROOT / "learner/examples/publication.reference.json").read_text())
        payload = fixture["artifact_bytes_utf8"].encode()
        artifact = fixture["descriptor"]["products"][0]["physical_artifacts"][0]
        self.assertEqual(artifact["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(artifact["byte_size"], len(payload))

    def test_join_ids(self):
        fixture = json.loads((ROOT / "learner/examples/sql-joins.reference.json").read_text())
        self.assertEqual(len(fixture["joins"]), 8)
        for row in fixture["joins"]:
            material = "|".join([row["query_id"], row["scope_id"], str(row["join_ordinal"]),
                                 row["right_relation_id"] or "", row["predicate"] or "", ",".join(row["using_columns"])])
            expected = "sql_join_edge_" + row["repo_id"] + "_" + hashlib.sha256(material.encode()).hexdigest()[:16]
            self.assertEqual(row["sql_join_edge_id"], expected)

    def test_oracle_boundary(self):
        report = json.loads((ROOT / "reviewer/CONTRACT_PROBES.json").read_text())
        self.assertEqual(report["pipeline_acceptance"], "NOT_RUN")
        self.assertEqual(len(report["checks"]), 16)
        self.assertTrue(all(c["status"] == "PASS" for c in report["checks"]))
        inputs = json.loads((ROOT / "reviewer/oracles/core-sql/inputs.json").read_text())
        self.assertEqual(set(inputs), {"sql-cases.sql"})
        self.assertEqual(inputs["sql-cases.sql"], (ROOT / "learner/examples/sql-cases.sql").read_text())


if __name__ == "__main__":
    unittest.main()
