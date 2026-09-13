import json
from pathlib import Path

from repository_topology.builder import build_topology


def _reduced(repo_id: str, observations: list[dict]) -> dict:
    exacts=[]; identities=[]
    for i, obs in enumerate(observations):
        eid=f"exact-{i}"
        exacts.append({
            "exact_representation_id": eid,
            "exact_representation_basis": {
                "family_kind":"http_boundary_observation",
                "observed_metrics": {
                    "protocol":"http","direction":obs["direction"],"method":obs["method"],"path_status":obs["path_status"]
                }
            }
        })
        facets=[]
        for idx,path in enumerate(obs.get("path_candidates",[])):
            facets.append({"path":f"$.path_candidates[{idx}]","value":path})
        for idx,name in enumerate(obs.get("request_fields",[])):
            facets.append({"path":f"$.request_fields[{idx}].name","value":name})
        for idx,name in enumerate(obs.get("response_fields",[])):
            facets.append({"path":f"$.response_fields[{idx}].name","value":name})
        identities.append({
            "observed_identity_id":f"obs-{repo_id}-{i}",
            "exact_representation_ids":[eid],
            "representative_evidence_id":f"evidence-{repo_id}-{i}",
            "occurrence_count":obs.get("occurrence_count",1),
            "identity":{"family_kind":"http_boundary_observation","family_label":obs["label"],"string_facets":facets}
        })
    return {
      "format":"repository-inventory-reduced/v3","reduced_inventory_id":f"reduced-{repo_id}","semantic_fingerprint":f"sem-{repo_id}",
      "source_inventory":{"repository_id":repo_id,"inventory_id":f"inv-{repo_id}","source_snapshot_fingerprint":f"snap-{repo_id}"},
      "exact_representations":exacts,"observed_identities":identities
    }


def _write(tmp_path: Path, repo: str, obs: list[dict]) -> Path:
    p=tmp_path/f"{repo}.json"; p.write_text(json.dumps(_reduced(repo,obs))); return p


def test_exact_http_edge_and_island(tmp_path):
    a=_write(tmp_path,"a",[{"direction":"outbound","method":"POST","path_status":"resolved","label":"/x"}])
    b=_write(tmp_path,"b",[{"direction":"inbound","method":"POST","path_status":"resolved","label":"/x"}])
    out=build_topology([a,b])
    assert out["summary"]["repository_count"] == 2
    assert out["summary"]["edge_count"] == 1
    assert out["summary"]["exact_edge_count"] == 1
    assert out["summary"]["probable_edge_count"] == 0
    assert out["summary"]["island_count"] == 1
    assert out["summary"]["half_wire_count"] == 2
    assert out["summary"]["matched_half_wire_count"] == 2
    assert out["summary"]["unmatched_half_wire_count"] == 0
    assert out["edges"][0]["match_classification"] == "exact"
    assert out["islands"][0]["repository_ids"] == ["a","b"]


def test_probable_requires_ambiguity_terminal_and_payload_fields(tmp_path):
    fields=["a","b","c","d","e"]
    a=_write(tmp_path,"a",[{"direction":"outbound","method":"POST","path_status":"ambiguous_declared_config","label":"prop","path_candidates":["/prefix/update"],"request_fields":fields}])
    b=_write(tmp_path,"b",[{"direction":"inbound","method":"POST","path_status":"resolved","label":"/update","request_fields":fields}])
    out=build_topology([a,b])
    assert len(out["edges"]) == 1
    assert out["edges"][0]["match_classification"] == "probable"


def test_unresolved_does_not_create_exact_edge(tmp_path):
    a=_write(tmp_path,"a",[{"direction":"outbound","method":"POST","path_status":"unresolved_expression","label":"path"}])
    b=_write(tmp_path,"b",[{"direction":"inbound","method":"POST","path_status":"resolved","label":"/x"}])
    out=build_topology([a,b])
    assert out["edges"] == []
    assert len(out["islands"]) == 2


def test_multiple_occurrences_do_not_inflate_edges(tmp_path):
    a=_write(tmp_path,"a",[{"direction":"outbound","method":"POST","path_status":"resolved","label":"/x","occurrence_count":6}])
    b=_write(tmp_path,"b",[{"direction":"inbound","method":"POST","path_status":"resolved","label":"/x"}])
    out=build_topology([a,b])
    assert len(out["edges"]) == 1
    assert out["edges"][0]["source_half_wires"][0]["occurrence_count"] == 6


def test_input_order_does_not_change_topology(tmp_path):
    a=_write(tmp_path,"a",[{"direction":"outbound","method":"POST","path_status":"resolved","label":"/x"}])
    b=_write(tmp_path,"b",[{"direction":"inbound","method":"POST","path_status":"resolved","label":"/x"}])
    assert build_topology([a,b]) == build_topology([b,a])
