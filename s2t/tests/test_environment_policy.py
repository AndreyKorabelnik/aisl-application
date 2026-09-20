from aisl_s2t.environment import (
    EnvironmentEvidenceIndex,
    EnvironmentPolicy,
    collapse_semantic_decisions,
    resolve_environment_gap,
    resolve_placeholder,
)


def _policy(explicit=None):
    return EnvironmentPolicy(
        environment_scopes={"production": ["stands[4]"], "uat": ["stands[2]"]},
        default_environment="production",
        explicit_environment=explicit,
    )


def _index():
    return EnvironmentEvidenceIndex.from_observations([
        {"placeholder": "app.schema", "value": "prod_schema", "scope": "stands[4]"},
        {"placeholder": "app.schema", "value": "uat_schema", "scope": "stands[2]"},
        {"placeholder": "app.prefix", "value": "prod_", "scope": "stands[4]"},
        {"placeholder": "app.prefix", "value": "uat_", "scope": "stands[2]"},
    ])


def test_default_environment_is_production():
    item = {"placeholder": "app.schema", "candidate_values": ["uat_schema", "prod_schema"]}
    decision = resolve_placeholder(item, index=_index(), policy=_policy())
    assert decision.status == "resolved"
    assert decision.value == "prod_schema"
    assert decision.basis == "default_environment:production"


def test_explicit_environment_overrides_default():
    item = {"placeholder": "app.schema", "candidate_values": ["uat_schema", "prod_schema"]}
    decision = resolve_placeholder(item, index=_index(), policy=_policy("uat"))
    assert decision.value == "uat_schema"
    assert decision.basis == "explicit_environment:uat"


def test_unique_literal_does_not_require_environment_classification():
    item = {"placeholder": "app.table", "candidate_values": ["loan_agrmnt"]}
    decision = resolve_placeholder(item, index=_index(), policy=_policy())
    assert decision.value == "loan_agrmnt"
    assert decision.basis == "unique_concrete_candidate"


def test_template_candidates_are_not_treated_as_concrete_values():
    item = {"placeholder": "app.schema", "candidate_values": ["{{schema}}", "prod_schema"]}
    decision = resolve_placeholder(item, index=_index(), policy=_policy())
    assert decision.value == "prod_schema"


def test_multiple_candidates_for_selected_environment_stay_ambiguous():
    index = _index()
    index.add(placeholder="app.schema", value="prod_schema_2", scope="stands[4]")
    item = {"placeholder": "app.schema", "candidate_values": ["prod_schema", "prod_schema_2"]}
    decision = resolve_placeholder(item, index=index, policy=_policy())
    assert decision.status == "ambiguous"
    assert decision.value is None


def test_no_candidate_for_selected_environment_stays_unresolved():
    item = {"placeholder": "app.schema", "candidate_values": ["unknown_a", "unknown_b"]}
    decision = resolve_placeholder(item, index=_index(), policy=_policy())
    assert decision.status == "unresolved"
    assert decision.value is None


def test_gap_resolves_all_placeholders_without_template_execution():
    gap = {
        "gap_id": "g1",
        "workflow_context_file": "workflow.yml",
        "workflow_target_logical_name": "dm.target",
        "target_column": "id",
        "evidence": {
            "source_relation_name": "${$app.schema}.${$app.prefix}table",
            "source_column": "id",
            "placeholder_resolution": [
                {"placeholder": "app.schema", "candidate_values": ["uat_schema", "prod_schema"]},
                {"placeholder": "app.prefix", "candidate_values": ["uat_", "prod_"]},
            ],
        },
    }
    decision = resolve_environment_gap(gap, index=_index(), policy=_policy())
    assert decision.status == "resolved"
    assert decision.resolved_source_relation == "prod_schema.prod_table"


