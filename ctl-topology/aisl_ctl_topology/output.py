from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

CSV_COLUMNS=("row_kind","producer_system","producer_revision","producer_flow","producer_flow_id","consumer_system",
             "consumer_revision","consumer_flow","consumer_flow_id","profile","entity_id","statistic_id",
             "status","stat_supported","producer_candidates","trigger_id","source_file")


def write_json(data: Mapping[str,Any], path: str | Path) -> None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def write_csv(data: Mapping[str,Any], path: str | Path) -> None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for e in data["edges"]:
        rows.append({**e,"row_kind":"dependency"})
    for g in data["gaps"]:
        rows.append({**g,"row_kind":"gap"})
    # An isolated flow is still shown, so missing edges do not imply missing flows.
    connected={(e["producer_system"],e["producer_revision"],e["producer_flow_id"]) for e in data["edges"]}
    connected.update((e["consumer_system"],e["consumer_revision"],e["consumer_flow_id"]) for e in data["edges"])
    for revision in data["revisions"]:
        for flow in revision["records"]["ctl_flow"]:
            key=(revision["system_id"],revision["revision_id"],str(flow.get("flow_id") or ""))
            if key not in connected:
                rows.append({"row_kind":"flow","consumer_system":key[0],"consumer_revision":key[1],
                             "consumer_flow":flow.get("flow_name") or "","status":"active" if flow.get("active") else "inactive",
                             "source_file":flow.get("source_file") or ""})
    rows.sort(key=lambda r:tuple(str(r.get(col) or "") for col in CSV_COLUMNS))
    with target.open('w',encoding='utf-8-sig',newline='') as out:
        writer=csv.DictWriter(out,fieldnames=CSV_COLUMNS,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)


def _node(system:str,revision:str,flow_id:str)->str:
    return 'n'+hashlib.sha256(f'{system}\x00{revision}\x00{flow_id}'.encode()).hexdigest()[:16]


def _label(s:str)->str:
    return str(s).replace('"','\\"').replace('\n',' ')


def write_mermaid(data:Mapping[str,Any],path:str|Path)->None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    lines=['flowchart LR']
    for rev in data['revisions']:
        sys,revision=rev['system_id'],rev['revision_id']
        sub='s'+hashlib.sha256(f'{sys}@{revision}'.encode()).hexdigest()[:12]
        lines.append(f'  subgraph {sub}["{_label(sys)} @ {_label(revision)}"]')
        for f in rev['records']['ctl_flow']:
            lines.append(f'    {_node(sys,revision,str(f.get("flow_id") or ""))}["{_label(f.get("flow_name") or f.get("flow_id") or "unknown")}"]')
        lines.append('  end')
    seen=set()
    for edge in data['edges']:
        a=_node(edge['producer_system'],edge['producer_revision'],edge['producer_flow_id'])
        b=_node(edge['consumer_system'],edge['consumer_revision'],edge['consumer_flow_id'])
        relation='-->' if edge['status']=='resolved_unique' and edge.get('stat_supported') is not False else '-.->'
        label=_label(f'{edge["profile"]}.{edge["entity_id"]}.{edge["statistic_id"]} [{edge["status"]}]')
        line=f'  {a} {relation}|"{label}"| {b}'
        if line not in seen:lines.append(line);seen.add(line)
    for gap in data['gaps']:
        # Ambiguous candidates are already represented by dotted candidate
        # edges; no speculative extra producer node is created for them.
        if gap['status'] == 'ambiguous_multiple':
            continue
        consumer=_node(gap['consumer_system'],gap['consumer_revision'],gap.get('consumer_flow_id',''))
        identity=(gap['consumer_system'],gap['consumer_revision'],gap.get('trigger_id',''))
        unresolved='u'+hashlib.sha256(('\x00'.join(identity)).encode()).hexdigest()[:16]
        label=_label(f"unresolved upstream: {gap.get('profile') or '?'} / {gap.get('entity_id') or '?'} / stat {gap.get('statistic_id') or '?'}")
        lines.append(f'  {unresolved}["{label}"]')
        lines.append(f'  {unresolved} -.->|"{_label(gap["status"])}"| {consumer}')
    target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
