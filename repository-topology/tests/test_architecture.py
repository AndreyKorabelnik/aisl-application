from pathlib import Path


def test_no_parser_or_framework_dependencies():
    root = Path(__file__).resolve().parents[1] / "repository_topology"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    forbidden = (
        "tree_sitter", "sqlglot", "repository_inventory.", "code_analyzer_core", "static_analysis_runner",
        "knowledge_layer_core", "knowledge_control_plane", "knowledge_api", "prepared_knowledge_runtime",
    )
    for token in forbidden:
        assert token not in text
