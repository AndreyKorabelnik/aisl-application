import unittest

from benchmark.compare import compare, loads


class ComparatorTests(unittest.TestCase):
    def test_object_order(self):
        self.assertTrue(compare({"a": 1, "b": 2}, {"b": 2, "a": 1})["equal"])

    def test_array_order(self):
        self.assertFalse(compare([1, 2], [2, 1])["equal"])

    def test_explicit_multiset(self):
        self.assertTrue(compare({"a": [1, 2]}, {"a": [2, 1]}, ["/a"])["equal"])

    def test_duplicates_preserved(self):
        self.assertFalse(compare([1, 1, 2], [1, 2, 2], [""])["equal"])

    def test_bool_is_not_int(self):
        self.assertFalse(compare(True, 1)["equal"])

    def test_float_is_not_int(self):
        self.assertFalse(compare(1.0, 1)["equal"])

    def test_missing_is_not_null(self):
        self.assertFalse(compare({"a": None}, {})["equal"])

    def test_extra_field_is_difference(self):
        self.assertFalse(compare({}, {"a": 1})["equal"])

    def test_ids_and_confidence_preserved(self):
        result = compare({"id": "a", "confidence": "unresolved"}, {"id": "b", "confidence": "confirmed"})
        self.assertEqual(len(result["differences"]), 2)

    def test_pointer_escape(self):
        result = compare({"a/b~c": [1, 2]}, {"a/b~c": [2, 1]}, ["/a~1b~0c"])
        self.assertTrue(result["equal"])

    def test_policy_typo_fails(self):
        with self.assertRaises(ValueError):
            compare({"a": []}, {"a": []}, ["/b"])

    def test_policy_requires_arrays(self):
        with self.assertRaises(ValueError):
            compare({"a": 1}, {"a": 1}, ["/a"])

    def test_nested_policy_fails(self):
        with self.assertRaises(ValueError):
            compare([[1]], [[1]], ["", "/0"])

    def test_nonfinite_fails(self):
        with self.assertRaises(ValueError):
            compare(float("nan"), float("nan"))

    def test_json_nonfinite_fails(self):
        with self.assertRaises(ValueError):
            loads('{"a": NaN}')

    def test_json_duplicate_keys_fail(self):
        with self.assertRaises(ValueError):
            loads('{"a": 1, "a": 2}')

    def test_same_scope(self):
        value = {"scope": {"system_id": "s1", "revision_id": "r1"}}
        self.assertTrue(compare(value, value)["equal"])

    def test_revision_mismatch(self):
        self.assertFalse(compare({"revision_id": "r1"}, {"revision_id": "r2"})["equal"])


if __name__ == "__main__":
    unittest.main()
