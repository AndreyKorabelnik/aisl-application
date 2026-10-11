/* Task 52 local consumer-only prototype. No guessed semantic links or network IO. */
export const SINGLE = 'interaction-attribute-lineage/v1';
export const BATCH = 'interaction-lineage-candidate-batch/v1';
const isRecord = v => v !== null && typeof v === 'object' && !Array.isArray(v);
function fail(message) { throw new Error(message); }
function requireObject(v, at) { if (!isRecord(v)) fail(`${at}: expected an object`); return v; }
function requireString(v, at) { if (typeof v !== 'string' || !v.trim()) fail(`${at}: expected a nonempty string`); return v; }
function requireArray(v, at) { if (!Array.isArray(v)) fail(`${at}: expected an array`); return v; }
function sourceIdentity(side, node, at) {
  return JSON.stringify([
    requireString(side.repository_id, at+'.repository_id'),
    requireString(side.system_id, at+'.system_id'),
    requireString(side.revision_id, at+'.revision_id'),
    requireString(node.value_node_id, at+'.value_node_id')
  ]);
}
export function parseLineage(input) {
  const root=requireObject(input,'input');
  if(root.format===SINGLE) return [root];
  if(root.format!==BATCH) fail(`Unsupported JSON format: ${String(root.format)}. Expected ${SINGLE} or ${BATCH}`);
  return requireArray(root.edges,'edges').map((wrapper,i)=>{
    requireObject(wrapper,`edges[${i}]`);
    requireString(wrapper.edge_id,`edges[${i}].edge_id`);
    const result=requireObject(wrapper.result,`edges[${i}].result`);
    if(result.format!==SINGLE) fail(`edges[${i}].result.format must be ${SINGLE}`);
    if(result.edge?.edge_id!==wrapper.edge_id) fail(`edges[${i}]: wrapper edge_id and result.edge.edge_id disagree`);
    return result;
  });
}
const equivalentNode=(a,b)=> ['repo_id','display_ref','node_kind','source_path','source_line','operation','type_ref'].every(k=> (a[k]??null)===(b[k]??null));
function valueLabel(n){return n.display_ref||n.value_node_id;}
function safeGap(g, origin) {return {...g, __origin: origin};}
function graphIndex(graph) {
  const outgoing=new Map(),incoming=new Map();
  for(const n of graph.nodes.values()){outgoing.set(n.id,[]);incoming.set(n.id,[])}
  for(const e of graph.edges.values()){
    outgoing.get(e.source)?.push(e.id);
    incoming.get(e.target)?.push(e.id);
  }
  return {outgoing,incoming};
}
export function normalizeLineage(input) {
  const results=parseLineage(input);
  const graph={kind:input.format,results, nodes:new Map(),edges:new Map(),journeys:[],gaps:[],queryGaps:[],diagnostics:[],repositories:new Map(),interactions:[],crossingCount:0};
  const addNode=(side,node,origin)=>{
    requireObject(node,origin);
    const id=sourceIdentity(side,node,origin);
    let value=graph.nodes.get(id);
    if(value){
      if(!equivalentNode(value.raw,node)) fail(`Identity conflict at ${origin} (${id})`);
    }else{
      value={id,repository_id:side.repository_id,system_id:side.system_id,revision_id:side.revision_id,display_ref:valueLabel(node),raw:node,journeys:new Set()};
      graph.nodes.set(id,value);
    }
    graph.repositories.set(side.repository_id,{id:side.repository_id,system_id:side.system_id,revision_id:side.revision_id});
    return value;
  };
  for (let ri=0;ri<results.length;ri++) {
    const result=results[ri];
    requireObject(result,`result[${ri}]`);
    if (result.format!==SINGLE) fail(`result[${ri}]: wrong format`);
    const interaction=requireObject(result.edge,`result[${ri}].edge`);
    const edgeId=requireString(interaction.edge_id,`result[${ri}].edge.edge_id`);
    if(graph.interactions.some(e=>e.edge_id===edgeId)) fail(`Duplicate interaction edge: ${edgeId}`);
    graph.interactions.push(interaction);
    for(const g of requireArray(result.gaps,`result[${ri}].gaps`)) graph.gaps.push(safeGap(g,edgeId));
    for(const [ji,j] of requireArray(result.journeys,`result[${ri}].journeys`).entries()) {
      requireObject(j,`journeys[${ji}]`);
      const jid=requireString(j.journey_id,`journeys[${ji}].journey_id`);
      const fid=`${edgeId}/${jid}`;
      if(graph.journeys.some(old=>old.id===fid)) fail(`Duplicate journey: ${fid}`);
      if(j.edge_id!==edgeId) fail(`Journey ${fid} belongs to wrong edge`);
      const crossing=requireObject(j.crossing,`${fid}.crossing`);
      const status=requireString(crossing.status,`${fid}.crossing.status`);
      // Fail closed: unknown states must never look like proven links.
      if(!['candidate','confirmed','unresolved','missing'].includes(status)) fail(`${fid}: unknown crossing status ${status}`);
      const jr={id:fid,edge_id:edgeId,field_path:requireString(j.field_path,`${fid}.field_path`),transport_role:requireString(j.transport_role,`${fid}.transport_role`),source_repo:requireString(j.source_repository_id,`${fid}.source_repository_id`),target_repo:requireString(j.target_repository_id,`${fid}.target_repository_id`),nodeIds:new Set(),edgeIds:new Set(),status,raw:j};
      graph.journeys.push(jr);
      for(const sideName of ['source_side','target_side']) {
        const side=requireObject(j[sideName],`${fid}.${sideName}`);
        const res=requireObject(requireObject(side.query,`${fid}.${sideName}.query`).result,`${fid}.${sideName}.query.result`);
        if((side.query.system_id!==undefined&&side.query.system_id!==side.system_id)||(side.query.revision_id!==undefined&&side.query.revision_id!==side.revision_id)) fail(`${fid}.${sideName}: query owner/revision conflict`);
        if(sideName==='source_side' && side.repository_id!==jr.source_repo || sideName==='target_side' && side.repository_id!==jr.target_repo) fail(`${fid}: repository context mismatch`);
        if(side.resolved_anchor!=null){const n=addNode(side,side.resolved_anchor,`${fid}.${sideName}.resolved_anchor`);n.journeys.add(fid);jr.nodeIds.add(n.id)}
        for(const [pi,path] of requireArray(res.paths,`${fid}.${sideName}.query.result.paths`).entries()) {
          for(const [si,step] of requireArray(path.steps,`${fid}.${sideName}.paths[${pi}].steps`).entries()){
            requireObject(step,`${fid}.steps[${si}]`);
            const s=addNode(side,step.source,`${fid}.steps[${si}].source`);
            const t=addNode(side,step.target,`${fid}.steps[${si}].target`);
            s.journeys.add(fid);t.journeys.add(fid);jr.nodeIds.add(s.id);jr.nodeIds.add(t.id);
            const flowId=requireString(step.value_flow_edge_id,`${fid}.steps[${si}].value_flow_edge_id`);
            const eid=JSON.stringify(['local',side.repository_id,side.system_id,side.revision_id,flowId]);
            let e=graph.edges.get(eid);
            if(e){if(e.source!==s.id||e.target!==t.id||e.status!==(step.confidence||'unknown'))fail(`Local edge identity conflict: ${flowId}`)}
            else {
              e={id:eid,source:s.id,target:t.id,kind:'local',status:step.confidence||'unknown',basis:step.basis||'',flow_kind:step.flow_kind||'',raw:step,journeys:new Set(),evidence:[{edge_id:edgeId,journey_id:jid,side:sideName,path_index:pi,step_index:si}]};graph.edges.set(eid,e);
            }
            e.journeys.add(fid);jr.edgeIds.add(eid);
          }
        }
        for(const g of res.gaps||[])graph.queryGaps.push(safeGap(g,`${fid}/${sideName}`));
      }
      const sside=j.source_side,tside=j.target_side;
      if(sside.anchor_status==='resolved'&&tside.anchor_status==='resolved'&&sside.resolved_anchor&&tside.resolved_anchor){
        const sn=addNode(sside,sside.resolved_anchor,`${fid}.source_anchor`);
        const tn=addNode(tside,tside.resolved_anchor,`${fid}.target_anchor`);
        const eid=JSON.stringify(['crossing',fid]);
        if(graph.edges.has(eid))fail(`${fid}: duplicate crossing`);
        const e={id:eid,source:sn.id,target:tn.id,kind:'crossing',status, basis:crossing.basis||'',raw:crossing,journeys:new Set([fid]),evidence:[{edge_id:edgeId,journey_id:jid}],transport_role:jr.transport_role,field_path:jr.field_path};
        graph.edges.set(eid,e);jr.edgeIds.add(eid);jr.nodeIds.add(sn.id);jr.nodeIds.add(tn.id);graph.crossingCount++;
      }else{
        graph.diagnostics.push({kind:'missing_crossing_anchor',journey_id:fid,field_path:jr.field_path,source_anchor_status:sside.anchor_status,target_anchor_status:tside.anchor_status});
      }
    }
  }
  graph.index=graphIndex(graph);
  return graph;
}
export function reachable(graph,startId,direction='both',limit=120){
  const selected=new Set([startId]),edges=new Set(),queue=[startId];
  for(let p=0;p<queue.length && selected.size<limit;p++){
    const node=queue[p];
    const eids=[...(direction==='downstream'?[]:(graph.index.incoming.get(node)||[])),...(direction==='upstream'?[]:(graph.index.outgoing.get(node)||[]))];
    for(const id of eids){const e=graph.edges.get(id);if(!e)continue;edges.add(id);const other=e.source===node?e.target:e.source;if(!selected.has(other)){selected.add(other);queue.push(other)}}
  }
  return {nodeIds:selected,edgeIds:edges,truncated:selected.size>=limit};
}
export function selectedSubgraph(graph,selectedId=null,journeyId=null,direction='both',showCandidate=true){
  let nodeIds,edgeIds,truncated=false;
  if(selectedId){const r=reachable(graph,selectedId,direction);nodeIds=r.nodeIds;edgeIds=r.edgeIds;truncated=r.truncated;}
  else if(journeyId){const j=graph.journeys.find(j=>j.id===journeyId);nodeIds=new Set(j?.nodeIds||[]);edgeIds=new Set(j?.edgeIds||[])}
  else{nodeIds=new Set(graph.nodes.keys());edgeIds=new Set(graph.edges.keys())}
  if(!showCandidate){for(const id of edgeIds){if(graph.edges.get(id)?.kind==='crossing')edgeIds.delete(id)}}
  return {nodeIds,edgeIds,truncated};
}
export function counts(graph){
  return {interactions:graph.interactions.length,journeys:graph.journeys.length,nodes:graph.nodes.size,localEdges:[...graph.edges.values()].filter(e=>e.kind==='local').length,candidateCrossings:[...graph.edges.values()].filter(e=>e.kind==='crossing'&&e.status==='candidate').length,gaps:graph.gaps.length,unconnected:graph.diagnostics.length};
}

