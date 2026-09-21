from aisl_s2t.primary_source import collapse_primary_sources


def _env(template="${$src.schema}.${$src.table}", resolved="prod.source"):
    return [{
        "semantic_key": ["dm.target", "id", template, "id"],
        "status": "resolved",
        "resolved_source_relation": resolved,
    }]


def test_branch_relation_wins_over_downstream_terminal_without_name_heuristics():
    rows = [
        {
            "mapping_id": "upstream",
            "workflow_context_file": "root.yml",
            "workflow_target_logical_name": "dm.target",
            "target_column": "id",
            "branch_relation_name": "${$src.schema}.${$src.table}",
            "source_relation_role": "driver_path",
            "source_sql_relation_name": "${$src.schema}.${$src.table}",
            "source_sql_column": "id",
            "source_sql_file": "source.sql",
        },
        {
            "mapping_id": "downstream",
            "workflow_context_file": "other.json",
            "workflow_target_logical_name": "dm.target",
            "target_column": "id",
            "branch_relation_name": "${$src.schema}.${$src.table}",
            "source_relation_role": "driver_path",
            "source_sql_relation_name": "dm.some_other_relation",
            "source_sql_column": "id",
            "source_sql_file": "arbitrary.sql",
        },
    ]
    decisions = collapse_primary_sources(rows, environment_resolutions=_env())
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.status == "resolved"
    assert decision.source_relation == "prod.source"
    assert decision.basis == "mechanically_observed_branch_primary_source"
    assert decision.mapping_ids == ("downstream", "upstream")
    assert decision.terminal_relations == ("${$src.schema}.${$src.table}", "dm.some_other_relation")


def test_distinct_resolved_branches_are_preserved_as_multiple_value_sources():
    rows = [
        {
            "mapping_id": "a", "workflow_target_logical_name": "dm.target", "target_column": "id",
            "branch_relation_name": "src.a", "source_relation_role": "driver_path",
            "source_sql_relation_name": "src.a", "source_sql_column": "id",
        },
        {
            "mapping_id": "b", "workflow_target_logical_name": "dm.target", "target_column": "id",
            "branch_relation_name": "src.b", "source_relation_role": "driver_path",
            "source_sql_relation_name": "src.b", "source_sql_column": "id",
        },
    ]
    decisions = collapse_primary_sources(rows, environment_resolutions=[])
    assert [(item.status, item.source_relation) for item in decisions] == [
        ("resolved", "src.a"), ("resolved", "src.b")
    ]


def test_unresolved_branch_does_not_promote_concrete_downstream_terminal():
    rows = [{
        "mapping_id": "m", "workflow_target_logical_name": "dm.target", "target_column": "id",
        "branch_relation_name": "${$src.schema}.${$src.table}", "source_relation_role": "driver_path",
        "source_sql_relation_name": "dm.downstream", "source_sql_column": "id",
    }]
    decisions = collapse_primary_sources(rows, environment_resolutions=[])
    assert len(decisions) == 1
    assert decisions[0].status == "unresolved"
    assert decisions[0].source_relation is None


def test_current_unresolved_driver_does_not_fallback_to_terminal_relation():
    rows = [{
        "mapping_id": "m", "workflow_target_logical_name": "dm.target", "target_column": "id",
        "branch_relation_name": "", "driver_relation_status": "unresolved", "driver_relation_name": "",
        "source_relation_role": "driver_path", "source_sql_relation_name": "src.only", "source_sql_column": "id",
    }]
    decisions = collapse_primary_sources(rows, environment_resolutions=[])
    assert len(decisions) == 1
    assert decisions[0].status == "unresolved"
    assert decisions[0].source_relation is None
    assert decisions[0].basis == "unresolved_primary_source_template"


def test_non_primary_relation_roles_are_not_folded_into_driver_sources():
    rows = [{
        "mapping_id": "lookup", "workflow_target_logical_name": "dm.target", "target_column": "name",
        "branch_relation_name": "dict.names", "source_relation_role": "lookup",
        "source_sql_relation_name": "dict.names", "source_sql_column": "name",
    }]
    assert collapse_primary_sources(rows, environment_resolutions=[]) == []


