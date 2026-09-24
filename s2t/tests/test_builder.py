import csv
import io

from aisl_s2t.builder import S2T_COLUMNS, build_deterministic_s2t, render_s2t_csv
from aisl_s2t.gaps import (
    BOUNDED_PRODUCER_AMBIGUITY,
    CONSUMER_CONVENTION,
    INSUFFICIENT_EVIDENCE,
    UNRESOLVED_PLACEHOLDER,
)


def _idx(name):
    return S2T_COLUMNS.index(name)


def _driver(mapping_id="m", target="mart.target", column="id", branch="src.base", source_column="id", **extra):
    row = {
        "mapping_id": mapping_id,
        "workflow_context_file": "opaque/workflow-a",
        "workflow_target_logical_name": target,
        "target_column": column,
        "branch_relation_name": branch,
        "source_relation_role": "driver_path",
        "source_sql_relation_name": "stage.terminal",
        "source_sql_column": source_column,
        "source_sql_file": "opaque/query-a",
    }
    row.update(extra)
    return row


def test_builder_emits_resolved_primary_source_and_26_column_row():
    result = build_deterministic_s2t([_driver()])
    assert len(result.rows) == 1
    row = result.rows[0]
    assert len(row) == 26
    assert row[_idx("T-trg-schema")] == "mart"
    assert row[_idx("T-trg")] == "target"
    assert row[_idx("T-trg-f")] == "id"
    assert row[_idx("T-src-schema")] == "src"
    assert row[_idx("T-src")] == "base"
    assert row[_idx("T-src-f-name")] == "id"
    assert result.gaps == ()


def test_builder_preserves_multiple_real_primary_branches_as_separate_rows():
    result = build_deterministic_s2t([
        _driver("a", branch="src.alpha"),
        _driver("b", branch="src.beta"),
    ])
    assert [(row[_idx("T-src-schema")], row[_idx("T-src")]) for row in result.rows] == [
        ("src", "alpha"), ("src", "beta")
    ]
    assert result.gaps == ()


def test_enrichment_does_not_replace_proven_primary_source():
    mappings = [
        _driver("driver", column="label", branch="source.customer", source_column="status_cd"),
        {
            "mapping_id": "enrichment", "workflow_target_logical_name": "mart.target", "target_column": "label",
            "branch_relation_name": "dictionary.codes", "source_relation_role": "enrichment",
            "source_sql_relation_name": "dictionary.codes", "source_sql_column": "description",
        },
    ]
    result = build_deterministic_s2t(mappings)
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row[_idx("T-src-schema")] == "source"
    assert row[_idx("T-src")] == "customer"
    assert row[_idx("T-src-f-name")] == "status_cd"
    assert all(gap.gap_type != CONSUMER_CONVENTION for gap in result.gaps)


def test_lookup_only_stays_target_only_and_is_typed_as_consumer_convention():
    mappings = [{
        "mapping_id": "lookup", "workflow_target_logical_name": "mart.target", "target_column": "label",
        "branch_relation_name": "dictionary.codes", "source_relation_role": "enrichment",
        "source_sql_relation_name": "dictionary.codes", "source_sql_column": "description",
    }]
    result = build_deterministic_s2t(mappings)
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row[_idx("T-src-schema")] == row[_idx("T-src")] == row[_idx("T-src-f-name")] == ""
    assert [(gap.gap_type, gap.basis) for gap in result.gaps] == [
        (CONSUMER_CONVENTION, "lookup_or_enrichment_observed_without_proven_primary_source")
    ]


def test_driver_candidate_is_not_promoted_and_stays_insufficient():
    mappings = [{
        "mapping_id": "candidate", "workflow_target_logical_name": "mart.target", "target_column": "id",
        "branch_relation_name": "src.possible", "source_relation_role": "driver_candidate",
        "source_sql_relation_name": "src.possible", "source_sql_column": "id",
    }]
    result = build_deterministic_s2t(mappings)
    assert result.rows[0][_idx("T-src")] == ""
    assert any(gap.gap_type == INSUFFICIENT_EVIDENCE for gap in result.gaps)


def test_unresolved_upstream_template_is_not_replaced_by_downstream_terminal():
    mappings = [_driver(branch="${$scope.schema}.source")]
    result = build_deterministic_s2t(mappings)
    assert result.rows[0][_idx("T-src")] == ""
    assert any(gap.gap_type == UNRESOLVED_PLACEHOLDER for gap in result.gaps)


