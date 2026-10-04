from __future__ import annotations

from pathlib import Path

from aisl_data_model_datamart_lineage import cli


def test_cli_writes_csv(monkeypatch, tmp_path: Path):
    class Gateway:
        def __init__(self, base_url):
            assert base_url == "http://aisl"
        def close(self):
            pass

    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "build_lineage", lambda **kwargs: [{"status": "confirmed"}])
    output = tmp_path / "out.csv"
    rc = cli.main([
        "build",
        "--aisl-base-url", "http://aisl",
        "--source-system", "ucp",
        "--source-revision", "rev-a",
        "--bridge-system", "tsa",
        "--bridge-revision", "rev-b",
        "--target-system", "profile",
        "--target-revision", "rev-c",
        "--source-object", "BirthDate",
        "--source-field", "value",
        "--output", str(output),
    ])
    assert rc == 0
    assert output.exists()


def test_cli_without_source_field_builds_all_declared_fields(monkeypatch, tmp_path: Path):
    class Gateway:
        def __init__(self, base_url):
            pass
        def close(self):
            pass

    monkeypatch.setattr(cli, "KnowledgeApiGateway", Gateway)
    monkeypatch.setattr(cli, "list_source_fields", lambda **kwargs: ["a", "b"])
    seen = []
    def _build(**kwargs):
        seen.append(kwargs["source_field"])
        return [{"source_field": kwargs["source_field"], "status": "confirmed"}]
    monkeypatch.setattr(cli, "build_lineage", _build)
    output = tmp_path / "all.csv"
    rc = cli.main([
        "build",
        "--source-system", "ucp", "--source-revision", "rev-a",
        "--bridge-system", "tsa", "--bridge-revision", "rev-b",
        "--target-system", "profile", "--target-revision", "rev-c",
        "--source-object", "com.example.X",
        "--output", str(output),
    ])
    assert rc == 0
    assert seen == ["a", "b"]