def test_non_environment_multi_value_placeholder_remains_unresolved():
    gap = {
        "gap_id": "g1",
        "workflow_context_file": "workflow.yml",
        "workflow_target_logical_name": "dm.target",
        "target_column": "id",
        "evidence": {
            "source_relation_name": "dm.${$s2t.target.table.name}",
            "source_column": "id",
            "placeholder_resolution": [{
                "placeholder": "s2t.target.table.name",
                "candidate_values": ["table_a", "table_b"],
            }],
        },
    }
    decision = resolve_environment_gap(gap, index=_index(), policy=_policy())
    assert decision.status == "unresolved"


def test_semantic_dedupe_accepts_one_consistent_resolved_identity_with_unresolved_siblings():
    base = {
        "workflow_target_logical_name": "dm.target",
        "target_column": "id",
        "evidence": {
            "source_relation_name": "${$app.schema}.source",
            "source_column": "id",
            "placeholder_resolution": [{"placeholder": "app.schema", "candidate_values": ["uat_schema", "prod_schema"]}],
        },
    }
    resolved = resolve_environment_gap(
        {**base, "gap_id": "g1", "workflow_context_file": "root.yml"}, index=_index(), policy=_policy()
    )
    unresolved = resolve_environment_gap(
        {
            **base,
            "gap_id": "g2",
            "workflow_context_file": "devops.json",
            "evidence": {
                **base["evidence"],
                "placeholder_resolution": [{"placeholder": "app.schema", "candidate_values": ["x", "y"]}],
            },
        },
        index=_index(),
        policy=_policy(),
    )
    groups = collapse_semantic_decisions([resolved, unresolved])
    assert groups == [{
        "semantic_key": ["dm.target", "id", "${$app.schema}.source", "id"],
        "status": "resolved",
        "resolved_source_relation": "prod_schema.source",
        "basis": "consistent_resolved_workflow_contexts",
        "gap_ids": ["g1", "g2"],
        "workflow_context_files": ["devops.json", "root.yml"],
    }]


def test_semantic_dedupe_keeps_conflicting_resolved_contexts_ambiguous():
    base = {
        "workflow_target_logical_name": "dm.target",
        "target_column": "id",
        "evidence": {
            "source_relation_name": "${$app.schema}.source",
            "source_column": "id",
            "placeholder_resolution": [{"placeholder": "app.schema", "candidate_values": ["uat_schema", "prod_schema"]}],
        },
    }
    a = resolve_environment_gap({**base, "gap_id": "g1", "workflow_context_file": "a"}, index=_index(), policy=_policy())
    b = resolve_environment_gap({**base, "gap_id": "g2", "workflow_context_file": "b"}, index=_index(), policy=_policy("uat"))
    group = collapse_semantic_decisions([a, b])[0]
    assert group["status"] == "ambiguous"
    assert group["resolved_source_relation"] is None


def test_structured_placeholder_rows_build_environment_index_without_name_heuristics():
    index = EnvironmentEvidenceIndex.from_placeholder_resolution_rows([
        {
            "placeholder": "app.schema",
            "resolved_value": "prod_schema",
            "resolution_status": "resolved",
            "evidence": [{
                "evidence_kind": "sql_environment_scope_observation",
                "selected_scope": "stands[4]",
            }],
        }
    ])
    assert index.scopes_for("app.schema", "prod_schema") == frozenset({"stands[4]"})


def test_environment_scope_identity_is_opaque_and_not_tied_to_stands_array_shape():
    index = EnvironmentEvidenceIndex.from_observations([
        {"placeholder": "app.schema", "value": "prod_schema", "scope": "config:production-profile"},
        {"placeholder": "app.schema", "value": "uat_schema", "scope": "config:uat-profile"},
    ])
    policy = EnvironmentPolicy(
        environment_scopes={
            "production": ["config:production-profile"],
            "uat": ["config:uat-profile"],
        }
    )
    decision = resolve_placeholder(
        {"placeholder": "app.schema", "candidate_values": ["uat_schema", "prod_schema"]},
        index=index,
        policy=policy,
    )
    assert decision.status == "resolved"
    assert decision.value == "prod_schema"
    assert decision.basis == "default_environment:production"
