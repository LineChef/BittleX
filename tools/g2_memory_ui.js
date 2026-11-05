/* The Facts tab of the review page (inserted into tools/g2_review.py's page at start-up): where each fact came from, how often G2 was given and used it, filters and sorting, and one form to add or edit a fact. */
(function(){
const SRC={told:"told in conversation",hand:"added by hand",goal_lesson:"goal lesson",reflection:"inferred (reflection)"};
const srcName=s=>SRC[s]||s||"unknown";
const OFTEN=20;                                   // given to G2 this many times and never used: worth a look
const fx={source:"all",core:false,unused:false,low:false,often:false,sort:"newest",tidy:false};
let tidy=null,tidyFor=null;
let info={core_max:12},infoAsked=false;
const used=r=>Math.max(r.declared||0,r.matched||0);
const given=r=>r.injected||0;
const flagged=r=>given(r)>=OFTEN&&used(r)===0;
const nice=d=>{if(!d)return "";const m=/^(\d{4})-(\d\d)-(\d\d)/.exec(d);if(!m)return d;const mo=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];return mo[+m[2]-1]+" "+(+m[3])};
const waiting=id=>((window.reviewState&&window.reviewState.pending)||[]).filter(p=>new RegExp("fact #"+id+"(\\D|$)").test(p.text||""));
const SORTS={newest:["Newest first",(a,b)=>b.id-a.id],importance:["Most important first",(a,b)=>b.importance-a.importance||b.id-a.id],
 lastused:["Used most recently",(a,b)=>(b.last_used||"").localeCompare(a.last_used||"")||b.id-a.id],mostused:["Used most",(a,b)=>used(b)-used(a)||given(b)-given(a)],mostgiven:["Given to G2 most",(a,b)=>given(b)-given(a)]};

function renderFacts(list,f){
 if(!infoAsked){infoAsked=true;api("/api/facts/info").then(i=>{info=i;render()}).catch(()=>{})}
 const all=data||[],g2btn=window.g2btn;
 const cores=all.filter(r=>r.core).length,srcs={};for(const r of all)srcs[r.source||"unknown"]=(srcs[r.source||"unknown"]||0)+1;
 const nOften=all.filter(flagged).length,nUnused=all.filter(r=>used(r)===0).length,nLow=all.filter(r=>r.importance<=2).length;
 // summary and filters
 const box=el("div","labelsum");
 box.append(el("b","",all.length+(all.length===1?" fact":" facts")+" · core "+cores+" of "+info.core_max),
  el("div","sub","Core facts are always given to G2, most important first, up to "+info.core_max+". “Given” is how often a fact was handed to G2 for a reply; “used” is how often G2 named it or the reply echoed it."));
 const row1=el("div");row1.style.marginTop="6px";row1.append(el("span","meta","Where it came from: "));
 row1.append(g2btn("All",()=>{fx.source="all";render()},fx.source==="all"?"on":""));
 for(const k of Object.keys(srcs).sort())row1.append(g2btn(srcName(k)+" ("+srcs[k]+")",()=>{fx.source=k;render()},fx.source===k?"on":""));
 const row2=el("div");row2.style.marginTop="4px";
 const tog=(key,label,n)=>row2.append(g2btn(label+(n===undefined?"":" ("+n+")"),()=>{fx[key]=!fx[key];render()},fx[key]?"on":""));
 tog("core","Core only",cores);tog("unused","Never used",nUnused);tog("often","Given often, never used",nOften);tog("low","Importance 1 to 2",nLow);
 const sel=el("select");for(const k of Object.keys(SORTS)){const o=el("option","",SORTS[k][0]);o.value=k;sel.append(o)}sel.value=fx.sort;sel.onchange=()=>{fx.sort=sel.value;render()};sel.style.marginLeft="8px";row2.append(el("span","meta","Sort: "),sel);
 if(fx.source!=="all"||fx.core||fx.unused||fx.low||fx.often||fx.sort!=="newest")row2.append(g2btn("Clear",()=>{Object.assign(fx,{source:"all",core:false,unused:false,low:false,often:false,sort:"newest"});render()}));
 const tb=g2btn(fx.tidy?"Back to the list":"Tidy up",()=>{fx.tidy=!fx.tidy;render()},fx.tidy?"on":"");tb.title="Possible duplicates, facts that name a date or time, and facts G2 is never given or never uses";tb.style.marginLeft="8px";row2.append(tb);
 box.append(row1,row2);list.append(box);
 if(fx.tidy){renderTidy(list,all);return}

 let items=all.filter(r=>(fx.source==="all"||(r.source||"unknown")===fx.source)&&(!fx.core||r.core)&&(!fx.unused||used(r)===0)&&(!fx.low||r.importance<=2)&&(!fx.often||flagged(r))&&(!f||JSON.stringify(r).toLowerCase().includes(f)));
 items=items.slice().sort(SORTS[fx.sort][1]);
 if(!items.length){list.append(el("div","empty",all.length?"No fact matches these filters.":"Nothing here."));return}
 list.append(el("div","meta","Showing "+items.length+" of "+all.length));
 for(const r of items){
  const row=el("div","row"),main=el("div","main");
  main.append(el("div","",r.fact));
  const meta=el("div","meta","#"+r.id+" · "+nice(r.ts)+" · ");
  const sc=el("span","gchip",srcName(r.source));meta.append(sc,document.createTextNode("importance "+r.importance));
  if(r.core)meta.append(el("span","gchip ok","core"));
  main.append(meta);
  const u=el("div","meta");
  if(r.injected===undefined)u.textContent="No usage data in this copy.";
  else if(!given(r))u.textContent="Never given to G2 yet.";
  else u.textContent="Given "+given(r)+"× · used "+used(r)+"×"+(used(r)?" (named "+(r.declared||0)+", echoed "+(r.matched||0)+")":"")+(r.last_used?" · last used "+nice(r.last_used):"");
  main.append(u);
  if(flagged(r)){const w=el("div","meta","Given "+given(r)+" times and never used: it may be worded too vaguely, or not worth keeping.");w.style.color="var(--x)";main.append(w)}
  if(r.source==="goal_lesson")main.append(el("div","meta","A goal lesson: it also shows on the Goals tab."));
  if(waiting(r.id).length){const p=el("span","gchip pend","waiting for the Pi");p.title=waiting(r.id).map(x=>x.text).join("; ");meta.append(p)}
  row.append(main);
  const tools=el("div");tools.style.cssText="display:flex;gap:6px;align-items:center;flex:none";
  const e=el("button","btn","Edit");e.onclick=()=>factForm(r);
  const c=el("button","btn",r.core?"Not core":"Make core");c.title=r.core?"Stop giving this fact to G2 every time":"Give this fact to G2 every time (up to "+info.core_max+" core facts)";
  c.onclick=async()=>{try{await api("/api/facts/edit",{id:r.id,core:!r.core});const was=!!r.core;load();toast(was?"No longer core":"Now core",async()=>{await api("/api/facts/edit",{id:r.id,core:was});load()})}catch(x){toast("Failed: "+x.message)}};
  tools.append(e,c);row.append(tools);
  row.append(xbtn(async()=>{try{const t=await api("/api/delete",{kind:"facts",id:r.id});data=data.filter(d=>d!==r);render();toast("Moved to the Trash",async()=>{await api("/api/restore",{trash_id:t.trash_id});load()})}catch(x){toast("Failed: "+x.message)}}));
  list.append(row)}
}

// ---- the tidy-up view
const ign=()=>{try{return new Set(JSON.parse(localStorage.getItem("g2TidyIgnore")||"[]"))}catch(e){return new Set()}};
const addIgn=k=>{try{const s=ign();s.add(k);localStorage.setItem("g2TidyIgnore",JSON.stringify([...s]))}catch(e){}};
async function delFact(r){try{const t=await api("/api/delete",{kind:"facts",id:r.id});tidyFor=null;load();toast("Fact #"+r.id+" moved to the Trash",async()=>{await api("/api/restore",{trash_id:t.trash_id});tidyFor=null;load()})}catch(x){toast("Failed: "+x.message)}}
function miniFact(r){const d=el("div");d.append(el("div","",r.fact));
 const m=el("div","meta","#"+r.id+" \u00b7 "+nice(r.ts)+" \u00b7 "+srcName(r.source)+" \u00b7 importance "+r.importance+(r.core?" \u00b7 core":"")+" \u00b7 given "+(r.injected||0)+"\u00d7, used "+used(r)+"\u00d7");d.append(m);return d}
function tidySection(list,title,items,empty,draw){const sf=fold(title+" ("+items.length+")",items.length>0);if(!items.length)sf.append(el("div","meta",empty));else for(const it of items)sf.append(draw(it));list.append(sf)}
function renderTidy(list,all){
 const g2btn=window.g2btn;
 if(tidyFor!==data){tidyFor=data;tidy=null;api("/api/facts/tidy").then(t=>{tidy=t;if(fx.tidy)render()}).catch(e=>{tidy={error:e.message};render()})}
 if(!tidy){list.append(el("div","empty","Looking for things to tidy\u2026"));return}
 if(tidy.error){list.append(el("div","empty","Could not check: "+tidy.error));return}
 const hide=ign();
 const dups=tidy.duplicates.filter(p=>!hide.has("dup:"+p.a.id+"-"+p.b.id)),dated=tidy.dated.filter(r=>!hide.has("date:"+r.id));
 const dead=all.filter(flagged),cores=all.filter(r=>r.core).sort((a,b)=>b.importance-a.importance||b.id-a.id),extra=cores.slice(info.core_max);
 const total=dups.length+dated.length+tidy.look_like.length+dead.length+extra.length;
 list.append(el("div","meta",total?total+" thing"+(total===1?"":"s")+" to look at. Nothing is changed until you press a button; deleted facts go to the Trash with an Undo.":"Nothing to tidy: no near-duplicates, no dated facts, nothing unused."));
 tidySection(list,"Say nearly the same thing",dups,"No near-duplicate pairs.",p=>{
  const row=el("div","row"),main=el("div","main");main.append(el("div","meta","Word overlap "+Math.round(p.score*100)+"%"),miniFact(p.a),el("hr"),miniFact(p.b));
  const act=el("div");act.style.marginTop="6px";
  act.append(g2btn("Keep #"+p.a.id+", delete #"+p.b.id,()=>delFact(p.b)),g2btn("Keep #"+p.b.id+", delete #"+p.a.id,()=>delFact(p.a)),g2btn("They are different",()=>{addIgn("dup:"+p.a.id+"-"+p.b.id);render()}));
  main.append(act);row.append(main);return row});
 tidySection(list,"Name a date or time",dated,"No dated facts.",r=>{
  const row=el("div","row"),main=el("div","main");main.append(miniFact(r),el("div","meta","G2\u2019s memory refuses to save facts like this himself: a fact should stay true, not log when something happened."));
  const act=el("div");act.style.marginTop="6px";act.append(g2btn("Edit",()=>factForm(r)),g2btn("Delete",()=>delFact(r),"danger"),g2btn("Fine as it is",()=>{addIgn("date:"+r.id);render()}));main.append(act);row.append(main);return row});
 tidySection(list,"More than one \u201cI look like\u2026\u201d fact",tidy.look_like,"One at most.",r=>{
  const row=el("div","row"),main=el("div","main");main.append(miniFact(r),el("div","meta","How G2 looks is a single slot: the newest description replaces older ones."));
  const act=el("div");act.style.marginTop="6px";act.append(g2btn("Edit",()=>factForm(r)),g2btn("Delete",()=>delFact(r),"danger"));main.append(act);row.append(main);return row});
 tidySection(list,"Given often and never used",dead,"None.",r=>{
  const row=el("div","row"),main=el("div","main");main.append(miniFact(r));
  const act=el("div");act.style.marginTop="6px";act.append(g2btn("Edit",()=>factForm(r)),g2btn("Delete",()=>delFact(r),"danger"));main.append(act);row.append(main);return row});
 tidySection(list,"Core facts G2 is not given (over the limit of "+info.core_max+")",extra,"All core facts fit.",r=>{
  const row=el("div","row"),main=el("div","main");main.append(miniFact(r),el("div","meta","Only the "+info.core_max+" most important core facts are given every time."));
  const act=el("div");act.style.marginTop="6px";act.append(g2btn("Make not core",async()=>{try{await api("/api/facts/edit",{id:r.id,core:false});tidyFor=null;load()}catch(x){toast("Failed: "+x.message)}}),g2btn("Raise importance",()=>factForm(r)));main.append(act);row.append(main);return row});
}

// ---- one form to add (r = null) or edit a fact; a refusal shows in the form and keeps it open
const IMPORTANCE=[{value:1,label:"1 — rarely matters"},{value:2,label:"2 — minor"},{value:3,label:"3 — normal"},{value:4,label:"4 — important"},{value:5,label:"5 — essential"}];
async function factForm(r){
 const all=data||[],cores=all.filter(x=>x.core).length,full=cores>=info.core_max&&!(r&&r.core);
 const fields=[{key:"fact",label:"The fact",type:"textarea",value:r?r.fact:"",hint:"A stable thing G2 should know, for example: The dishwasher is next to the fridge."},
  {key:"importance",label:"How much it matters",type:"select",options:IMPORTANCE,value:r?r.importance:3},
  {key:"core",label:"Always give it to G2 (core)",type:"select",options:[{value:"0",label:"No"},{value:"1",label:"Yes — every reply"}],value:r&&r.core?"1":"0",hint:full?"You already have "+cores+" core facts and G2 is given at most "+info.core_max+" (most important first).":""}];
 if(r)fields.push({key:"ts",label:"Date",value:(r.ts||"").slice(0,10),hint:"Like 2026-10-10, or 2026-10-10 18:30."});
 let result=null;
 const v=await window.g2ask(r?"Edit fact #"+r.id:"Add a fact",fields,r?"Save":"Add fact",async v=>{
  const fact=(v.fact||"").trim();if(!fact)throw new Error("Write the fact first.");
  if(!r){result=await api("/api/facts/add",{fact,importance:+v.importance,core:v.core==="1"});return}
  const body={id:r.id};
  if(fact!==r.fact)body.fact=fact;
  if(+v.importance!==r.importance)body.importance=+v.importance;
  if((v.core==="1")!==!!r.core)body.core=v.core==="1";
  if((v.ts||"").trim()&&(v.ts||"").trim()!==(r.ts||"").slice(0,10))body.ts=(v.ts||"").trim();
  if(Object.keys(body).length===1)throw new Error("Nothing was changed.");
  await api("/api/facts/edit",body);result=body});
 if(!v)return;
 if(!r){load();toast("Fact added",async()=>{await api("/api/delete",{kind:"facts",id:result.id});load()})}
 else{const old={id:r.id,fact:r.fact,importance:r.importance,core:!!r.core,ts:(r.ts||"").slice(0,19)},undo={id:r.id};for(const k of Object.keys(result))if(k!=="id")undo[k]=old[k];
  load();toast("Fact updated",async()=>{await api("/api/facts/edit",undo);load()})}
}
window.renderFacts=renderFacts;window.factForm=factForm;window.fx=fx;
})();
