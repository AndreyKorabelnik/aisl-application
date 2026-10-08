"""Consumer-only CTL topology composition; evidence truth stays in AISL."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .gateway import CTL_RECORD_KINDS


def _text(v: Any) -> str:
    return str(v) if v is not None else ""


def _stats(value: Any) -> frozenset[str]:
    try:
        data = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return frozenset()
    return frozenset(map(str, data)) if isinstance(data, list) else frozenset()


def build_topology(revisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Produce complete source-preserving JSON and explicitly qualified flow projections.

    - locally published dependencies are retained as-is, including ambiguity/status;
    - cross-revision links require exact profile/entity and published stat support;
    - publication relations take precedence over broader linked_entity occurrences;
    - missing/ambiguous producers are never promoted into confirmed edges.
    """
    identities: set[tuple[str,str]] = set()
    systems: set[str] = set()
    snapshots: list[dict[str, Any]] = []
    producers: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    all_flows: dict[tuple[str, str, str], dict] = {}
    for revision in revisions:
        sys, rev = _text(revision["system_id"]), _text(revision["revision_id"])
        if (sys, rev) in identities or sys in systems:
            raise ValueError(f"duplicate pinned revision/system {sys}/{rev}")
        identities.add((sys, rev))
        systems.add(sys)
        records = revision["records"]
        if any(k not in records or not isinstance(records[k], list) for k in CTL_RECORD_KINDS):
            raise ValueError(f"missing published CTL record kind: {sys}/{rev}")
        snapshot = {"system_id": sys, "revision_id": rev,
                    "artifact_id": _text(revision["artifact_id"]),
                    "records": {k: sorted((dict(row) for row in records[k]), key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)) for k in CTL_RECORD_KINDS}}
        snapshots.append(snapshot)
        for flow in records["ctl_flow"]:
            all_flows[(sys,rev,_text(flow.get("flow_id")))] = flow
        for fe in records["ctl_flow_entity"]:
            if not fe.get("active") or fe.get("relation") not in {"linked_entity", "published_entity"}:
                continue
            flow=all_flows.get((sys,rev,_text(fe.get("flow_id"))))
            if flow is None or not flow.get("active"):
                continue
            key = (_text(fe.get("profile")), _text(fe.get("entity_id")))
            if all(key):
                producers[key].append({"system_id":sys,"revision_id":rev,"flow_id":_text(fe.get("flow_id")),
                                       "flow_name":_text(fe.get("flow_name")),"source_file":_text(fe.get("source_file")),
                                       "relation":fe.get("relation"),"published_stats":sorted(_stats(fe.get("published_stats_json")))})
    snapshots.sort(key=lambda x:(x["system_id"],x["revision_id"]))
    for key, values in list(producers.items()):
        # precedence is scoped to a revision: a direct declaration in one revision
        # does not erase a declaration from another published system.
        by_rev:dict[tuple[str,str],list[dict]]=defaultdict(list)
        for row in values: by_rev[(row["system_id"],row["revision_id"])].append(row)
        selected=[]
        for rows in by_rev.values():
            direct=[x for x in rows if x["relation"]=="published_entity"]
            selected.extend(direct or rows)
        unique={(p["system_id"],p["revision_id"],p["flow_id"]):p for p in selected}
        producers[key]=sorted(unique.values(),key=lambda x:(x["system_id"],x["revision_id"],x["flow_id"]))

    edges=[]; gaps=[]
    for rev in snapshots:
        sys, revision=rev["system_id"],rev["revision_id"]
        records=rev["records"]
        locally_resolved={_text(d.get("trigger_id")) for d in records["ctl_dependency"]}
        for d in records["ctl_dependency"]:
            edges.append({"kind":"repository_local","status":_text(d.get("resolution_status")),
                          "producer_system":sys,"producer_revision":revision,
                          "producer_flow_id":_text(d.get("producer_flow_id")),
                          "producer_flow":_text(d.get("producer_flow_name")),
                          "consumer_system":sys,"consumer_revision":revision,
                          "consumer_flow_id":_text(d.get("consumer_flow_id")),
                          "consumer_flow":_text(d.get("consumer_flow_name")),
                          "profile":_text(d.get("profile")),"entity_id":_text(d.get("entity_id")),
                          "statistic_id":_text(d.get("statistic_id")),
                          "stat_supported":d.get("producer_stat_supported"),
                          "producer_candidates":int(d.get("producer_candidate_count") or 0),
                          "source_file":_text(d.get("provenance_json")),
                          "trigger_id":_text(d.get("trigger_id"))})
        for trigger in records["ctl_trigger"]:
            if not trigger.get("active") or _text(trigger.get("trigger_id")) in locally_resolved or not all_flows.get((sys,revision,_text(trigger.get("flow_id"))),{}).get("active"):
                continue
            key=(_text(trigger.get("upstream_profile")), _text(trigger.get("upstream_entity_id")))
            stat=_text(trigger.get("statistic_id"))
            if not all(key) or not stat:
                gaps.append({"consumer_system":sys,"consumer_revision":revision,
                             "consumer_flow":_text(trigger.get("flow_name")),"consumer_flow_id":_text(trigger.get("flow_id")),"source_file":_text(trigger.get("source_file")),"trigger_id":_text(trigger.get("trigger_id")),
                             "status":"unresolved_trigger_identity","profile":key[0],"entity_id":key[1],"statistic_id":stat})
                continue
            external=[p for p in producers.get(key,()) if (p["system_id"],p["revision_id"]) != (sys,revision)]
            confirmed=[p for p in external if stat in p["published_stats"]]
            if len(confirmed)==1:
                status="resolved_unique"
            elif len(confirmed)>1:
                status="ambiguous_multiple"
            elif external:
                status="statistic_not_confirmed"
            else:
                status="external_half_wire"
            if confirmed:
                for p in confirmed:
                    edges.append({"kind":"cross_revision","status":status,
                                  "producer_system":p["system_id"],"producer_revision":p["revision_id"],
                                  "producer_flow_id":p["flow_id"],"producer_flow":p["flow_name"],
                                  "consumer_system":sys,"consumer_revision":revision,
                                  "consumer_flow_id":_text(trigger.get("flow_id")),
                                  "consumer_flow":_text(trigger.get("flow_name")),
                                  "profile":key[0],"entity_id":key[1],"statistic_id":stat,
                                  "stat_supported":True,"producer_candidates":len(confirmed),
                                  "source_file":_text(trigger.get("source_file")),
                                  "trigger_id":_text(trigger.get("trigger_id"))})
            if status!='resolved_unique':
                gaps.append({"consumer_system":sys,"consumer_revision":revision,
                             "consumer_flow":_text(trigger.get("flow_name")),"consumer_flow_id":_text(trigger.get("flow_id")),"source_file":_text(trigger.get("source_file")),"trigger_id":_text(trigger.get("trigger_id")),
                             "status":status,"profile":key[0],"entity_id":key[1],"statistic_id":stat,
                             "producer_candidates":len(confirmed),"candidate_revisions":sorted({f'{p["system_id"]}@{p["revision_id"]}' for p in external})})
    edges.sort(key=lambda x:tuple(_text(x.get(k)) for k in ("consumer_system","consumer_revision","consumer_flow_id","profile","entity_id","statistic_id","producer_system","producer_revision","producer_flow_id")))
    gaps.sort(key=lambda x:tuple(_text(x.get(k)) for k in ("consumer_system","consumer_revision","trigger_id","status")))
    return {"schema_version":"aisl-ctl-topology/v1","revisions":snapshots,
            "edges":edges,"gaps":gaps,
            "counts":{"revisions":len(snapshots),"flows":sum(len(r["records"]["ctl_flow"]) for r in snapshots),
                      "edges":len(edges),"gaps":len(gaps)}}
