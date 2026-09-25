from __future__ import annotations

import json

from aisl_s2t.revision_source import RevisionBuildInputs


def test_build_cli_requires_only_system_revision_and_output(tmp_path, monkeypatch):
    from aisl_s2t import cli

    inputs = RevisionBuildInputs(
        mapping_rows=({
            "mapping_id": "v1",
            "workflow_target_logical_name": "mart.target",
            "target_column": "id",
            "branch_relation_name": "src.base",
            "driver_relation_name": "src.base",
            "driver_relation_status": "resolved",
            "source_relation_role": "driver_path",
            "source_sql_relation_name": "src.base",
            "source_sql_column": "id",
        },),
        mapping_gaps=(),
        target_fields=({"target_relation": "mart.target", "target_column": "id"},),
        retrieval={"schema_version": "aisl_s2t_revision_retrieval/v1"},
    )
    monkeypatch.setattr(cli, "load_revision_inputs", lambda **kwargs: inputs)
    output = tmp_path / "s2t.csv"

    assert cli.main([
        "build",
        "--system-id", "system-x",
        "--revision-id", "revision-y",
        "--output", str(output),
    ]) == 0

    audit_path = tmp_path / "s2t.audit.json"
    assert output.exists()
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["system_id"] == "system-x"
    assert audit["revision_id"] == "revision-y"
    assert audit["retrieval"]["schema_version"] == "aisl_s2t_revision_retrieval/v1"