def test_public_two_candidate_producer_ambiguity_is_typed_without_ranking_or_promotion():
    gaps = [{
        "gap_id": "public-gap-1",
        "workflow_target_logical_name": "mart.target",
        "target_column": "sid",
        "gap_kind": "intermediate_producer_ambiguous",
        "mapping_basis": "multiple_repository_exact_table_producers_without_observed_workflow_path",
        "evidence": {
            "frontier_usage_id": "usage-opaque",
            "producer_resolution_candidates": [
                {"producer_id": "producer-A", "workflow": "wf-a", "kind": "sql_write", "table": "schema_a.source"},
                {"producer_id": "producer-B", "workflow": "wf-b", "kind": "sql_write", "table": "schema_b.source"},
            ],
        },
    }]
    result = build_deterministic_s2t([], mapping_gaps=gaps)
    assert len(result.rows) == 1
    assert result.rows[0][_idx("T-src")] == ""
    bounded = [gap for gap in result.gaps if gap.gap_type == BOUNDED_PRODUCER_AMBIGUITY]
    assert len(bounded) == 1
    assert bounded[0].candidate_ids == ("producer-A", "producer-B")
    assert bounded[0].source_gap_ids == ("public-gap-1",)


def test_large_producer_candidate_set_is_not_classified_as_bounded():
    gaps = [{
        "gap_id": "g", "workflow_target_logical_name": "mart.target", "target_column": "x",
        "gap_kind": "intermediate_producer_ambiguous",
        "evidence": {"producer_resolution_candidates": [{"producer_id": f"p{i}", "table": f"s.t{i}"} for i in range(6)]},
    }]
    result = build_deterministic_s2t([], mapping_gaps=gaps)
    assert [gap.gap_type for gap in result.gaps] == [INSUFFICIENT_EVIDENCE]


def test_builder_is_input_order_invariant_and_file_path_rename_invariant():
    rows = [
        _driver("a", branch="src.primary", workflow_context_file="one/path", source_sql_file="one.sql"),
        _driver("b", branch="src.primary", workflow_context_file="two/path", source_sql_file="two.sql"),
    ]
    forward = build_deterministic_s2t(rows)
    reverse = build_deterministic_s2t(list(reversed(rows)))
    renamed = build_deterministic_s2t([
        {**rows[0], "workflow_context_file": "renamed/x", "source_sql_file": "renamed-a.q"},
        {**rows[1], "workflow_context_file": "renamed/y", "source_sql_file": "renamed-b.q"},
    ])
    assert forward.rows == reverse.rows == renamed.rows
    assert [(g.gap_type, g.target_relation, g.target_column, g.candidate_ids) for g in forward.gaps] == [
        (g.gap_type, g.target_relation, g.target_column, g.candidate_ids) for g in reverse.gaps
    ]


def test_only_explicit_linked_non_direct_expression_enters_transformation_column():
    mappings = [
        _driver(
            "m1", column="norm", source_column="raw",
            linked_target_expressions=[
                {"expression": "raw", "expression_kind": "direct_column", "resolution_status": "resolved"},
                {"expression": "upper(raw)", "expression_kind": "function", "resolution_status": "resolved"},
                {"expression": "unresolved(raw)", "expression_kind": "function", "resolution_status": "partial"},
            ],
        )
    ]
    result = build_deterministic_s2t(mappings)
    assert len(result.rows) == 1
    assert result.rows[0][_idx("T-src-f")] == "upper(raw)"


def test_source_column_is_not_invented_from_target_name_when_public_mapping_lacks_it():
    mappings = [_driver(source_column="")]
    result = build_deterministic_s2t(mappings)
    assert result.rows[0][_idx("T-src")] == "base"
    assert result.rows[0][_idx("T-src-f-name")] == ""


def test_target_metadata_cannot_inject_source_identity():
    mappings = [_driver()]
    target_fields = [{
        "target_relation": "mart.target", "target_column": "id",
        "T-trg-platform": "platform-observed",
        "T-src-schema": "forbidden", "T-src": "forbidden", "T-src-f-name": "forbidden",
    }]
    result = build_deterministic_s2t(mappings, target_fields=target_fields)
    row = result.rows[0]
    assert row[_idx("T-trg-platform")] == "platform-observed"
    assert row[_idx("T-src-schema")] == "src"
    assert row[_idx("T-src")] == "base"
    assert row[_idx("T-src-f-name")] == "id"


def test_csv_contract_has_header_description_row_and_real_embedded_newline():
    result = build_deterministic_s2t([_driver()])
    text = render_s2t_csv(result.rows)
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[0] == list(S2T_COLUMNS)
    assert len(parsed[0]) == len(parsed[1]) == len(parsed[2]) == 26
    assert "\n*рекомендовано" in parsed[1][_idx("T-trg-f")]


