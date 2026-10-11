import {normalizeLineage,counts,selectedSubgraph,traceNode,weakComponents} from './graph-core.mjs';
import {demoData} from './demo-data.mjs';
const $=id=>document.getElementById(id);
const SVG='http://www.w3.org/2000/svg';
const X={graph:null,datasetName:'Синтетический пример · 3 взаимодействия',mode:'detail',focus:null,journey:null,selected:null,selectedType:null,direction:'both',showCandidate:true,zoom:1,tx:0,ty:0,bounds:null,lastLayout:null,example:'birthdate',search:'',panning:false,pointer:null,webFocus:null,webTrace:null,webPositions:null};
const REPOS=['ucp-service','kpk-client','profile-fl-loader','analytics-ui'];
const WEB_COLORS=['#5ceab1','#81bdfa','#c5a4fa','#fbd08c'];
const REPO_NAMES={'ucp-service':'UCP Service','kpk-client':'КПК · Client','profile-fl-loader':'Profile FL','analytics-ui':'Analytics UI'};
const initials=n=>REPO_NAMES[n]||n.replaceAll('-',' ');
const examples=[
 {id:'birthdate',icon:'↗',name:'birthDate → ageBucket',subtitle:'Три кандидатных пересечения',needle:'UCP.db.individual.birthDate',mode:'node'},
 {id:'fullname',icon:'⋈',name:'firstName + lastName',subtitle:'Объединение полей в КПК',needle:'KPK.mapper.composeFullName',mode:'node'},
 {id:'emaildomain',icon:'!',name:'emailDomain · разрыв',subtitle:'Источник не разрешён',needle:'customer.emailDomain',mode:'journey'},
 {id:'phone',icon:'⤷',name:'phone · terminal',subtitle:'Нет доказанного продолжения',needle:'individual.phone',mode:'journey'}
];
function svg(tag,attrs={},text){const e=document.createElementNS(SVG,tag);for(const [k,v] of Object.entries(attrs))if(v!==undefined && v!==null)e.setAttribute(k,String(v));if(text!==undefined)e.textContent=String(text);return e}
function clear(el){el.replaceChildren()}
function el(tag,attrs={},text){const x=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='class')x.className=v;else if(k==='title')x.title=v;else x.setAttribute(k,v)}if(text!==undefined)x.textContent=String(text);return x}
function addLine(container,cls,title,value){const row=el('div',{class:cls||'field-row'});row.append(el('span',{},title),el('strong',{},value??'—'));container.append(row)}
function addSection(container,title){const x=el('section',{class:'inspect-section'});x.append(el('h3',{},title));container.append(x);return x}
function rawBlock(container,value){const pre=el('pre',{class:'code-box'},JSON.stringify(value,null,2));container.append(pre)}
function chip(container,text,cls=''){container.append(el('span',{class:'pill '+cls},text))}
function alertMsg(msg,kind='warning'){const t=$('toast');t.textContent=msg;t.hidden=false;t.dataset.kind=kind;clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>t.hidden=true,6000)}
function nodeByName(needle){return [...X.graph.nodes.values()].find(n=>n.display_ref===needle)}
function firstJourney(needle){return X.graph.journeys.find(j=>j.field_path===needle)}
function loadGraph(input,name,isDemo=false){
  try{
    X.graph=normalizeLineage(input);X.datasetName=name;X.focus=null;X.journey=null;X.selected=null;X.selectedType=null;X.webFocus=null;X.webTrace=null;X.example=null;X.search='';$('search').value='';
    $('syntheticNotice').hidden=!isDemo;
    X.mode='detail';updateModeButtons();
    const root=nodeByName('UCP.db.individual.birthDate')||[...X.graph.nodes.values()][0];if(root){X.focus=root.id;X.selected=root.id;X.selectedType='node';X.example=isDemo?'birthdate':null}
    render();
    if(!isDemo)alertMsg(`Локальный JSON загружен: ${counts(X.graph).journeys} маршрутов. На сервер не отправлялся.`,'success');
  }catch(e){alertMsg('Не удалось загрузить JSON: '+e.message);console.warn('Input rejected:',e.message)}
}
function selectExample(item){
  X.example=item.id;
  if(item.mode==='node') {const n=nodeByName(item.needle);if(!n){alertMsg('В этом JSON пример не найден');return}X.focus=n.id;X.journey=null;X.selected=n.id;X.selectedType='node'}
  else{const j=firstJourney(item.needle);if(!j){alertMsg('В этом JSON пример не найден');return}X.focus=null;X.journey=j.id;X.selected=j.id;X.selectedType='journey'}
  if(X.mode==='web'){
    const chosen=item.mode==='node'?X.focus:[...(X.graph.journeys.find(j=>j.id===X.journey)?.nodeIds||[])][0];
    if(chosen){selectWebNode(chosen);return}
  }
  X.mode='detail';updateModeButtons();render();
}
function selectNode(id){if(X.mode==='web'){selectWebNode(id);return}X.focus=id;X.journey=null;X.selected=id;X.selectedType='node';X.example=null;X.mode='detail';render()}
function selectJourney(id){X.journey=id;X.focus=null;X.selected=id;X.selectedType='journey';X.example=null;X.mode='detail';render()}
function selectEdge(id){X.selected=id;X.selectedType='edge';renderGraph(false);renderInspector()}
function renderExamples(){const holder=$('examples');clear(holder);for(const item of examples){const b=el('button',{class:'example-button'+(X.example===item.id?' active':'')});b.append(el('span',{class:'example-icon'},item.icon));const t=el('div',{class:'example-copy'});t.append(el('strong',{},item.name),el('small',{},item.subtitle));b.append(t);b.addEventListener('click',()=>selectExample(item));holder.append(b)}}
function renderJourneys(){const holder=$('journeyList');clear(holder);$('journeyCount').textContent=X.graph.journeys.length;for(const j of X.graph.journeys){const btn=el('button',{class:'journey-item'+(X.journey===j.id?' active':'')});btn.append(el('span',{class:'bullet'}));const body=el('span');body.append(el('strong',{},j.field_path),el('small',{},`${j.transport_role==='response'?'Ответ':'Запрос'} · ${initials(j.source_repo)} → ${initials(j.target_repo)}`));btn.append(body);btn.addEventListener('click',()=>selectJourney(j.id));holder.append(btn)}}
function renderSearch(){const term=$('search').value.trim().toLowerCase();X.search=term;const holder=$('searchResults');clear(holder);if(!term){holder.hidden=true;return}const nodes=[...X.graph.nodes.values()].filter(n=>n.display_ref.toLowerCase().includes(term)).slice(0,14);const journeys=X.graph.journeys.filter(j=>j.field_path.toLowerCase().includes(term)).slice(0,6);for(const n of nodes){const b=el('button',{class:'search-item'});b.append(el('span',{},n.display_ref),el('small',{},initials(n.repository_id)));b.onclick=()=>{holder.hidden=true;$('search').value=n.display_ref;selectNode(n.id)};holder.append(b)}for(const j of journeys){const b=el('button',{class:'search-item'});b.append(el('span',{},j.field_path),el('small',{},`Взаимодействие · ${initials(j.source_repo)} → ${initials(j.target_repo)}`));b.onclick=()=>{holder.hidden=true;$('search').value=j.field_path;selectJourney(j.id)};holder.append(b)}if(!holder.childNodes.length)holder.append(el('div',{class:'search-item'},'Совпадений нет'));holder.hidden=false}
function graphStats(){const total=counts(X.graph);const subset=X.lastLayout;const ns=subset?.nodeIds.size??total.nodes;const es=subset?.edgeIds.size??X.graph.edges.size;const arr=[['Узлов',ns],['Переходов',es],['Кандидатов',total.candidateCrossings]];const h=$('miniCounts');clear(h);for(const [label,count] of arr){const x=el('div',{class:'stat-mini'});x.append(el('b',{},count),el('small',{},label));h.append(x)}}
function updateTitle(){
 const overview=X.mode==='overview',web=X.mode==='web';const focus=X.focus&&X.graph.nodes.get(X.focus);
 const journey=X.journey&&X.graph.journeys.find(j=>j.id===X.journey);
 $('canvasKicker').textContent=web?'ДЕМОНСТРАЦИОННЫЙ РЕЖИМ':overview?'УРОВЕНЬ СИСТЕМ':'ПОТОК АТРИБУТОВ';
 $('canvasHeading').textContent=web?'Паутина атрибутов':overview?'Карта взаимодействий':focus?focus.display_ref:journey?journey.field_path:'Граф атрибутов';
 $('canvasSubheading').textContent=web?'Вся опубликованная сеть · выберите узел, чтобы проследить входящие и исходящие ветви':overview?'Агрегированные взаимодействия не являются доказанными связями атрибутов':journey?`${initials(journey.source_repo)} → ${initials(journey.target_repo)} · ${journey.transport_role}`:'Сплошные линии — локальные факты; пунктирные — только кандидаты.';
}
function updateModeButtons(){
 for(const [id,mode] of [['overviewBtn','overview'],['detailBtn','detail'],['webBtn','web']]){$(id).classList.toggle('active',X.mode===mode);$(id).setAttribute('aria-pressed',String(X.mode===mode))}
 $('app').classList.toggle('web-mode',X.mode==='web');$('webOverlay').hidden=X.mode!=='web';$('webPresent').hidden=X.mode!=='web';
 if(X.mode!=='web'){$('app').classList.remove('web-present');$('webPresent').textContent='⛶ На весь экран'}
}
function setMode(mode){
 if(mode==='web'&&X.mode!=='web'){
   X.webFocus=null;X.webTrace=null;X.selected=null;X.selectedType=null;X.focus=null;X.journey=null;X.example=null;
 }else if(mode==='detail'&&X.mode==='web'){
   const node=X.webFocus&&X.graph.nodes.get(X.webFocus);X.focus=node?.id||nodeByName('UCP.db.individual.birthDate')?.id||null;
   X.selected=X.focus;X.selectedType=X.focus?'node':null;X.journey=null;
 }
 X.mode=mode;updateModeButtons();render();
}

