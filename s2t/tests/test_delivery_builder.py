from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "build-aisl-s2t-delivery.py"


def load_builder_module():
    spec = importlib.util.spec_from_file_location("build_aisl_s2t_delivery", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_delivery_builder_surface() -> None:
    assert BUILDER.is_file()
    text = BUILDER.read_text(encoding="utf-8")
    assert "FIRST_PARTY_COMPONENTS" in text
    assert "third_party_policy" in text
    assert "--no-deps" in text
    assert "--no-build-isolation" in text


def test_clean_delivery_boundary_contains_only_s2t() -> None:
    builder = load_builder_module()
    assert builder.FIRST_PARTY_COMPONENTS == ("aisl-s2t",)
    assert "sqlglot" not in builder.FIRST_PARTY_COMPONENTS
    assert "duckdb" not in builder.FIRST_PARTY_COMPONENTS
    assert "tree-sitter" not in builder.FIRST_PARTY_COMPONENTS


def test_delivery_name_is_bound_to_version_and_source_commit() -> None:
    builder = load_builder_module()
    assert (
        builder.delivery_zip_name("0.1.0a5", "eb6eb407e168d24b09b4fa76b23c7baea09f3af2")
        == "aisl-s2t-clean-0.1.0a5-eb6eb407.zip"
    )
