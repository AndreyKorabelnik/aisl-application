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


def test_revision_cli_uses_production_by_default_when_environment_policy_is_supplied(tmp_path, monkeypatch):
    from aisl_s2t import cli

    template = "${$app.schema || '.source'}"
    inputs = RevisionBuildInputs(
        mapping_rows=({
            "mapping_id": "v-env",
            "workflow_target_logical_name": "mart.target",
            "target_column": "id",
            "branch_relation_name": template,
            "driver_relation_name": template,
            "driver_relation_status": "partial",
            "source_relation_role": "driver_path",
            "source_sql_relation_name": template,
            "source_sql_column": "id",
        },),
        mapping_gaps=({
            "gap_id": "g-env",
            "workflow_context_file": "workflow.yml",
            "workflow_target_logical_name": "mart.target",
            "target_column": "id",
            "gap_kind": "source_relation_placeholder_unresolved",
            "mapping_basis": "observed_workflow_placeholder_binding_resolution",
            "evidence": {
                "source_relation_name": template,
                "source_column": "id",
                "placeholder_resolution": [{
                    "placeholder": "app.schema",
                    "candidate_values": ["uat_schema", "prod_schema"],
                }],
            },
        },),
        target_fields=({"target_relation": "mart.target", "target_column": "id"},),
        retrieval={"schema_version": "aisl_s2t_revision_retrieval/v1"},
    )
    monkeypatch.setattr(cli, "load_revision_inputs", lambda **kwargs: inputs)

    policy = tmp_path / "environment-policy.json"
    policy.write_text(json.dumps({
        "default_environment": "production",
        "environment_scopes": {
            "production": ["stands[4]"],
            "uat": ["stands[2]"],
        },
    }), encoding="utf-8")
    observations = tmp_path / "environment-observations.json"
    observations.write_text(json.dumps([
        {"placeholder": "app.schema", "value": "prod_schema", "scope": "stands[4]"},
        {"placeholder": "app.schema", "value": "uat_schema", "scope": "stands[2]"},
    ]), encoding="utf-8")
    output = tmp_path / "s2t.csv"

    assert cli.main([
        "build",
        "--system-id", "system-x",
        "--revision-id", "revision-y",
        "--environment-policy", str(policy),
        "--environment-observations", str(observations),
        "--output", str(output),
    ]) == 0

    with output.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    data = rows[2]
    assert data[header.index("T-src-schema")] == "prod_schema"
    assert data[header.index("T-src")] == "source"

    audit = json.loads((tmp_path / "s2t.audit.json").read_text(encoding="utf-8"))
    assert audit["environment"]["selected_environment"] == "production"
    assert audit["environment"]["selected_scopes"] == ["stands[4]"]
    assert audit["counts"]["typed_gaps_by_type"].get("UNRESOLVED_PLACEHOLDER", 0) == 0


def test_revision_cli_fails_closed_on_incomplete_environment_configuration(tmp_path, monkeypatch):
    from aisl_s2t import cli

    inputs = RevisionBuildInputs(
        mapping_rows=(),
        mapping_gaps=(),
        target_fields=(),
        retrieval={"schema_version": "aisl_s2t_revision_retrieval/v1"},
    )
    monkeypatch.setattr(cli, "load_revision_inputs", lambda **kwargs: inputs)
    policy = tmp_path / "environment-policy.json"
    policy.write_text(json.dumps({
        "environment_scopes": {"production": ["stands[4]"]},
    }), encoding="utf-8")

    assert cli.main([
        "build",
        "--system-id", "system-x",
        "--revision-id", "revision-y",
        "--environment-policy", str(policy),
        "--output", str(tmp_path / "s2t.csv"),
    ]) == 2