function orderRepo(r){const i=REPOS.indexOf(r);return i>=0?i:REPOS.length}
const NODE_W=190,NODE_H=60;
function computeLevels(nodes,edges,root){
  const set=new Set(nodes),levels=new Map(),q=[];
  const out=new Map(),inc=new Map();for(const n of nodes){out.set(n,[]);inc.set(n,[])}
  for(const e of edges){if(set.has(e.source)&&set.has(e.target)){out.get(e.source).push(e.target);inc.get(e.target).push(e.source)}}
  let seeds;
  if(root&&set.has(root)){seeds=[root];levels.set(root,0);q.push(root)}
  else {const sources=nodes.filter(id=>inc.get(id).length===0);seeds=sources.length?sources:nodes.slice(0,1);for(const id of seeds){levels.set(id,0);q.push(id)}}
  for(let pos=0;pos<q.length;pos++){
    const id=q[pos],d=levels.get(id);for(const next of out.get(id)||[])if(!levels.has(next)){levels.set(next,d+1);q.push(next)}
  }
  if(root){for(let pos=0;pos<q.length;pos++){const id=q[pos],d=levels.get(id);for(const prev of inc.get(id)||[])if(!levels.has(prev)){levels.set(prev,d-1);q.push(prev)}}}
  for(const id of nodes)if(!levels.has(id)){const max=Math.max(0,...levels.values());levels.set(id,max+1)}
  return levels;
}
function layoutDetail(){
 const s=selectedSubgraph(X.graph,X.focus,X.journey,X.direction,X.showCandidate);X.lastLayout=s;
 const nodes=[...s.nodeIds].filter(id=>X.graph.nodes.has(id));const eds=[...s.edgeIds].map(id=>X.graph.edges.get(id)).filter(e=>e&&s.nodeIds.has(e.source)&&s.nodeIds.has(e.target));
 const levels=computeLevels(nodes,eds,X.focus);const byLevel=new Map();for(const id of nodes){const l=levels.get(id)||0;if(!byLevel.has(l))byLevel.set(l,[]);byLevel.get(l).push(id)}
 const positions=new Map(),sorted=[...byLevel.keys()].sort((a,b)=>a-b),min=sorted[0]??0;
 for(const [li,level] of sorted.entries()){
   const ids=byLevel.get(level).sort((a,b)=>orderRepo(X.graph.nodes.get(a).repository_id)-orderRepo(X.graph.nodes.get(b).repository_id)||X.graph.nodes.get(a).display_ref.localeCompare(X.graph.nodes.get(b).display_ref));
   for(let i=0;i<ids.length;i++)positions.set(ids[i],{x:45+(level-min)*250,y:70+i*94});
 }
 const maxX=Math.max(350,...[...positions.values()].map(p=>p.x+NODE_W));const maxY=Math.max(230,...[...positions.values()].map(p=>p.y+NODE_H));
 return {nodes,edges:eds,positions,bounds:{x:0,y:0,w:maxX+50,h:maxY+50},truncated:s.truncated};
}
function truncated(text,max=24){text=String(text);return text.length>max?text.slice(0,max-1)+'…':text}
function drawDetail(world,layout){
 const {nodes,edges,positions}=layout;
 for(const edge of edges){
  const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;
  const right=b.x>=a.x+80;const sx=right?a.x+NODE_W:a.x+NODE_W/2,sy=a.y+NODE_H/2;
  const tx=right?b.x:b.x+NODE_W/2,ty=b.y+NODE_H/2;
  const bend=Math.max(45,Math.abs(tx-sx)*.45);const path=right?`M${sx} ${sy} C${sx+bend} ${sy},${tx-bend} ${ty},${tx} ${ty}`:`M${sx} ${sy} C${sx+60} ${sy+40},${tx-60} ${ty-40},${tx} ${ty}`;
  const color=edge.kind==='crossing'?'candidate':edge.status!=='confirmed'?'uncertain':'';const e=svg('path',{d:path,class:`graph-edge ${color} ${X.selectedType==='edge'&&X.selected===edge.id?'selected':''}`,'marker-end':edge.kind==='crossing'?'url(#arrow-candidate)':'url(#arrow-confirmed)'});e.append(svg('title',{},edge.kind==='crossing'?`${edge.status.toUpperCase()} crossing · ${edge.field_path}`:`${edge.status} local value flow`));e.addEventListener('click',ev=>{ev.stopPropagation();selectEdge(edge.id)});world.append(e);
 }
 for(const id of nodes){const n=X.graph.nodes.get(id),p=positions.get(id);const g=svg('g',{class:`graph-node ${X.selectedType==='node'&&X.selected===id?'selected':''}`,transform:`translate(${p.x},${p.y})`});
  g.append(svg('rect',{class:'card-body',width:NODE_W,height:NODE_H,rx:10,ry:10}));
  g.append(svg('rect',{x:0,y:0,width:5,height:NODE_H,rx:2,fill:['#27a66e','#6887d3','#b28bd4','#e0ac55'][orderRepo(n.repository_id)%4]}));
  g.append(svg('circle',{class:'node-dot',cx:17,cy:22,r:4}));
  g.append(svg('text',{class:'primary-text',x:27,y:26},truncated(n.display_ref,26)));
  g.append(svg('text',{class:'secondary-text',x:16,y:47},truncated(initials(n.repository_id),34)));
  g.append(svg('title',{},`${n.display_ref}\n${n.repository_id}\n${n.system_id}@${n.revision_id}`));g.addEventListener('click',ev=>{ev.stopPropagation();selectNode(id)});world.append(g)
 }
 if(layout.truncated)world.append(svg('text',{class:'graph-caption',x:32,y:30},'Часть графа ограничена бюджетом 120 узлов; остальные связи сохранены в данных'));
}