// Demo-only graph projections. Edges retain their exact published epistemic status.
// An ancestor/descendant is reached ONLY along the published directed edge.
export function traceNode(graph, startId, includeCandidate=true, maxNodes=5000){
  if(!graph.nodes.has(startId))throw new Error('Trace start node is not in the graph');
  function walk(forward){
    const nodes=new Set([startId]), edges=new Set(), queue=[startId];
    let truncated=false;
    for(let index=0;index<queue.length;index++){
      const id=queue[index], links=forward?graph.index.outgoing.get(id):graph.index.incoming.get(id);
      for(const edgeId of links||[]){
        const e=graph.edges.get(edgeId);
        if(!e||(e.kind==='crossing'&&!includeCandidate))continue;
        const next=forward?e.target:e.source;
        if(!nodes.has(next)&&nodes.size>=maxNodes){truncated=true;continue}
        edges.add(edgeId);
        if(!nodes.has(next)){nodes.add(next);queue.push(next)}
      }
    }
    return {nodes,edges,truncated};
  }
  const upstream=walk(false),downstream=walk(true);
  return {
    upstream,downstream,
    nodes:new Set([...upstream.nodes,...downstream.nodes]),
    edges:new Set([...upstream.edges,...downstream.edges]),
    candidateEdges:new Set([...upstream.edges,...downstream.edges].filter(id=>graph.edges.get(id)?.kind==='crossing')),
    truncated:upstream.truncated||downstream.truncated
  };
}

// Weak components are used ONLY to arrange the overview. They do NOT imply
// a directed, confirmed lineage route between arbitrary component members.
export function weakComponents(graph){
  const result=[],visited=new Set();
  for(const id of graph.nodes.keys()){
    if(visited.has(id))continue;
    const queue=[id];visited.add(id);
    for(let i=0;i<queue.length;i++){
      for(const edgeId of [...(graph.index.incoming.get(queue[i])||[]),...(graph.index.outgoing.get(queue[i])||[])]){
        const e=graph.edges.get(edgeId),next=e.source===queue[i]?e.target:e.source;
        if(!visited.has(next)){visited.add(next);queue.push(next)}
      }
    }
    result.push(queue);
  }
  return result.sort((a,b)=>b.length-a.length||a[0].localeCompare(b[0]));
}
