from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

from aisl_s2t.builder import S2T_COLUMNS, build_deterministic_s2t
from aisl_s2t.revision_source import (
    REQUIRED_CAPABILITIES,
    RevisionBuildInputs,
    RevisionSourceError,
    collect_revision_inputs,
)


@dataclass
class _Execution:
    result: dict


class _Integration:
    def __init__(self, candidates, pages):
        self.candidates = list(candidates)
        self.pages = dict(pages)
        self.calls = []

    def execute_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "find_sql_target_candidates":
            offset = int(arguments["offset"])
            limit = int(arguments["limit"])
            items = self.candidates[offset:offset + limit]
            return _Execution({
                "system_id": "system-x",
                "revision_id": "revision-y",
                "candidate_count": len(self.candidates),
                "returned_count": len(items),
                "candidates": items,
                "diagnostics": [],
            })
        if name == "list_sql_target_value_sources":
            key = (arguments["target_relation"], int(arguments["offset"]))
            return _Execution(self.pages[key])
        raise AssertionError(name)


class _Pinned:
    def __init__(self, integration, capabilities=None):
        self._integration = integration
        self._capabilities = tuple(capabilities or REQUIRED_CAPABILITIES)

    def get_capabilities(self):
        return self._capabilities

    def integration(self, profile_id):
        assert profile_id == "sql-analysis/v1"
        return self._integration


class _Client:
    def __init__(self, pinned):
        self.pinned = pinned

    def revision(self, system_id, revision_id):
        assert (system_id, revision_id) == ("system-x", "revision-y")
        return self.pinned


def _candidate(name, *, kind="workflow_target", repo="repo-a", status="confirmed_unique", physical=None, contexts=None):
    return {
        "repo_id": repo,
        "logical_target_name": name,
        "recommended_target_relation": physical,
        "target_relation_recommendation_status": status,
        "target_kind": kind,
        "workflow_contexts": contexts or [f"workflow/{name}.yaml"],
    }


def _page(target, offset, total, mappings, *, expressions=None, gaps=None, truncated=False):
    return {
        "schema_version": "knowledge_api/v1",
        "mapping_schema_version": "target-source-mapping/v4",
        "system_id": "system-x",
        "revision_id": "revision-y",
        "target_relation": target,
        "page": {"offset": offset, "limit": 100, "total": total},
        "mappings": mappings,
        "target_expressions": expressions or [],
        "transformation_sets": [],
        "gaps": gaps or [],
        "gap_count": len(gaps or []),
        "gaps_truncated": truncated,
        "summary": {},
    }


def _source(mapping_id, relation, column, *, role="driver_path", status="resolved", refs=None):
    return {
        "relation": relation,
        "column": column,
        "status": status,
        "value_mapping_id": mapping_id,
        "source_relation_role": role,
        "contribution_roles": ["projection_value"],
        "target_expression_refs": refs or [],
        "mapping_basis": "raw_terminal_sql_origin",
        "provenance": {},
    }


def test_revision_inputs_use_all_eligible_targets_and_never_rank_one_winner():
    candidates = [
        _candidate("final_a", physical="dm.final_a"),
        _candidate("intermediate_x", kind="intermediate"),
        _candidate("final_b", repo="repo-b", status="probable_ranked", physical="maybe.final_b"),
        _candidate("disabled", contexts=["workflow/__off__/disabled.yaml"]),
    ]
    pages = {
        ("final_a", 0): _page("final_a", 0, 1, [{
            "target_column": "id", "source_count": 1, "mapping_status": "complete",
            "sources": [_source("v1", "src.a", "id")],
        }]),
        ("final_b", 0): _page("final_b", 0, 1, [{
            "target_column": "code", "source_count": 1, "mapping_status": "complete",
            "sources": [_source("v2", "src.b", "code")],
        }]),
    }
    integration = _Integration(candidates, pages)
    inputs = collect_revision_inputs(_Client(_Pinned(integration)), system_id="system-x", revision_id="revision-y")

    assert inputs.retrieval["target_candidates_seen"] == 4
    assert inputs.retrieval["eligible_targets"] == 2
    assert inputs.retrieval["skipped_intermediate_targets"] == 1
    assert inputs.retrieval["skipped_disabled_targets"] == 1
    assert {row["workflow_target_logical_name"] for row in inputs.mapping_rows} == {"dm.final_a", "final_b"}
    calls = [args for name, args in integration.calls if name == "list_sql_target_value_sources"]
    assert {item["target_relation"] for item in calls} == {"final_a", "final_b"}