// A graph-first demonstration layout; all data still comes from the normalizer.
// Weak components are a placement device only, NOT an assertion of directed lineage.
function webLayout(){
 const g=X.graph,components=weakComponents(g),positions=new Map();
 const repos=[...g.repositories.keys()].sort((a,b)=>orderRepo(a)-orderRepo(b)||a.localeCompare(b));
 const repoCols=new Map(repos.map((r,i)=>[r,i]));
 const worldWidth=120+repos.length*455;
 const laneDefs=[];let baseY=98;
 for(let i=0;i<components.length;i++){
  const ids=components[i],byRepo=new Map();
  for(const id of ids){const repo=g.nodes.get(id).repository_id;if(!byRepo.has(repo))byRepo.set(repo,[]);byRepo.get(repo).push(id)}
  const biggest=Math.max(...[...byRepo.values()].map(a=>a.length));
  const height=Math.max(51,biggest*13+24);
  laneDefs.push({component:ids,y:baseY,height,index:i});
  for(const [repo,list] of byRepo){
   const col=repoCols.get(repo);
   list.sort((a,b)=>g.nodes.get(a).display_ref.localeCompare(g.nodes.get(b).display_ref));
   for(let j=0;j<list.length;j++){
     const id=list[j],hash=[...id].reduce((acc,ch)=>Math.imul(acc^ch.charCodeAt(0),16777619)>>>0,2166136261);
     const shift=((hash%101)-50)*1.8;
     positions.set(id,{x:265+col*455+shift,y:baseY+(j+1)*height/(list.length+1),repo,component:i});
   }
  }
  baseY+=height+11;
 }
 const allEdges=[...g.edges.values()].filter(e=>X.showCandidate||e.kind!=='crossing');
 const ids=[...g.nodes.keys()];
 X.lastLayout={nodeIds:new Set(ids),edgeIds:new Set(allEdges.map(e=>e.id))};
 return {nodes:ids,edges:allEdges,positions,bounds:{x:0,y:0,w:worldWidth,h:baseY+36},height:baseY+36,laneDefs};
}
function webPath(a,b,edge){
 const d=b.x-a.x;const bend=Math.min(115,Math.max(28,Math.abs(d)*.46));
 return d>=0?`M${a.x} ${a.y} C${a.x+bend} ${a.y},${b.x-bend} ${b.y},${b.x} ${b.y}`:`M${a.x} ${a.y} C${a.x+85} ${a.y-12},${b.x-85} ${b.y+12},${b.x} ${b.y}`;
}
function webSelection(){return X.webFocus?traceNode(X.graph,X.webFocus,X.showCandidate):null}
function selectWebNode(id){
 if(!X.graph.nodes.has(id))return;
 X.webFocus=id;X.selected=id;X.selectedType='node';X.webTrace=webSelection();
 renderGraph(false);renderWebInfo();renderInspector();
}
function clearWebNode(){X.webFocus=null;X.webTrace=null;X.selected=null;X.selectedType=null;renderGraph(false);renderWebInfo();renderInspector()}
function drawWeb(world,layout){
 X.webPositions=layout.positions;
 const trace=X.webTrace=X.webFocus?webSelection():null;
 const cols=[...X.graph.repositories.keys()].sort((a,b)=>orderRepo(a)-orderRepo(b)||a.localeCompare(b));
 // Subtle vertical regions provide repository context without inventing grouping facts.
 for(const [ix,repo] of cols.entries()){const x=55+ix*455,region=svg('g',{class:'web-region'});
   region.append(svg('rect',{class:'web-region-fill',x,y:44,width:422,height:layout.height-72,rx:24}));
   region.append(svg('circle',{cx:x+22,cy:76,r:5,fill:WEB_COLORS[ix%WEB_COLORS.length]}));
   region.append(svg('text',{x:x+36,y:81,class:'web-region-title'},initials(repo)));
   region.append(svg('text',{x:x+399,y:81,'text-anchor':'end',class:'web-region-count'},`${[...X.graph.nodes.values()].filter(n=>n.repository_id===repo).length} узл.`));
   world.append(region);
 }
 const links=svg('g',{class:'web-links'}),halos=svg('g',{class:'web-halos'}),dots=svg('g',{class:'web-dots'}),labels=svg('g',{class:'web-labels'});
 world.append(links,halos,dots,labels);
 for(const edge of layout.edges){const a=layout.positions.get(edge.source),b=layout.positions.get(edge.target);if(!a||!b)continue;
  const active=trace?.edges.has(edge.id),isUp=trace?.upstream.edges.has(edge.id),isDown=trace?.downstream.edges.has(edge.id);
  const cls=['spider-edge',edge.kind==='crossing'?'candidate':'local',trace?(active?'lit':'muted'):'idle',isUp?'upstream':'',isDown?'downstream':''].join(' ');
  const line=svg('path',{d:webPath(a,b,edge),class:cls,'data-edge-id':edge.id});line.append(svg('title',{},`${edge.kind==='crossing'?'CANDIDATE transport':'Локальный переход · '+edge.status}
${X.graph.nodes.get(edge.source)?.display_ref} → ${X.graph.nodes.get(edge.target)?.display_ref}`));links.append(line);
 }
 for(const id of layout.nodes){const n=X.graph.nodes.get(id),p=layout.positions.get(id),ix=cols.indexOf(n.repository_id),selected=id===X.webFocus;
  const inPath=trace?.upstream.nodes.has(id),outPath=trace?.downstream.nodes.has(id),isActive=selected||inPath||outPath;
  const cls=['spider-node',trace?(isActive?'lit':'muted'):'idle',selected?'selected':'',inPath?'upstream':'',outPath?'downstream':''].join(' ');
  if(isActive){halos.append(svg('circle',{class:'spider-halo '+(selected?'center':'branch'),cx:p.x,cy:p.y,r:selected?24:15}));}
  const group=svg('g',{class:cls,transform:`translate(${p.x},${p.y})`,'data-node-id':id,tabindex:0,role:'button','aria-label':n.display_ref});
  group.append(svg('circle',{class:'spider-hit',r:18}));
  group.append(svg('circle',{class:'spider-core',r:selected?11:8.2,fill:WEB_COLORS[ix%WEB_COLORS.length]}));
  group.append(svg('circle',{class:'spider-spot',r:selected?4.5:3,fill:'#edfdfd'}));
  group.append(svg('title',{},`${n.display_ref}
${initials(n.repository_id)}
Нажмите, чтобы выделить все доступные ветви`));
  group.addEventListener('click',e=>{e.stopPropagation();selectWebNode(id)});
  group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectWebNode(id)}});
  dots.append(group);
  if(selected){
   const x=p.x+20,above=p.y>140;
   const label=svg('g',{class:'spider-name-label',transform:`translate(${x},${above?p.y-32:p.y+20})`});
   label.append(svg('rect',{width:Math.min(325,Math.max(115,n.display_ref.length*7+25)),height:32,rx:8}));
   label.append(svg('text',{x:11,y:20},truncated(n.display_ref,43)));
   labels.append(label);
  }
 }
}
function renderWebInfo(){
 const root=$('webInfo');clear(root);
 if(X.mode!=='web')return;
 const c=counts(X.graph),n=X.webFocus&&X.graph.nodes.get(X.webFocus),trace=X.webTrace;
 if(!n||!trace){const big=el('div',{class:'web-metrics'});big.append(el('b',{},c.nodes+' узлов'),el('span',{},(c.localEdges+(X.showCandidate?c.candidateCrossings:0))+' переходов'),el('span',{},`${weakComponents(X.graph).length} групп связности`));root.append(big);root.append(el('div',{class:'web-explainer'},'Вся сеть на одном экране. Выберите точку — подсветим направления к источникам и потребителям. Пунктир означает кандидатную связь.'));$('webClear').hidden=true;return}
 root.append(el('div',{class:'web-label'},'ВЫБРАННЫЙ УЗЕЛ'));
 root.append(el('div',{class:'web-current'},n.display_ref));
 const chips=el('div',{class:'web-metrics'});chips.append(el('span',{class:'upstream-count'},`← ${trace.upstream.nodes.size-1} до узла`),el('span',{class:'downstream-count'},`${trace.downstream.nodes.size-1} после узла →`),el('span',{class:'candidate-count'},`◆ ${trace.candidateEdges.size} candidate`));root.append(chips);
 const hint=el('div',{class:'web-explainer'},'Подсвечены только направленные переходы; пунктир не означает подтверждённый межсистемный путь.');root.append(hint);
 const actions=el('div',{class:'web-info-actions'});
 const btn=el('button',{class:'web-action'},'Показать цепочку крупнее');btn.onclick=zoomWebTrace;
 const details=el('button',{class:'web-action secondary'},'Детали →');details.onclick=()=>setMode('detail');
 actions.append(btn,details);root.append(actions);$('webClear').hidden=false;
}
function zoomWebTrace(){
 if(!X.webTrace||!X.webPositions)return;
 const points=[...X.webTrace.nodes].map(id=>X.webPositions.get(id)).filter(Boolean);if(!points.length)return;
 const minX=Math.min(...points.map(p=>p.x))-135,maxX=Math.max(...points.map(p=>p.x))+145,minY=Math.min(...points.map(p=>p.y))-110,maxY=Math.max(...points.map(p=>p.y))+110;
 const rect=$('stage').getBoundingClientRect(),scale=Math.min(1.45,(rect.width-140)/Math.max(1,maxX-minX),(rect.height-95)/Math.max(1,maxY-minY));
 X.zoom=Math.max(.18,scale);X.tx=(rect.width-(maxX-minX)*X.zoom)/2-minX*X.zoom;X.ty=(rect.height-(maxY-minY)*X.zoom)/2-minY*X.zoom;applyTransform();
}
function webMatches(){
 const term=$('webSearch').value.trim().toLowerCase(),holder=$('webSearchResults');clear(holder);
 if(!term){holder.hidden=true;return}
 const nodes=[...X.graph.nodes.values()].filter(n=>n.display_ref.toLowerCase().includes(term)).slice(0,8);
 for(const n of nodes){const btn=el('button',{class:'web-search-item'},truncated(n.display_ref,55));btn.onclick=()=>{holder.hidden=true;selectWebNode(n.id)};holder.append(btn)}
 if(!nodes.length)holder.append(el('div',{class:'web-search-item'},'Совпадений нет'));
 holder.hidden=false;
}

