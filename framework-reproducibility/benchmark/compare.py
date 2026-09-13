"""Strict JSON comparison; not an AISL semantic normalizer.

Only explicitly approved exact JSON Pointers may denote unordered arrays.
No field deletion, numeric tolerance or ID rewriting is implemented.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _bad_constant(value):
    raise ValueError(f"non-JSON numeric constant: {value}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(value):
    return json.loads(value, parse_constant=_bad_constant, object_pairs_hook=_object)


def _escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _walk(value, pointer=""):
    yield pointer, value
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON keys must be strings")
            yield from _walk(child, pointer + "/" + _escape(key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _walk(child, pointer + "/" + str(i))
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError(f"not a JSON value: {type(value).__name__}")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite number")


def _canonical(value, pointer, unordered):
    # Type tags intentionally distinguish true/1 and integer/float.
    if isinstance(value, dict):
        return ("object", tuple((key, _canonical(child, pointer + "/" + _escape(key), unordered))
                                for key, child in sorted(value.items())))
    if isinstance(value, list):
        children = [_canonical(child, pointer + "/" + str(i), unordered) for i, child in enumerate(value)]
        if pointer in unordered:
            children.sort(key=repr)
        return ("array", tuple(children))
    return (type(value).__name__, value)


def compare(expected, actual, unordered_paths=()):
    unordered = frozenset(unordered_paths)
    maps = [dict(_walk(value)) for value in (expected, actual)]
    for pointer in unordered:
        if not isinstance(pointer, str) or any(pointer not in m or not isinstance(m[pointer], list) for m in maps):
            raise ValueError(f"unordered pointer must identify an array in both inputs: {pointer!r}")
        # Index-addressed policies below a reordered collection are unstable.
        if any(other != pointer and other.startswith(pointer + "/") for other in unordered):
            raise ValueError("nested unordered policies are unsupported")
    differences = []

    def visit(a, b, pointer):
        if type(a) is not type(b):
            differences.append({"path": pointer, "reason": "type", "expected": type(a).__name__, "actual": type(b).__name__})
        elif isinstance(a, dict):
            for key in sorted(a.keys() | b.keys()):
                child = pointer + "/" + _escape(key)
                if key not in a or key not in b:
                    differences.append({"path": child, "reason": "unexpected_field" if key not in a else "missing_field"})
                else:
                    visit(a[key], b[key], child)
        elif isinstance(a, list):
            if pointer in unordered:
                if _canonical(a, pointer, unordered) != _canonical(b, pointer, unordered):
                    differences.append({"path": pointer, "reason": "multiset"})
            else:
                if len(a) != len(b):
                    differences.append({"path": pointer, "reason": "array_length", "expected": len(a), "actual": len(b)})
                for i, (left, right) in enumerate(zip(a, b)):
                    visit(left, right, pointer + "/" + str(i))
        elif a != b:
            differences.append({"path": pointer, "reason": "value", "expected": a, "actual": b})

    visit(expected, actual, "")
    return {"equal": not differences, "differences": differences, "policy": {"unordered_paths": sorted(unordered)}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--unordered", action="append", default=[])
    args = parser.parse_args()
    result = compare(loads(args.expected.read_text()), loads(args.actual.read_text()), args.unordered)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["equal"] else 1)