def test_revision_inputs_preserve_multiple_sources_expression_and_gap_only_target():
    candidates = [_candidate("target", physical="mart.target")]
    expressions = [
        {"expression": "id", "expression_kind": "direct_column", "output_name": "id", "resolution_status": "resolved"},
        {"expression": "upper(code)", "expression_kind": "function", "output_name": "id", "resolution_status": "resolved"},
    ]
    pages = {
        ("target", 0): _page("target", 0, 2, [
            {
                "target_column": "id", "source_count": 2, "mapping_status": "complete",
                "sources": [
                    _source("v1", "src.a", "id", refs=[0, 1]),
                    _source("v2", "src.b", "code", refs=[1]),
                ],
            },
            {
                "target_column": "missing_source", "source_count": 0,
                "mapping_status": "unresolved", "sources": [],
            },
        ], expressions=expressions, gaps=[{
            "gap_id": "g1",
            "gap_kind": "ultimate_source_identity_unresolved",
            "severity": "source_identity_missing",
            "owner_id": "missing_source",
            "message": "terminal_identity_missing",
            "details": {
                "target_column": "missing_source",
                "workflow_context_file": "wf.yaml",
                "impact": "source_identity_missing",
                "mapping_basis": "terminal_identity_missing",
                "evidence": {},
            },
        }]),
    }
    inputs = collect_revision_inputs(_Client(_Pinned(_Integration(candidates, pages))), system_id="system-x", revision_id="revision-y")
    result = build_deterministic_s2t(
        inputs.mapping_rows,
        mapping_gaps=inputs.mapping_gaps,
        target_fields=inputs.target_fields,
    )
    idx = {name: S2T_COLUMNS.index(name) for name in ("T-trg-f", "T-src", "T-src-f-name", "T-src-f")}
    id_rows = [row for row in result.rows if row[idx["T-trg-f"]] == "id"]
    assert {(row[idx["T-src"]], row[idx["T-src-f-name"]], row[idx["T-src-f"]]) for row in id_rows} == {
        ("a", "id", "upper(code)"),
        ("b", "code", "upper(code)"),
    }
    missing = [row for row in result.rows if row[idx["T-trg-f"]] == "missing_source"]
    assert len(missing) == 1
    assert missing[0][idx["T-src"]] == ""


def test_missing_required_capability_fails_closed():
    integration = _Integration([], {})
    client = _Client(_Pinned(integration, capabilities={"common.sql-target-resolution"}))
    with pytest.raises(RevisionSourceError, match="common.sql-target-value-source-mapping"):
        collect_revision_inputs(client, system_id="system-x", revision_id="revision-y")


def test_invalid_expression_reference_fails_closed():
    candidates = [_candidate("target", physical="mart.target")]
    pages = {
        ("target", 0): _page("target", 0, 1, [{
            "target_column": "id", "source_count": 1, "mapping_status": "complete",
            "sources": [_source("v1", "src.a", "id", refs=[7])],
        }]),
    }
    with pytest.raises(RevisionSourceError, match="outside target_expressions"):
        collect_revision_inputs(
            _Client(_Pinned(_Integration(candidates, pages))),
            system_id="system-x", revision_id="revision-y",
        )


def test_eligible_targets_with_no_fields_mappings_or_gaps_fail_closed():
    candidates = [_candidate("target", physical="mart.target")]
    pages = {
        ("target", 0): _page("target", 0, 0, []),
    }
    with pytest.raises(
        RevisionSourceError,
        match=r"eligible_targets=1, target_fields=0, mapping_rows=0, mapping_gaps=0",
    ):
        collect_revision_inputs(
            _Client(_Pinned(_Integration(candidates, pages))),
            system_id="system-x",
            revision_id="revision-y",
        )


def test_zero_eligible_targets_may_return_empty_public_inputs():
    inputs = collect_revision_inputs(
        _Client(_Pinned(_Integration([], {}))),
        system_id="system-x",
        revision_id="revision-y",
    )
    assert inputs.mapping_rows == ()
    assert inputs.mapping_gaps == ()
    assert inputs.target_fields == ()
    assert inputs.retrieval["eligible_targets"] == 0