function layoutOverview(){const found=[...X.graph.repositories.keys()].sort((a,b)=>orderRepo(a)-orderRepo(b)||a.localeCompare(b));const positions=new Map();found.forEach((id,i)=>positions.set(id,{x:70+i*305,y:170}));const links=new Map();for(const j of X.graph.journeys){const id=j.source_repo+'→'+j.target_repo;if(!links.has(id))links.set(id,{source:j.source_repo,target:j.target_repo,journeys:0,eligible:0});const l=links.get(id);l.journeys++;if(j.raw.source_side.anchor_status==='resolved'&&j.raw.target_side.anchor_status==='resolved')l.eligible++}return {found,positions,links:[...links.values()],bounds:{x:0,y:0,w:Math.max(510,found.length*305+100),h:520}}}
function drawOverview(world,layout){X.lastLayout={nodeIds:new Set(X.graph.nodes.keys()),edgeIds:new Set(X.graph.edges.keys())};
 for(const l of layout.links){const a=layout.positions.get(l.source),b=layout.positions.get(l.target);if(!a||!b)continue;const from={x:a.x+(b.x>=a.x?220:0),y:a.y+69},to={x:b.x+(b.x>=a.x?0:220),y:b.y+69};const bend=Math.max(80,Math.abs(to.x-from.x)/2);const curve=`M${from.x} ${from.y} C${from.x+(to.x>from.x?bend:-bend)} ${from.y-55},${to.x+(to.x>from.x?-bend:bend)} ${to.y+55},${to.x} ${to.y}`;
 world.append(svg('path',{d:curve,class:'repo-link','marker-end':'url(#arrow-candidate)'}));const mid=(from.x+to.x)/2;world.append(svg('text',{class:'repo-label',x:mid,y:from.y-72,'text-anchor':'middle'},`${l.journeys} атрибутов · ${l.eligible} якорных пар`))}
 for(const repo of layout.found){const p=layout.positions.get(repo);const g=svg('g',{class:'repo-box',transform:`translate(${p.x},${p.y})`});g.append(svg('rect',{width:220,height:138,rx:14}));g.append(svg('circle',{cx:29,cy:31,r:14,fill:'#eaf7ef'}));g.append(svg('text',{x:29,y:36,'text-anchor':'middle',fill:'#11965f','font-size':12},'◈'));g.append(svg('text',{class:'name',x:18,y:71},initials(repo)));g.append(svg('text',{class:'meta',x:18,y:97},`${[...X.graph.nodes.values()].filter(n=>n.repository_id===repo).length} локальных узлов`));g.append(svg('text',{class:'meta',x:18,y:116},'Открыть атрибуты →'));g.addEventListener('click',()=>{const node=[...X.graph.nodes.values()].find(n=>n.repository_id===repo);if(node)selectNode(node.id)});world.append(g)}
 world.append(svg('text',{class:'graph-caption',x:75,y:87},'Агрегированный обзор. Пунктир означает кандидатное взаимодействие, не доказанный путь атрибута.'))
}
function applyTransform(){const w=$('world');w.setAttribute('transform',`translate(${X.tx},${X.ty}) scale(${X.zoom})`)}
function fitView(){if(!X.bounds)return;const rect=$('stage').getBoundingClientRect();const b=X.bounds;const ideal=Math.min(1.1,(rect.width-78)/Math.max(1,b.w),(rect.height-90)/Math.max(1,b.h));X.zoom=Math.max(.22,Math.min(1.7,ideal));X.tx=(rect.width-b.w*X.zoom)/2-b.x*X.zoom;X.ty=(rect.height-b.h*X.zoom)/2-b.y*X.zoom;applyTransform()}
function focusView(layout){
 const rect=$('stage').getBoundingClientRect();X.zoom=.83;
 const pos=layout.positions;const root=X.focus&&pos?.get(X.focus);
 const first=root || (pos ? [...pos.values()].sort((a,b)=>a.x-b.x)[0] : null);
 X.tx=(rect.width*.22)-(first?.x||0)*X.zoom;
 X.ty=(rect.height*.48)-(first?.y||0)*X.zoom;
 applyTransform();
}
function renderGraph(fit=true){
 if(!X.graph)return;const world=$('world');clear(world);
 const layout=X.mode==='overview'?layoutOverview():X.mode==='web'?webLayout():layoutDetail();X.bounds=layout.bounds;X.currentLayout=layout;
 if(X.mode==='overview')drawOverview(world,layout);else if(X.mode==='web')drawWeb(world,layout);else drawDetail(world,layout);
 if(fit){if(X.mode==='detail'&&layout.bounds.w>$('stage').getBoundingClientRect().width*1.5)focusView(layout);else fitView()}else applyTransform();
 graphStats();updateTitle();if(X.mode==='web')renderWebInfo();
}
function showGaps(body,journey){const relevant=X.graph.gaps.filter(g=>g.__origin===journey.edge_id&&g.field_path===journey.field_path&&g.transport_role===journey.transport_role);
 const warnings=[];if(journey.raw.source_side.anchor_status!=='resolved')warnings.push('Источник: '+journey.raw.source_side.anchor_status);if(journey.raw.target_side.anchor_status!=='resolved')warnings.push('Получатель: '+journey.raw.target_side.anchor_status);for(const g of relevant)warnings.push(g.reason+' · '+g.side);
 for(const warning of warnings)body.append(el('div',{class:'warning-card'},'⚠ '+warning));
}
function inspectJourney(body,j){body.append(el('div',{class:'inspect-tag'},'АТРИБУТ ВЗАИМОДЕЙСТВИЯ'));body.append(el('div',{class:'inspect-title'},j.field_path));chip(body,j.transport_role==='response'?'HTTP response':'HTTP request');chip(body,j.status==='candidate'?'CANDIDATE':j.status,j.status==='candidate'?'amber':'green');addLine(body,'field-row','Направление значений',`${initials(j.source_repo)} → ${initials(j.target_repo)}`);
 if(j.status==='candidate')body.append(el('div',{class:'warning-card'},'Межсистемная связь получена из topology candidate. Независимого подтверждения пересечения нет.'));
 showGaps(body,j);const sec=addSection(body,'Якоря и привязки');for(const sideName of ['source_side','target_side']){const x=j.raw[sideName];addLine(sec,'field-row',sideName==='source_side'?'Отправитель':'Получатель',`${x.anchor_status} · ${x.resolved_anchor?.display_ref||'якорь не разрешён'}`)}const sec2=addSection(body,'Основание crossing');addLine(sec2,'field-row','Basis',j.raw.crossing.basis);rawBlock(addSection(body,'Исходный фрагмент'),{crossing:j.raw.crossing,source_side_status:j.raw.source_side.anchor_status,target_side_status:j.raw.target_side.anchor_status})}