def _ambiguous_usage_context(usage_id="usage-1", *, relations=None):
    return {
        "schema_version": "knowledge_api/v1",
        "usage": {
            "sql_column_usage_id": usage_id,
            "repo_id": "repo-x",
            "query_id": "query-x",
            "scope_id": "scope-x",
            "file": "opaque.sql",
            "column_name": "sid",
            "usage_role": "projection",
            "relation_id": None,
            "resolution_status": "ambiguous",
            "resolution_basis": "ambiguous_unqualified",
        },
        "scope": {"sql_select_scope_id": "scope-x", "query_id": "query-x", "file": "opaque.sql"},
        "scope_relations": relations or [
            {
                "sql_relation_id": "relation-present",
                "relation_kind": "physical",
                "relation_name": "schema_a.source",
                "output_contract_status": "complete",
                "output_contract_basis": "observed_complete_contract",
                "output_columns": ["sid", "other"],
            },
            {
                "sql_relation_id": "relation-absent",
                "relation_kind": "physical",
                "relation_name": "schema_b.dictionary",
                "output_contract_status": "complete",
                "output_contract_basis": "observed_complete_contract",
                "output_columns": ["code", "description"],
            },
            {
                "sql_relation_id": "relation-unknown",
                "relation_kind": "physical",
                "relation_name": "schema_c.unknown",
                "output_contract_status": "not_applicable",
                "output_contract_basis": "contract_not_available",
                "output_columns": [],
            },
        ],
        "counts": {"scope_relations": 3, "joins": 0, "projections": 1},
    }


def test_ambiguous_unqualified_usage_context_generates_bounded_survivor_set_without_selecting_winner():
    mappings = [{
        "mapping_id": "m-gap",
        "workflow_target_logical_name": "mart.target",
        "target_column": "sid",
        "immediate_source_column_usage_id": "usage-1",
        "source_relation_role": "unknown",
    }]
    gaps = [{
        "gap_id": "g-gap",
        "workflow_target_logical_name": "mart.target",
        "target_column": "sid",
        "gap_kind": "ultimate_source_identity_unresolved",
        "mapping_basis": "terminal_source_requires_relation_and_column_identity",
        "evidence": {"source_mapping_id": "m-gap"},
    }]
    result = build_deterministic_s2t(
        mappings,
        mapping_gaps=gaps,
        column_usage_contexts=[_ambiguous_usage_context()],
    )
    assert result.rows[0][_idx("T-src")] == ""
    bounded = [gap for gap in result.gaps if gap.gap_type == BOUNDED_PRODUCER_AMBIGUITY]
    assert len(bounded) == 1
    assert bounded[0].candidate_ids == ("relation-present", "relation-unknown")
    assert "candidate_relation_id:relation-present" in bounded[0].evidence_refs
    assert "excluded_relation_id:relation-absent" in bounded[0].evidence_refs
    assert "sql_column_usage_id:usage-1" in bounded[0].evidence_refs


def test_ambiguous_usage_candidate_generation_is_scope_relation_order_invariant():
    context = _ambiguous_usage_context()
    reversed_context = {**context, "scope_relations": list(reversed(context["scope_relations"]))}
    mappings = [{
        "mapping_id": "m-gap", "workflow_target_logical_name": "mart.target", "target_column": "sid",
        "immediate_source_column_usage_id": "usage-1", "source_relation_role": "unknown",
    }]
    gaps = [{
        "gap_id": "g-gap", "workflow_target_logical_name": "mart.target", "target_column": "sid",
        "gap_kind": "ultimate_source_identity_unresolved", "evidence": {"source_mapping_id": "m-gap"},
    }]
    one = build_deterministic_s2t(mappings, mapping_gaps=gaps, column_usage_contexts=[context])
    two = build_deterministic_s2t(mappings, mapping_gaps=gaps, column_usage_contexts=[reversed_context])
    one_bounded = [(g.gap_type, g.candidate_ids, g.evidence_refs) for g in one.gaps if g.gap_type == BOUNDED_PRODUCER_AMBIGUITY]
    two_bounded = [(g.gap_type, g.candidate_ids, g.evidence_refs) for g in two.gaps if g.gap_type == BOUNDED_PRODUCER_AMBIGUITY]
    assert one_bounded == two_bounded


