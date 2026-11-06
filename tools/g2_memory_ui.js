/* The Facts tab of the review page (inserted into tools/g2_review.py's page at start-up): where each fact came from, how often G2 was given and used it, filters and sorting, and one form to add or edit a fact. */
(function(){
const SRC={told:"told in conversation",hand:"added by hand",goal_lesson:"goal lesson",reflection:"inferred (reflection)"};
const srcName=s=>SRC[s]||s||"unknown";
const OFTEN=20;                                   // shown to G2 this many times and never mentioned: worth a look
const fx={source:"all",core:false,unused:false,low:false,often:false,sort:"newest",tidy:false};
let tidy=null,tidyFor=null;
let info={core_max:12},infoAsked=false;
const used=r=>Math.max(r.declared||0,r.matched||0);
const given=r=>r.injected||0;
const flagged=r=>given(r)>=OFTEN&&used(r)===0;
const nice=d=>{if(!d)return "";const m=/^(\d{4})-(\d\d)-(\d\d)/.exec(d);if(!m)return d;const mo=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];return mo[+m[2]-1]+" "+(+m[3])};
const waiting=id=>((window.reviewState&&window.reviewState.pending)||[]).filter(p=>new RegExp("fact #"+id+"(\\D|$)").test(p.text||""));
const SORTS={newest:["Newest first",(a,b)=>b.id-a.id],importance:["Most important first (5 down to 1)",(a,b)=>b.importance-a.importance||b.id-a.id],
 lastused:["Mentioned most recently",(a,b)=>(b.last_used||"").localeCompare(a.last_used||"")||b.id-a.id],mostused:["Mentioned most",(a,b)=>used(b)-used(a)||given(b)-given(a)],mostgiven:["Shown to G2 most",(a,b)=>given(b)-given(a)]};

function renderFacts(list,f){
 if(!infoAsked){infoAsked=true;api("/api/facts/info").then(i=>{info=i;render()}).catch(()=>{})}
 const all=data||[],g2btn=window.g2btn;
 ensureTidy();
 const cores=all.filter(r=>r.core).length,srcs={};for(const r of all)srcs[r.source||"unknown"]=(srcs[r.source||"unknown"]||0)+1;
 const nOften=all.filter(flagged).length,nUnused=all.filter(r=>used(r)===0).length,nLow=all.filter(r=>r.importance<=2).length;
 // summary and filters
 const box=el("div","labelsum");
 box.append(el("b","",all.length+(all.length===1?" fact":" facts")+" · core "+cores+" of "+info.core_max),
  el("div","sub","Importance runs from 1 (rarely matters) to 5 (essential): 5 is the most important. Core facts are always shown to G2, most important first, up to "+info.core_max+". “Shown” is how many times a fact was put in front of G2 while he was working out a reply; “mentioned” is how many times he then named it or his reply repeated it."));
 const row1=el("div");row1.style.marginTop="6px";row1.append(el("span","meta","Where it came from: "));
 row1.append(g2btn("All",()=>{fx.source="all";render()},fx.source==="all"?"on":""));
 for(const k of Object.keys(srcs).sort())row1.append(g2btn(srcName(k)+" ("+srcs[k]+")",()=>{fx.source=k;render()},fx.source===k?"on":""));
 const row2=el("div");row2.style.marginTop="4px";
 const tog=(key,label,n)=>row2.append(g2btn(label+(n===undefined?"":" ("+n+")"),()=>{fx[key]=!fx[key];render()},fx[key]?"on":""));
 tog("core","Core only",cores);tog("unused","Never mentioned",nUnused);tog("often","Shown often, never mentioned",nOften);tog("low","Low importance (1 or 2)",nLow);
 const sel=el("select");for(const k of Object.keys(SORTS)){const o=el("option","",SORTS[k][0]);o.value=k;sel.append(o)}sel.value=fx.sort;sel.onchange=()=>{fx.sort=sel.value;render()};sel.style.marginLeft="8px";row2.append(el("span","meta","Sort: "),sel);
 if(fx.source!=="all"||fx.core||fx.unused||fx.low||fx.often||fx.sort!=="newest")row2.append(g2btn("Clear",()=>{Object.assign(fx,{source:"all",core:false,unused:false,low:false,often:false,sort:"newest"});render()}));
 const tb=g2btn(fx.tidy?"Back to the list":"Tidy up",()=>{fx.tidy=!fx.tidy;render()},fx.tidy?"on":"");tb.title="Possible duplicates, facts that name a date or time, and facts G2 is shown but never mentions";tb.style.marginLeft="8px";row2.append(tb);
 box.append(row1,row2);list.append(box);
 suggestionsPanel(list,all);
 if(fx.tidy){renderTidy(list,all);return}

 let items=all.filter(r=>(fx.source==="all"||(r.source||"unknown")===fx.source)&&(!fx.core||r.core)&&(!fx.unused||used(r)===0)&&(!fx.low||r.importance<=2)&&(!fx.often||flagged(r))&&(!f||JSON.stringify(r).toLowerCase().includes(f)));
 items=items.slice().sort(SORTS[fx.sort][1]);
 if(!items.length){list.append(el("div","empty",all.length?"No fact matches these filters.":"Nothing here."));return}
 list.append(el("div","meta","Showing "+items.length+" of "+all.length));
 for(const r of items){
  const row=el("div","row"),main=el("div","main");
  main.append(el("div","",r.fact));
  const meta=el("div","meta","#"+r.id+" · "+nice(r.ts)+" · ");
  const sc=el("span","gchip",srcName(r.source));meta.append(sc,document.createTextNode("importance "+r.importance+" of 5"));
  if(r.core)meta.append(el("span","gchip ok","core"));
  main.append(meta);
  const u=el("div","meta");
  if(r.injected===undefined)u.textContent="No usage data in this copy.";
  else if(!given(r))u.textContent="Not shown to G2 yet.";
  else u.textContent="Shown to G2 "+given(r)+" times · mentioned "+used(r)+" times"+(used(r)?" (he named it "+(r.declared||0)+", his reply repeated it "+(r.matched||0)+")":"")+(r.last_used?" · last mentioned "+nice(r.last_used):"");
  main.append(u);
  if(flagged(r)){const w=el("div","meta","G2 was shown this fact "+given(r)+" times and never mentioned it. It may be worded too vaguely for him to use, or not be worth keeping.");w.style.color="var(--x)";main.append(w)}
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
 const m=el("div","meta","#"+r.id+" \u00b7 "+nice(r.ts)+" \u00b7 "+srcName(r.source)+" \u00b7 importance "+r.importance+" of 5"+(r.core?" \u00b7 core":"")+" \u00b7 shown "+(r.injected||0)+"\u00d7, mentioned "+used(r)+"\u00d7");d.append(m);return d}
function tidySection(list,title,items,empty,draw){const sf=fold(title+" ("+items.length+")",items.length>0);if(!items.length)sf.append(el("div","meta",empty));else for(const it of items)sf.append(draw(it));list.append(sf)}
function ensureTidy(){if(tidyFor!==data){tidyFor=data;tidy=null;api("/api/facts/tidy").then(t=>{tidy=t;render()}).catch(e=>{tidy={error:e.message};render()})}}
function renderTidy(list,all){
 const g2btn=window.g2btn;
 ensureTidy();
 if(!tidy){list.append(el("div","empty","Looking for things to tidy\u2026"));return}
 if(tidy.error){list.append(el("div","empty","Could not check: "+tidy.error));return}
 const hide=ign();
 const dups=tidy.duplicates.filter(p=>!hide.has("dup:"+p.a.id+"-"+p.b.id)),dated=tidy.dated.filter(r=>!hide.has("date:"+r.id));
 const dead=all.filter(flagged),cores=all.filter(r=>r.core).sort((a,b)=>b.importance-a.importance||b.id-a.id),extra=cores.slice(info.core_max);
 const total=dups.length+dated.length+tidy.look_like.length+dead.length+extra.length;
 list.append(el("div","meta",total?total+" thing"+(total===1?"":"s")+" to look at. Nothing is changed until you press a button; deleted facts go to the Trash with an Undo.":"Nothing to tidy: no near-duplicates, no dated facts, nothing shown but never mentioned."));
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
 tidySection(list,"Shown often and never mentioned",dead,"None.",r=>{
  const row=el("div","row"),main=el("div","main");main.append(miniFact(r));
  const act=el("div");act.style.marginTop="6px";act.append(g2btn("Edit",()=>factForm(r)),g2btn("Delete",()=>delFact(r),"danger"));main.append(act);row.append(main);return row});
 tidySection(list,"Core facts G2 is not given (over the limit of "+info.core_max+")",extra,"All core facts fit.",r=>{
  const row=el("div","row"),main=el("div","main");main.append(miniFact(r),el("div","meta","Only the "+info.core_max+" most important core facts are given every time."));
  const act=el("div");act.style.marginTop="6px";act.append(g2btn("Make not core",async()=>{try{await api("/api/facts/edit",{id:r.id,core:false});tidyFor=null;load()}catch(x){toast("Failed: "+x.message)}}),g2btn("Raise importance",()=>factForm(r)));main.append(act);row.append(main);return row});
}

// ---- suggested clean-up (user, 2026-11-06): the page works out which facts to delete or stop giving G2 every time, with the reason, and one button accepts them all.
// Local rules only (no API call). Nothing is changed until the button is pressed; deleted facts go to the Trash with an Undo.
const sugIgn=()=>{try{return new Set(JSON.parse(localStorage.getItem("g2SuggestIgnore")||"[]"))}catch(e){return new Set()}};
const addSugIgn=k=>{try{const s=sugIgn();s.add(k);localStorage.setItem("g2SuggestIgnore",JSON.stringify([...s]))}catch(e){}};
const worth=r=>[r.core?1:0,r.importance||0,used(r),given(r)-0,r.id];                 // which of two near-duplicates to keep: core, importance, mentioned, then the newer
const better=(a,b)=>{const x=worth(a),y=worth(b);for(let i=0;i<x.length;i++){if(x[i]!==y[i])return x[i]>y[i]}return a.id>b.id};
function suggestions(all){
 if(!tidy||tidy.error)return null;
 const byId=new Map(all.map(r=>[r.id,r])),out=new Map(),hide=sugIgn();
 const add=(r,act,why)=>{if(!r||out.has(r.id)||hide.has(act+":"+r.id))return;out.set(r.id,{id:r.id,act,why,fact:r})};
 for(const p of tidy.duplicates||[]){const a=byId.get(p.a.id),b=byId.get(p.b.id);if(!a||!b||out.has(a.id)||out.has(b.id))continue;const keep=better(a,b)?a:b,drop=keep===a?b:a;
  if(!drop.core)add(drop,"delete","Says nearly the same as #"+keep.id+" ("+Math.round(p.score*100)+"% of the words match), which is kept.")}
 for(const r of tidy.dated||[])if(!r.core&&(byId.get(r.id)||{}).importance<=3)add(byId.get(r.id),"delete","Names a date or time: a fact should stay true, not log when something happened.");
 const looks=(tidy.look_like||[]).map(r=>byId.get(r.id)).filter(Boolean).sort((a,b)=>b.id-a.id);for(const r of looks.slice(1))add(r,"delete","An older “I look like…” description: only the newest one counts.");
 for(const r of all)if(flagged(r)&&!r.core&&r.importance<=3)add(r,"delete","G2 was shown it "+given(r)+" times and never mentioned it, and it is not marked important.");
 const cores=all.filter(r=>r.core).sort((a,b)=>b.importance-a.importance||b.id-a.id);for(const r of cores.slice(info.core_max))add(r,"uncore","More core facts than G2 is shown ("+info.core_max+"): this one is beyond the limit.");
 return [...out.values()].sort((a,b)=>(a.act===b.act?0:a.act==="delete"?-1:1)||a.id-b.id)}
async function acceptSuggestions(list){
 const done=[];let failed=0;
 for(const s of list){try{if(s.act==="delete"){const t=await api("/api/delete",{kind:"facts",id:s.id});done.push({s,trash:t.trash_id})}else{await api("/api/facts/edit",{id:s.id,core:false});done.push({s})}}catch(x){failed++}}
 tidyFor=null;load();
 toast("Done: "+done.filter(d=>d.s.act==="delete").length+" deleted, "+done.filter(d=>d.s.act==="uncore").length+" no longer core"+(failed?"; "+failed+" failed":"")+". Deleted facts are in the Trash.",async()=>{
  for(const d of done){try{if(d.trash)await api("/api/restore",{trash_id:d.trash});else await api("/api/facts/edit",{id:d.s.id,core:true})}catch(x){}}tidyFor=null;load()})}
function suggestionsPanel(list,all){
 const g2btn=window.g2btn,sug=suggestions(all);
 const box=el("div","labelsum");box.style.borderColor="#7fb069";
 if(sug===null){box.append(el("div","meta","Working out suggested clean-ups\u2026"));list.append(box);return}
 if(!sug.length){box.append(el("b","","Suggested clean-up: nothing to do."),el("div","sub","No near-duplicates, dated facts or facts G2 is shown and never mentions."));list.append(box);return}
 const nd=sug.filter(s=>s.act==="delete").length,nu=sug.length-nd;
 box.append(el("b","","Suggested clean-up: "+(nd?nd+" to delete":"")+(nd&&nu?", ":"")+(nu?nu+" to stop giving G2 every time":"")));
 box.append(el("div","sub","Worked out on this Mac from how often G2 mentions each fact, duplicates and dates. Nothing changes until you accept; deleted facts go to the Trash and the toast has an Undo. Skip any you want to keep."));
 const row=el("div");row.style.margin="6px 0";
 const acc=g2btn("Accept all "+sug.length+" suggestions",()=>{if(confirm("Apply all "+sug.length+" suggestions? Deleted facts go to the Trash.")){acceptSuggestions(sug)}},"on");row.append(acc);box.append(row);
 const fl=fold("Show the "+sug.length+" suggestions",sug.length<=6);
 for(const s of sug){const r=el("div","meta");const chip=el("span","gchip "+(s.act==="delete"?"":"pend"),s.act==="delete"?"delete":"not core");r.append(chip,document.createTextNode(" #"+s.id+" \u201c"+s.fact.fact+"\u201d \u2014 "+s.why+" "));
  r.append(g2btn("Skip",()=>{addSugIgn(s.act+":"+s.id);render()}));fl.append(r)}
 box.append(fl);list.append(box)}

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
window.g2suggestFor=(all,t,i)=>{tidy=t;if(i)info=i;return suggestions(all)};window.renderFacts=renderFacts;window.factForm=factForm;window.fx=fx;
})();