function renderInspector(){const body=$('inspectorBody');clear(body);if(!X.graph||!X.selected){body.append(el('div',{class:'empty-inspector'},'Выберите узел или переход на графе.'));return}
 const g=X.graph;
 if(X.selectedType==='node'){
  const n=g.nodes.get(X.selected);if(!n)return;
  body.append(el('div',{class:'inspect-tag'},'ЛОКАЛЬНЫЙ УЗЕЛ · VALUE NODE'));body.append(el('div',{class:'inspect-title'},n.display_ref));chip(body,initials(n.repository_id));chip(body,n.raw.node_kind||'value');
  body.append(el('div',{class:'success-card'},'Узел опубликован в локальном value-flow. Это не подтверждает соседние межсистемные crossing.'));
  const sec=addSection(body,'Владелец и идентичность');addLine(sec,'field-row','Repository',n.repository_id);addLine(sec,'field-row','System',n.system_id);addLine(sec,'field-row','Revision',n.revision_id);addLine(sec,'field-row','Value node ID',n.raw.value_node_id);
  const ev=addSection(body,'Исходный материал');addLine(ev,'field-row','Путь',n.raw.source_path||'Нет');addLine(ev,'field-row','Строка',n.raw.source_line||'Нет');addLine(ev,'field-row','Операция',n.raw.operation||'Нет');addLine(ev,'field-row','Journeys',n.journeys.size);
  rawBlock(addSection(body,'Оригинальные данные'),n.raw);
 } else if(X.selectedType==='edge'){
  const e=g.edges.get(X.selected);if(!e)return;
  body.append(el('div',{class:'inspect-tag'},e.kind==='crossing'?'МЕЖСИСТЕМНЫЙ ПЕРЕХОД':'ЛОКАЛЬНЫЙ ПЕРЕХОД'));body.append(el('div',{class:'inspect-title'},e.kind==='crossing'?e.field_path:'Value flow'));
  chip(body,e.kind==='crossing'?'CROSSING':'LOCAL');chip(body,e.status||'unknown',e.kind==='crossing'?'amber':'green');
  if(e.kind==='crossing')body.append(el('div',{class:'warning-card'},e.status==='candidate'?'Переход только кандидатный. Пунктирная линия не является доказательством передачи значения.':'Статус пересечения: '+e.status));
  else if(e.status!=='confirmed')body.append(el('div',{class:'warning-card'},'Локальная связь не имеет статуса confirmed: '+e.status));
  const sec=addSection(body,'Направление данных');addLine(sec,'field-row','Из',g.nodes.get(e.source)?.display_ref);addLine(sec,'field-row','В',g.nodes.get(e.target)?.display_ref);addLine(sec,'field-row','Basis',e.basis);addLine(sec,'field-row','Journeys',e.journeys.size);
  rawBlock(addSection(body,'Опубликованное evidence'),{edge:e.raw,provenance:e.evidence});
 }else if(X.selectedType==='journey'){const j=g.journeys.find(j=>j.id===X.selected);if(j)inspectJourney(body,j)}
 if(window.innerWidth<=880)$('inspector').classList.add('open')
}
function render(){if(!X.graph)return;updateModeButtons();renderExamples();renderJourneys();renderGraph();renderInspector();renderSearch()}
function zoom(mult,clientX,clientY){const rect=$('stage').getBoundingClientRect(),sx=(clientX??rect.left+rect.width/2)-rect.left,sy=(clientY??rect.top+rect.height/2)-rect.top,prior=X.zoom;X.zoom=Math.max(.15,Math.min(3,prior*mult));X.tx=sx-(sx-X.tx)*X.zoom/prior;X.ty=sy-(sy-X.ty)*X.zoom/prior;applyTransform()}
function registerEvents(){
 $('btnDemo').addEventListener('click',()=>loadGraph(demoData,'Синтетический пример · 3 взаимодействия',true));
 $('btnUpload').addEventListener('click',()=>$('fileUpload').click());
 async function takeFile(file){if(!file)return;if(file.size>30*1024*1024){alertMsg('Для этой версии допустим JSON до 30 МБ');return}try{const str=await file.text();loadGraph(JSON.parse(str),file.name)}catch(e){alertMsg('Ошибка чтения файла: '+e.message)}}
 $('fileUpload').addEventListener('change',e=>{takeFile(e.target.files?.[0]);e.target.value=''});
 let drags=0;document.addEventListener('dragenter',e=>{if(!e.dataTransfer?.types?.includes('Files'))return;drags++;$('dropOverlay').hidden=false});document.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files'))e.preventDefault()});document.addEventListener('dragleave',e=>{drags--;if(drags<=0){drags=0;$('dropOverlay').hidden=true}});document.addEventListener('drop',e=>{e.preventDefault();drags=0;$('dropOverlay').hidden=true;takeFile(e.dataTransfer?.files?.[0])});
 $('search').addEventListener('input',renderSearch);$('search').addEventListener('keydown',e=>{if(e.key==='Escape'){$('search').value='';renderSearch()}});
 $('overviewBtn').addEventListener('click',()=>setMode('overview'));
 $('detailBtn').addEventListener('click',()=>setMode('detail'));
 $('webBtn').addEventListener('click',()=>setMode('web'));
 $('webClear').addEventListener('click',clearWebNode);
 $('webSearch').addEventListener('input',webMatches);
 $('webSearch').addEventListener('keydown',e=>{if(e.key==='Enter'){const n=[...X.graph.nodes.values()].find(n=>n.display_ref.toLowerCase().includes(e.target.value.toLowerCase()));if(n){$('webSearchResults').hidden=true;selectWebNode(n.id)}}if(e.key==='Escape')$('webSearchResults').hidden=true});
 $('webPresent').addEventListener('click',()=>{const p=$('app').classList.toggle('web-present');$('webPresent').textContent=p?'↙ Обычный вид':'⛶ На весь экран';fitView()});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&X.mode==='web'){$('app').classList.remove('web-present');$('webPresent').textContent='⛶ На весь экран';$('webSearchResults').hidden=true;clearWebNode();fitView()}});
 $('candidateToggle').addEventListener('change',e=>{X.showCandidate=e.target.checked;renderGraph()});
 $('flowDirection').addEventListener('change',e=>{X.direction=e.target.value;renderGraph()});
 $('resetSelection').addEventListener('click',()=>{X.selected=null;X.selectedType=null;$('inspector').classList.remove('open');renderGraph(false);renderInspector()});
 $('zoomIn').addEventListener('click',()=>zoom(1.3));$('zoomOut').addEventListener('click',()=>zoom(1/1.3));$('fit').addEventListener('click',fitView);
 const stage=$('stage'),graph=$('graph');
 graph.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1.12:1/1.12,e.clientX,e.clientY)},{passive:false});
 graph.addEventListener('pointerdown',e=>{if(e.button!==0)return;if(e.target.closest?.('.spider-node,.graph-node,.graph-edge,.repo-box,.spider-edge'))return;X.panning=true;X.pointer={x:e.clientX,y:e.clientY};graph.classList.add('panning');graph.setPointerCapture(e.pointerId)});
 graph.addEventListener('pointermove',e=>{if(!X.panning||!X.pointer)return;X.tx+=e.clientX-X.pointer.x;X.ty+=e.clientY-X.pointer.y;X.pointer={x:e.clientX,y:e.clientY};applyTransform()});
 const up=()=>{X.panning=false;X.pointer=null;graph.classList.remove('panning')};graph.addEventListener('pointerup',up);graph.addEventListener('pointercancel',up);
 $('graphBackground').addEventListener('click',()=>{if(X.mode==='web')clearWebNode()});
 const observer=new ResizeObserver(()=>{if(!X.graph||!X.bounds)return;const l=X.currentLayout;if(X.mode==='detail' && l?.bounds?.w>$('stage').getBoundingClientRect().width*1.5)focusView(l);else fitView()});observer.observe(stage);
}
registerEvents();loadGraph(demoData,'Синтетический пример · 3 взаимодействия',true);