def test_single_survivor_from_usage_context_is_not_promoted_by_consumer():
    context = _ambiguous_usage_context(relations=[
        {
            "sql_relation_id": "relation-present", "relation_kind": "physical", "relation_name": "schema_a.source",
            "output_contract_status": "complete", "output_contract_basis": "observed_complete_contract", "output_columns": ["sid"],
        },
        {
            "sql_relation_id": "relation-absent", "relation_kind": "physical", "relation_name": "schema_b.dictionary",
            "output_contract_status": "complete", "output_contract_basis": "observed_complete_contract", "output_columns": ["code"],
        },
    ])
    mappings = [{
        "mapping_id": "m-gap", "workflow_target_logical_name": "mart.target", "target_column": "sid",
        "immediate_source_column_usage_id": "usage-1", "source_relation_role": "unknown",
    }]
    gaps = [{
        "gap_id": "g-gap", "workflow_target_logical_name": "mart.target", "target_column": "sid",
        "gap_kind": "ultimate_source_identity_unresolved", "evidence": {"source_mapping_id": "m-gap"},
    }]
    result = build_deterministic_s2t(mappings, mapping_gaps=gaps, column_usage_contexts=[context])
    assert result.rows[0][_idx("T-src")] == ""
    assert not any(g.gap_type == BOUNDED_PRODUCER_AMBIGUITY for g in result.gaps)
    assert any(g.gap_type == INSUFFICIENT_EVIDENCE for g in result.gaps)


def test_non_ambiguous_usage_context_does_not_generate_candidate_set():
    context = _ambiguous_usage_context()
    context = {**context, "usage": {**context["usage"], "resolution_basis": "qualified_relation"}}
    mappings = [{
        "mapping_id": "m-gap", "workflow_target_logical_name": "mart.target", "target_column": "sid",
        "immediate_source_column_usage_id": "usage-1", "source_relation_role": "unknown",
    }]
    gaps = [{
        "gap_id": "g-gap", "workflow_target_logical_name": "mart.target", "target_column": "sid",
        "gap_kind": "ultimate_source_identity_unresolved", "evidence": {"source_mapping_id": "m-gap"},
    }]
    result = build_deterministic_s2t(mappings, mapping_gaps=gaps, column_usage_contexts=[context])
    assert not any(g.gap_type == BOUNDED_PRODUCER_AMBIGUITY for g in result.gaps)

def test_builder_preserves_partial_driver_template_and_typed_gap():
    mappings = [{
        "mapping_id": "m", "workflow_target_logical_name": "mart.target", "target_column": "id",
        "source_relation_role": "driver_path", "branch_relation_name": "stage.branch",
        "driver_relation_status": "partial", "driver_relation_name": "${$opaque.scope}.real",
        "source_sql_relation_name": "${$opaque.scope}.real", "source_sql_column": "id",
    }]
    result = build_deterministic_s2t(mappings)
    row = result.rows[0]
    assert row[_idx("T-src-schema")] == "${$opaque.scope}"
    assert row[_idx("T-src")] == "real"
    assert row[_idx("T-src-f-name")] == "id"
    assert any(gap.gap_type == UNRESOLVED_PLACEHOLDER for gap in result.gaps)


def test_resolved_environment_closes_primary_and_public_placeholder_gaps():
    template = "${$app.schema || '.source'}"
    mappings = [{
        "mapping_id": "m-env",
        "workflow_target_logical_name": "mart.target",
        "target_column": "id",
        "branch_relation_name": template,
        "driver_relation_name": template,
        "driver_relation_status": "partial",
        "source_relation_role": "driver_path",
        "source_sql_relation_name": template,
        "source_sql_column": "id",
    }]
    public_gaps = [{
        "gap_id": "g-env",
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
    }]
    environment = [{
        "semantic_key": ["mart.target", "id", template, "id"],
        "status": "resolved",
        "resolved_source_relation": "prod_schema.source",
    }]
    result = build_deterministic_s2t(
        mappings,
        mapping_gaps=public_gaps,
        environment_resolutions=environment,
    )
    row = result.rows[0]
    assert row[_idx("T-src-schema")] == "prod_schema"
    assert row[_idx("T-src")] == "source"
    assert not any(gap.gap_type == UNRESOLVED_PLACEHOLDER for gap in result.gaps)


def test_unresolved_environment_keeps_public_placeholder_gap():
    template = "${$app.schema || '.source'}"
    public_gaps = [{
        "gap_id": "g-env",
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
    }]
    result = build_deterministic_s2t([], mapping_gaps=public_gaps)
    assert any(gap.gap_type == UNRESOLVED_PLACEHOLDER for gap in result.gaps)