def test_two_syntactic_templates_that_resolve_to_same_relation_are_deduplicated():
    rows = [
        {
            "mapping_id": "a", "workflow_target_logical_name": "dm.target", "target_column": "id",
            "branch_relation_name": "${$src.schema}.${$src.table}", "source_relation_role": "driver_path",
            "source_sql_relation_name": "x", "source_sql_column": "id",
        },
        {
            "mapping_id": "b", "workflow_target_logical_name": "dm.target", "target_column": "id",
            "branch_relation_name": "${$src.schema}.source", "source_relation_role": "driver_path",
            "source_sql_relation_name": "y", "source_sql_column": "id",
        },
    ]
    env = [
        {"semantic_key": ["dm.target", "id", "${$src.schema}.${$src.table}", "id"], "status": "resolved", "resolved_source_relation": "prod.source"},
        {"semantic_key": ["dm.target", "id", "${$src.schema}.source", "id"], "status": "resolved", "resolved_source_relation": "prod.source"},
    ]
    decisions = collapse_primary_sources(rows, environment_resolutions=env)
    assert len(decisions) == 1
    assert decisions[0].source_relation == "prod.source"
    assert decisions[0].primary_templates == ("${$src.schema}.${$src.table}", "${$src.schema}.source")


def test_primary_source_cli(tmp_path):
    import json
    from aisl_s2t.cli import main

    mappings = [{
        "mapping_id": "m", "workflow_target_logical_name": "dm.target", "target_column": "id",
        "branch_relation_name": "src.source", "source_relation_role": "driver_path",
        "source_sql_relation_name": "dm.downstream", "source_sql_column": "id",
    }]
    env = {"semantic_decisions": []}
    mappings_path = tmp_path / "mappings.json"
    env_path = tmp_path / "env.json"
    output_path = tmp_path / "out.json"
    mappings_path.write_text(json.dumps(mappings), encoding="utf-8")
    env_path.write_text(json.dumps(env), encoding="utf-8")

    assert main([
        "collapse-primary-sources",
        "--mappings", str(mappings_path),
        "--environment-resolution", str(env_path),
        "--output", str(output_path),
    ]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "aisl_s2t_primary_source_resolution/v1"
    assert payload["counts"]["resolved_primary_source_decisions"] == 1
    assert payload["decisions"][0]["source_relation"] == "src.source"


def test_input_order_does_not_change_semantic_primary_source_decisions():
    rows = [
        {
            "mapping_id": "a", "workflow_context_file": "x", "workflow_target_logical_name": "dm.target", "target_column": "id",
            "branch_relation_name": "src.primary", "source_relation_role": "driver_path",
            "source_sql_relation_name": "mid.one", "source_sql_column": "id", "source_sql_file": "q1.sql",
        },
        {
            "mapping_id": "b", "workflow_context_file": "y", "workflow_target_logical_name": "dm.target", "target_column": "id",
            "branch_relation_name": "src.primary", "source_relation_role": "driver_path",
            "source_sql_relation_name": "mid.two", "source_sql_column": "id", "source_sql_file": "q2.sql",
        },
    ]
    forward = collapse_primary_sources(rows, environment_resolutions=[])
    reverse = collapse_primary_sources(list(reversed(rows)), environment_resolutions=[])
    assert [item.to_dict() for item in forward] == [item.to_dict() for item in reverse]


def test_file_and_workflow_names_do_not_drive_primary_source_selection():
    base = {
        "mapping_id": "m", "workflow_target_logical_name": "dm.target", "target_column": "id",
        "branch_relation_name": "src.primary", "source_relation_role": "driver_path",
        "source_sql_relation_name": "mid.terminal", "source_sql_column": "id",
    }
    a = collapse_primary_sources([
        {**base, "workflow_context_file": "alpha.conf", "source_sql_file": "one.sql"}
    ], environment_resolutions=[])[0]
    b = collapse_primary_sources([
        {**base, "workflow_context_file": "completely-renamed.yaml", "source_sql_file": "arbitrary.q"}
    ], environment_resolutions=[])[0]
    assert (a.status, a.source_relation, a.basis) == (b.status, b.source_relation, b.basis)
    assert a.source_relation == "src.primary"


def test_driver_and_lookup_contributions_are_not_collapsed_into_one_primary_source():
    rows = [
        {
            "mapping_id": "driver", "workflow_target_logical_name": "dm.target", "target_column": "label",
            "branch_relation_name": "src.customer", "source_relation_role": "driver_path",
            "source_sql_relation_name": "src.customer", "source_sql_column": "status_cd",
        },
        {
            "mapping_id": "lookup", "workflow_target_logical_name": "dm.target", "target_column": "label",
            "branch_relation_name": "dict.status", "source_relation_role": "enrichment",
            "source_sql_relation_name": "dict.status", "source_sql_column": "name",
        },
    ]
    decisions = collapse_primary_sources(rows, environment_resolutions=[])
    assert len(decisions) == 1
    assert decisions[0].source_relation == "src.customer"
    assert decisions[0].source_relation_role == "driver_path"


def test_driver_candidate_without_proven_driver_path_is_not_promoted():
    rows = [{
        "mapping_id": "candidate", "workflow_target_logical_name": "dm.target", "target_column": "id",
        "branch_relation_name": "src.possible", "source_relation_role": "driver_candidate",
        "source_sql_relation_name": "src.possible", "source_sql_column": "id",
    }]
    assert collapse_primary_sources(rows, environment_resolutions=[]) == []


def test_ambiguous_environment_resolution_keeps_branch_unresolved():
    rows = [{
        "mapping_id": "m", "workflow_target_logical_name": "dm.target", "target_column": "id",
        "branch_relation_name": "${$src.schema}.source", "source_relation_role": "driver_path",
        "source_sql_relation_name": "mid.terminal", "source_sql_column": "id",
    }]
    env = [{
        "semantic_key": ["dm.target", "id", "${$src.schema}.source", "id"],
        "status": "ambiguous",
        "resolved_source_relation": None,
    }]
    decision = collapse_primary_sources(rows, environment_resolutions=env)[0]
    assert decision.status == "unresolved"
    assert decision.source_relation is None

def test_current_driver_relation_wins_over_observed_branch_structure():
    rows = [{
        "mapping_id": "m", "workflow_target_logical_name": "mart.target", "target_column": "id",
        "source_relation_role": "driver_path", "branch_relation_name": "stage.branch",
        "driver_relation_status": "resolved", "driver_relation_name": "source.real",
        "source_sql_relation_name": "source.real", "source_sql_column": "id",
    }]
    decision = collapse_primary_sources(rows, environment_resolutions=[])[0]
    assert decision.status == "resolved"
    assert decision.source_relation == "source.real"
    assert decision.basis == "mechanically_observed_driver_primary_source"


def test_partial_current_driver_template_is_preserved_as_literal():
    rows = [{
        "mapping_id": "m", "workflow_target_logical_name": "mart.target", "target_column": "id",
        "source_relation_role": "driver_path", "branch_relation_name": "stage.branch",
        "driver_relation_status": "partial", "driver_relation_name": "${$opaque.scope}.real",
        "source_sql_relation_name": "${$opaque.scope}.real", "source_sql_column": "id",
    }]
    decision = collapse_primary_sources(rows, environment_resolutions=[])[0]
    assert decision.status == "template"
    assert decision.source_relation == "${$opaque.scope}.real"
    assert decision.basis == "mechanically_observed_driver_primary_source_template"


def test_ambiguous_current_driver_does_not_promote_branch_structure():
    rows = [{
        "mapping_id": "m", "workflow_target_logical_name": "mart.target", "target_column": "id",
        "source_relation_role": "driver_path", "branch_relation_name": "stage.branch",
        "driver_relation_status": "ambiguous", "driver_relation_name": "",
        "source_sql_relation_name": "source.a", "source_sql_column": "id",
    }]
    decision = collapse_primary_sources(rows, environment_resolutions=[])[0]
    assert decision.status == "unresolved"
    assert decision.source_relation is None


def test_current_driver_selection_is_input_order_invariant():
    rows = [
        {
            "mapping_id": "a", "workflow_target_logical_name": "mart.target", "target_column": "id",
            "source_relation_role": "driver_path", "branch_relation_name": "stage.a",
            "driver_relation_status": "resolved", "driver_relation_name": "source.real",
            "source_sql_relation_name": "source.real", "source_sql_column": "id",
        },
        {
            "mapping_id": "b", "workflow_target_logical_name": "mart.target", "target_column": "id",
            "source_relation_role": "driver_path", "branch_relation_name": "stage.b",
            "driver_relation_status": "resolved", "driver_relation_name": "source.real",
            "source_sql_relation_name": "source.real", "source_sql_column": "id",
        },
    ]
    forward = collapse_primary_sources(rows, environment_resolutions=[])
    reverse = collapse_primary_sources(list(reversed(rows)), environment_resolutions=[])
    assert [item.to_dict() for item in forward] == [item.to_dict() for item in reverse]
