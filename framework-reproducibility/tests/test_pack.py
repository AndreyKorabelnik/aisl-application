import unittest

from tools.validate_pack import resolve_local_refs, validate


class PackTests(unittest.TestCase):
    def test_current_pack(self):
        result = validate()
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["scored_readiness"])

    def test_broken_ref_fails(self):
        with self.assertRaises(KeyError):
            resolve_local_refs({"$ref": "#/$defs/missing"})

    def test_external_ref_fails(self):
        with self.assertRaises(ValueError):
            resolve_local_refs({"$ref": "https://example.com/schema"})

    def test_escaped_ref(self):
        self.assertEqual(resolve_local_refs({"$defs": {"a/b": {}}, "$ref": "#/$defs/a~1b"}), 1)


if __name__ == "__main__":
    unittest.main()
