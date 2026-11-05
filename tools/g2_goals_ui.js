/* The Goals tab of the review page (inserted into tools/g2_review.py's page at start-up). Every edit is queued on the Mac (/api/goals/edit) and applied to the Pi later. */
(function(){
const st=document.createElement("style");st.textContent=`
.gtile{display:inline-block;min-width:104px;margin:0 8px 8px 0;padding:6px 10px;background:var(--surface);border:1px solid var(--line);border-radius:8px;vertical-align:top}
.gtile b{display:block;font-size:1.15rem}.gtile span{color:var(--muted);font-size:.74rem}
.gtbl{width:100%;border-collapse:collapse;font-size:.86rem;background:var(--surface);border:1px solid var(--line);border-radius:8px}
.gtbl th{text-align:left;color:var(--muted);font-weight:600;font-size:.74rem;padding:5px 8px;border-bottom:1px solid var(--line)}
.gtbl td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}.gtbl tr:last-child td{border-bottom:0}
.gbar{display:inline-block;width:70px;height:7px;background:var(--line);border-radius:4px;vertical-align:middle;margin-right:4px;overflow:hidden}.gbar i{display:block;height:100%;background:var(--ok)}
.gchip{display:inline-block;border-radius:10px;padding:0 8px;font-size:.74rem;border:1px solid var(--line);margin-right:4px}
.gchip.ok{color:var(--ok);border-color:var(--ok)}.gchip.bad{color:var(--x);border-color:var(--x)}.gchip.pend{background:#fff3c4;color:#6b5200;border-color:#e0c15a}
.gb{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:5px;padding:1px 8px;font-size:.78rem;margin:1px 3px 1px 0}.gb.danger{color:var(--x);border-color:var(--x)}.gb.on{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.gwarn{background:#fff3c4;color:#6b5200;border:1px solid #e0c15a;border-radius:8px;padding:8px 12px;margin:8px 0}
.gmodal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:50}
.gmodal form{background:var(--surface);color:var(--ink);border-radius:10px;padding:16px 18px;width:min(460px,92vw);max-height:88vh;overflow:auto}
.gmodal label{display:block;margin:8px 0 2px;font-size:.84rem;color:var(--ink2)}.gmodal input,.gmodal select,.gmodal textarea{width:100%;box-sizing:border-box;font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.gmodal .hint{color:var(--muted);font-size:.76rem}
`;document.head.append(st);

const G={}; // per-goal view state: {result, cond}
const COND_LABEL=c=>[c.attachment,c.floor,c.hw].filter(Boolean).join(" · ");
const pendingOps=()=>(data&&data.pending)||[];
const pend=(goal,pred)=>pendingOps().filter(p=>(p.goal===goal||p.goal===undefined)&&pred(p));
function pendChip(text){const c=el("span","gchip pend","pending");c.title=text||"Queued on this Mac; it applies to G2 on the next sync";return c}
function btn(text,fn,cls){const b=el("button","gb"+(cls?" "+cls:""),text);b.onclick=fn;return b}

// ---- a small form dialog: fields [{key,label,type,value,options,hint,min,max,step}] -> resolves to {key:value} or null
function ask(title,fields,okText,submit){return new Promise(res=>{
 const m=el("div","gmodal"),fm=el("form");fm.append(el("h3","",title));fm.querySelector("h3").style.margin="0 0 6px";const ins={};
 for(const f of fields){const lb=el("label","",f.label);let i;
  if(f.type==="select"){i=el("select");for(const o of f.options){const op=el("option","",o.label!==undefined?o.label:String(o));op.value=o.value!==undefined?o.value:o;i.append(op)}i.value=String(f.value)}
  else if(f.type==="textarea"){i=el("textarea");i.rows=3;i.value=f.value||""}
  else{i=el("input");i.type=f.type||"text";i.value=f.value===undefined||f.value===null?"":f.value;if(f.min!==undefined)i.min=f.min;if(f.max!==undefined)i.max=f.max;if(f.step!==undefined)i.step=f.step}
  ins[f.key]=i;lb.append(i);fm.append(lb);if(f.hint)fm.append(el("div","hint",f.hint))}
 const err=el("div","hint");err.style.cssText="color:var(--x);margin-top:8px;display:none";fm.append(err);
 const row=el("div");row.style.cssText="margin-top:14px;display:flex;gap:8px;justify-content:flex-end";
 const no=el("button","btn","Cancel");no.type="button";const ok=el("button","btn",okText||"Queue it");ok.type="submit";ok.style.cssText="background:var(--accent);color:var(--bg);border-color:var(--accent)";
 row.append(no,ok);fm.append(row);m.append(fm);document.body.append(m);const first=fm.querySelector("input,select,textarea");if(first)first.focus();
 const done=v=>{m.remove();res(v)};no.onclick=()=>done(null);m.onclick=e=>{if(e.target===m)done(null)};
 fm.onsubmit=async e=>{e.preventDefault();const out={};for(const f of fields){let v=ins[f.key].value;if(f.type==="number")v=v===""?null:Number(v);out[f.key]=v}
  if(submit){ok.disabled=true;try{await submit(out)}catch(x){err.textContent=x.message;err.style.display="";ok.disabled=false;return}}done(out)}})}      // with a `submit`, a refusal is shown in the form and the form stays open

async function queue(op,what){try{const r=await api("/api/goals/edit",op);data.pending=r.pending;render();toast("Queued: "+(what||"edit")+" (applies on the next sync)",async()=>{await api("/api/goals/cancel",{id:r.id});load()})}catch(e){toast("Not queued: "+e.message)}}
async function confirmThen(msg,fn){const v=await ask(msg,[],"Yes, queue it");if(v)fn()}

function valueField(k,value,label){
 if(k.kind==="choice")return {key:"value",label:label||"Value",type:"select",options:k.options,value:value===undefined||value===null?k.options[0]:value};
 if(k.kind==="bool")return {key:"value",label:label||"Value",type:"select",options:["true","false"],value:String(value)};
 return {key:"value",label:label||"Value",type:"number",value:value,min:k.lo,max:k.hi,step:k.step||"any",hint:"Allowed: "+k.lo+" to "+k.hi+(k.unit?" "+k.unit:"")}}
function scopeOptions(g){const s=new Set(["all"]);for(const c of g.conditions_seen||[]){const o=JSON.parse(c);if(o.attachment&&o.floor)s.add("attachment="+o.attachment+"|floor="+o.floor);if(o.floor)s.add("floor="+o.floor);if(o.attachment)s.add("attachment="+o.attachment)}
 return [...s].map(v=>({value:v,label:v==="all"?"Everywhere (every attachment and floor)":v}))}
const scopeField=g=>({key:"scope",label:"Applies to",type:"select",options:scopeOptions(g),value:"all"});

// ---- the page
function renderGoals(list,f){const d=data;if(!d||!d.goals){list.append(el("div","empty","No goal data."));return}
 const m=d.memory||{};const sum=el("div","labelsum");
 sum.append(el("b","","Goal data copied from the Pi: "),document.createTextNode(d.pulled||"never"));
 if(d.pulled_age_h===null||d.pulled_age_h>24){const w=el("div","gwarn",d.pulled_age_h===null?"This copy has no date, so it may be old.":"This copy is "+Math.round(d.pulled_age_h)+" hours old; what you see may not match G2. It refreshes when the Pi is reachable (g2goal pull).");sum.append(w)}
 if(m.lowest_mb!==undefined)sum.append(el("div","sub","Pi memory: lowest available "+Math.round(m.lowest_mb)+" MB ("+m.when+"), swap up to "+Math.round(m.swap_mb)+" MB"+(m.oom_kills?", OOM KILLS: "+m.oom_kills:"")));
 const cur=(d.curation||"").split("\n").filter(x=>x.startsWith("- "));if(cur.length){const fl=fold("Curation notes ("+cur.length+")",false);for(const c of cur)fl.append(el("div","meta",c.slice(2)));sum.append(fl)}
 list.append(sum);

 // waiting edits
 const pe=d.pending||[];
 if(pe.length){const box=el("div","labelsum");box.style.borderColor="#e0c15a";box.append(el("b","",pe.length+(pe.length===1?" edit is":" edits are")+" waiting to be sent to G2"));
  box.append(el("div","sub","They are kept on this Mac and sent when the Pi is up and no goal session is running (on g2goal pull, g2goal run or the button below)."));
  for(const p of pe){const r=el("div","meta",p.text);if(p.error){const e=el("div","meta","Last try failed: "+p.error);e.style.color="var(--x)";r.append(e)}
   r.append(btn("Cancel",async()=>{try{const x=await api("/api/goals/cancel",{id:p.id});d.pending=x.pending;render()}catch(e){toast("Failed: "+e.message)}},"danger"));box.append(r)}
  box.append(btn("Apply now",async()=>{toast("Sending to G2…");try{const x=await api("/api/goals/apply",{});toast(x.message);load()}catch(e){toast("Failed: "+e.message)}},"on"));list.append(box)}
 else if((d.edit_history||[]).length){const h=d.edit_history[0];const b=el("div","sub","Last edit sent to G2: "+h.text+" ("+h.time+")"+(h.ok?"":" — failed"));b.style.margin="6px 0";list.append(b)}

 // toolbar: new goal, order
 const bar=el("div");bar.style.margin="8px 0";
 bar.append(el("button","btn","Add a goal"));bar.firstChild.onclick=()=>addGoal();
 if((d.priority||[]).length>1){const o=el("span","meta","  Order (highest first): ");d.priority.forEach((gid,i)=>{const g=d.goals.find(x=>x.id===gid);o.append(document.createTextNode((i?" > ":"")+(g?g.title:gid)));
   if(i>0)o.append(btn("↑",()=>{const a=[...d.priority];[a[i-1],a[i]]=[a[i],a[i-1]];queue({op:"priority",order:a},"goal order")}));if(i<d.priority.length-1)o.append(btn("↓",()=>{const a=[...d.priority];[a[i+1],a[i]]=[a[i],a[i+1]];queue({op:"priority",order:a},"goal order")}))});
  if(pend(undefined,p=>p.op==="priority").length)o.append(pendChip());bar.append(o)}
 if(d.goals.length>1){const all=v=>()=>{for(const g of d.goals)setGoalOpen(g.id,v);render()};bar.append(btn("Collapse all",all(false)),btn("Expand all",all(true)))}
 list.append(bar);

 // suggestions
 if((d.suggestions||[]).length){const sf=fold("G2 suggests a change ("+d.suggestions.length+")",true);for(const s of d.suggestions){const r=el("div","row"),mn=el("div","main");mn.append(el("div","",s.text),el("div","meta",s.goal+" · "+s.status));
   const q=pend(s.goal,p=>(p.op==="confirm"||p.op==="cancel")&&p.knob===s.knob);if(q.length)mn.append(pendChip(q[0].text));else{mn.append(btn("Confirm",()=>queue({op:"confirm",goal:s.goal,knob:s.knob},"confirm "+s.knob),"on"),btn("Cancel it",()=>queue({op:"cancel",goal:s.goal,knob:s.knob},"cancel the suggestion for "+s.knob)))}
   r.append(mn);sf.append(r)}list.append(sf)}

 d.goals.forEach((g,i)=>goalCard(list,g,f,i));

 const t=d.turns||{};const tf=fold("Turns in the last "+t.days+" days ("+(t.count||0)+")",false);for(const c of (t.causes||[]))tf.append(el("div","meta",c.n+" × "+c.cause));for(const r of (t.recent||[]))tf.append(el("div","meta",r.time+" · "+r.kind+" "+(r.direction||"")+" "+(r.degrees||"")+"° · "+r.why+(r.ball?" · ball "+Math.round(r.ball)+" in at "+Math.round(r.ball_deg)+"°":"")+(r.wall_in?" · wall reading "+r.wall_in+" in":"")));list.append(tf);
 if((d.other_lessons||[]).length){const of=fold("Other lessons ("+d.other_lessons.length+")",false);for(const l of d.other_lessons)of.append(el("div","meta","#"+l.id+" · "+l.time+": "+l.text));list.append(of)}
 if((d.edit_history||[]).length){const hf=fold("Edits sent to G2 ("+d.edit_history.length+")",false);for(const h of d.edit_history)hf.append(el("div","meta",h.time+" · "+(h.ok?"done":"FAILED")+" · "+h.text+(h.ok?"":" — "+h.answer)));list.append(hf)}
}

function goalOpen(id,i){try{const m=JSON.parse(localStorage.getItem("g2GoalOpen")||"{}");if(id in m)return !!m[id]}catch(e){}return i===0}
function setGoalOpen(id,v){try{const m=JSON.parse(localStorage.getItem("g2GoalOpen")||"{}");m[id]=!!v;localStorage.setItem("g2GoalOpen",JSON.stringify(m))}catch(e){}}
function goalCard(parent,g,f,idx){
 const list=el("div"),df=g.definition||{},rate=g.counted?Math.round(100*g.successes/g.counted):null;
 const open0=goalOpen(g.id,idx),hd=el("div","divider");hd.style.cursor="pointer";hd.setAttribute("role","button");hd.tabIndex=0;
 const lastS=(g.sessions||[])[0],gist=(rate===null?"no counted attempts yet":rate+"% of "+g.counted)+(lastS?" \u00b7 last session "+lastS.successes+" of "+lastS.attempts:"");
 const pc=pendingOps().filter(p=>p.goal===g.id).length;
 const paint=()=>{const o=list.style.display!=="none";hd.textContent=(o?"\u25BE ":"\u25B8 ")+g.title+(g.kind==="standing"?" \u00b7 always on":"");if(!o){const sp=el("span","","  \u2014  "+gist+(pc?" \u00b7 "+pc+" edit"+(pc>1?"s":"")+" waiting":""));sp.style.cssText="text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted)";hd.append(sp)}hd.setAttribute("aria-expanded",o)};
 list.style.display=open0?"":"none";
 const flip=()=>{list.style.display=list.style.display==="none"?"":"none";setGoalOpen(g.id,list.style.display!=="none");paint()};
 hd.onclick=flip;hd.onkeydown=ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();flip()}};
 paint();parent.append(hd,list);
 // summary strip
 const strip=el("div");strip.style.margin="8px 0 2px";
 const tile=(big,small,tip)=>{const t=el("div","gtile");t.append(el("b","",big),el("span","",small));if(tip)t.title=tip;strip.append(t)};
 tile(rate===null?"—":rate+"%","success ("+g.successes+" of "+g.counted+" counted)");
 const last=(g.sessions||[])[0];tile(last?last.successes+" of "+last.attempts:"—","last session"+(last?" · "+last.time:""),last?"ended: "+last.why:"");
 const focus=(g.learned||[]).find(k=>k.focus);tile(focus?focus.setting:"—","working on"+(focus?" (now "+focus.now+")":""));
 if(g.kind!=="standing"){tile((df.min_pack_pct??"?")+"%","pack needed to start");tile((df.attempts??"?")+" · "+(df.minutes??"?")+" min","attempts · time per session")}
 list.append(strip);
 if(g.trend&&g.trend.length){const W=30,H=40,svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("width",g.trend.length*W);svg.setAttribute("height",H+14);svg.style.cssText="display:block;margin:4px 0 6px";
  g.trend.forEach((t,i)=>{const h=t.rate===null?2:Math.max(2,Math.round(t.rate*H));const r=document.createElementNS(svg.namespaceURI,"rect");r.setAttribute("x",i*W+4);r.setAttribute("y",H-h);r.setAttribute("width",W-8);r.setAttribute("height",h);r.setAttribute("rx",2);r.style.fill=t.rate===null?"var(--muted)":(t.rate>=.5?"var(--ok)":"var(--x)");
   const tt=document.createElementNS(svg.namespaceURI,"title");tt.textContent=t.session+": "+t.successes+" of "+t.attempts+" good";r.append(tt);svg.append(r);
   const tx=document.createElementNS(svg.namespaceURI,"text");tx.setAttribute("x",i*W+W/2);tx.setAttribute("y",H+11);tx.setAttribute("text-anchor","middle");tx.setAttribute("font-size","9");tx.style.fill="var(--muted)";tx.textContent=t.successes+"/"+t.attempts;svg.append(tx)});
  const cap=el("div","meta","Success per session, oldest to newest (hover for the date)");list.append(svg,cap)}
 const acts=el("div");acts.style.margin="6px 0";
 acts.append(btn("Edit goal",()=>editGoal(g)),btn("Forget what it learned",()=>confirmThen("Forget everything “"+g.title+"” learned? The journal of attempts is kept; its learned values start again.",()=>queue({op:"reset",goal:g.id},"forget what "+g.title+" learned")),"danger"));
 const pr=pend(g.id,p=>p.op==="set"||p.op==="reset");if(pr.length)acts.append(pendChip(pr.map(p=>p.text).join("; ")));list.append(acts);

 // definition
 const dfd=fold("How this goal is set up",false);const rows=[["Attempts per session",df.attempts],["Time limit",(df.minutes??"?")+" min"],["Starts only above",(df.min_pack_pct??"?")+"% pack"],["Ends early after",df.target_successes?df.target_successes+" successes":"never (uses every attempt)"],["Rest between attempts",(df.rest_between_s??"?")+" s"],["Start phrases",(df.start_words||[]).map(w=>"G2, "+w).join(" · ")||"(none)"]];
 if(g.kind==="standing")dfd.append(el("div","meta","A standing goal has no start or end: every encounter in any activity counts as an attempt."));
 const dt=el("table","gtbl");for(const [a,b] of rows){const tr=el("tr");tr.append(el("td","",a),el("td","",String(b)));dt.append(tr)}dfd.append(dt);list.append(dfd);

 settingsTable(list,g);
 overridesList(list,g);
 lessonsList(list,g,f);
 attemptsTable(list,g,f);
 const sess=fold("Sessions ("+g.sessions.length+")",false);for(const s of g.sessions){sess.append(el("div","meta",s.time+" · "+s.successes+" of "+s.attempts+" good · "+(s.minutes||0).toFixed(1)+" min · ended: "+s.why))}list.append(sess);
}

function settingsTable(list,g){
 const knobs=(g.definition&&g.definition.knobs)||[];const learned={};for(const k of g.learned||[])learned[k.setting]=k;
 const now=Object.assign({},g.settings_now||{});for(const k of g.learned||[])if(k.now!==undefined&&k.now!==null)now[k.setting]=k.now;
 const ovr=g.override_rows||[];
 const isInPlay=k=>ovr.some(o=>o.knob===k.name&&o.kind!=="banned")||!!learned[k.name]||pend(g.id,p=>p.knob===k.name).length>0;
 const inPlay=knobs.filter(isInPlay),rest=knobs.filter(k=>!isInPlay(k));
 inPlay.sort((a,b)=>((learned[b.name]||{}).focus?1:0)-((learned[a.name]||{}).focus?1:0)||a.name.localeCompare(b.name));
 const mk=(arr,title,open)=>{const sf=fold(title+" ("+arr.length+")",open);if(!arr.length){sf.append(el("div","empty","None."));return sf}
  const t=el("table","gtbl"),h=el("tr");for(const x of ["Setting","In use","Who changes it","What G2 tried (good of tries)",""])h.append(el("th","",x));t.append(h);
  for(const k of arr){const tr=el("tr"),L=learned[k.name];const c1=el("td");c1.append(el("div","",(L&&L.focus?"★ ":"")+k.label),el("div","meta",k.name));
   const pin=ovr.find(o=>o.kind==="pin"&&o.knob===k.name),lim=ovr.find(o=>o.kind==="limit"&&o.knob===k.name);
   const c2=el("td","",now[k.name]===undefined?"—":String(now[k.name])+(k.unit?" "+k.unit:""));if(pin)c2.append(el("div","gchip ok","pinned "+pin.value+(pin.scope!=="all"?" · "+pin.scope:"")));if(lim)c2.append(el("div","gchip ok","limit "+lim.lo+" to "+lim.hi));
   const c3=el("td");const sel=el("select");for(const o of ["free","ask","fixed"]){const op=el("option","",o==="free"?"G2 (free)":o==="ask"?"You, G2 suggests (ask)":"You (fixed)");op.value=o;sel.append(op)}
   const pc=pend(g.id,p=>p.op==="set"&&p.controls&&p.controls[k.name]);sel.value=pc.length?pc[0].controls[k.name]:k.control;sel.onchange=()=>queue({op:"set",goal:g.id,controls:{[k.name]:sel.value}},k.label+" is changed by "+sel.value);c3.append(sel);if(pc.length)c3.append(pendChip());
   const c4=el("td");if(L)for(const t2 of L.tried){const w=el("div","meta");const b=el("span","gbar"),i=el("i");i.style.width=(t2.tries?100*t2.good/t2.tries:0)+"%";b.append(i);w.append(b,document.createTextNode(t2.value+" ("+t2.good+" of "+t2.tries+")"));c4.append(w)}else c4.append(el("span","meta","not tried"));
   const c5=el("td");const pq=pend(g.id,p=>p.knob===k.name&&["pin","unpin","limit","unlimit","forget","undo"].includes(p.op));
   c5.append(btn(pin?"Change pin":"Pin",async()=>{const v=await ask("Pin "+k.label,[valueField(k,pin?pin.value:now[k.name]),scopeField(g)],"Queue pin");if(v)queue({op:"pin",goal:g.id,knob:k.name,value:v.value,scope:v.scope},"pin "+k.name+" = "+v.value)}));
   if(k.kind==="float"||k.kind==="int")c5.append(btn(lim?"Change limit":"Limit",async()=>{const v=await ask("Limit "+k.label,[{key:"lo",label:"Lowest G2 may use",type:"number",value:lim?lim.lo:k.lo,min:k.lo,max:k.hi,step:k.step||"any"},{key:"hi",label:"Highest G2 may use",type:"number",value:lim?lim.hi:k.hi,min:k.lo,max:k.hi,step:k.step||"any",hint:"Allowed: "+k.lo+" to "+k.hi+(k.unit?" "+k.unit:"")},scopeField(g)],"Queue limit");if(v)queue({op:"limit",goal:g.id,knob:k.name,lo:v.lo,hi:v.hi,scope:v.scope},"limit "+k.name)}));
   if(L){c5.append(btn("Undo what he chose",()=>confirmThen("Ban the value G2 settled on for “"+k.label+"” and go back to the next best?",()=>queue({op:"undo",goal:g.id,knob:k.name},"undo the learned value of "+k.name))));
    c5.append(btn("Forget",()=>confirmThen("Forget everything G2 learned about “"+k.label+"”? It goes back to your value.",()=>queue({op:"forget",goal:g.id,knob:k.name},"forget what was learned for "+k.name)),"danger"))}
   if(pq.length)c5.append(pendChip(pq.map(p=>p.text).join("; ")));
   tr.append(c1,c2,c3,c4,c5);t.append(tr)}
  sf.append(t);return sf};
 list.append(mk(inPlay,"Settings in play: tried, pinned or limited",true));list.append(mk(rest,"Other settings",false));
}

function overridesList(list,g){
 const ovr=g.override_rows||[];if(!ovr.length)return;const of=fold("Your overrides ("+ovr.length+")",true);
 for(const o of ovr){const r=el("div","row"),mn=el("div","main");
  const text=o.kind==="pin"?"Pinned "+o.knob+" = "+o.value:o.kind==="limit"?"Limit "+o.knob+": "+o.lo+" to "+o.hi:"Undone value of "+o.knob+": "+o.value+" (G2 will not use it)";
  mn.append(el("div","",text),el("div","meta","Applies to: "+(o.scope==="all"?"everywhere":o.scope)));
  const op=o.kind==="pin"?"unpin":o.kind==="limit"?"unlimit":"unban";const q=pend(g.id,p=>p.knob===o.knob&&["unpin","unlimit","unban"].includes(p.op));
  if(q.length)mn.append(pendChip(q[0].text));else r.append(btn(o.kind==="banned"?"Allow again":"Remove",()=>queue({op,goal:g.id,knob:o.knob,value:o.kind==="banned"?o.value:undefined,scope:o.scope},op+" "+o.knob),"danger"));
  r.prepend(mn);of.append(r)}list.append(of)}

function lessonsList(list,g,f){
 const les=g.lessons.filter(l=>!f||l.text.toLowerCase().includes(f));const lf=fold("What G2 learned ("+les.length+")",true);
 lf.append(btn("Add a lesson",async()=>{const v=await ask("Add a lesson for "+g.title,[{key:"text",label:"What G2 should remember",type:"textarea",hint:"Write it the way the saved ones read. A note naming a date or time is refused."}],"Queue lesson");if(v&&v.text)queue({op:"lesson_add",text:g.title+": "+v.text.trim()},"a new lesson")}));
 if(!les.length)lf.append(el("div","empty","No lessons saved yet."));
 for(const l of les){const r=el("div","row"),mn=el("div","main");mn.append(el("div","",l.text),el("div","meta","#"+l.id+" · "+l.time));
  if(l.flag){const b=el("div","meta","Flagged: "+l.flag);b.style.color="var(--x)";mn.append(b)}
  const q=pend(undefined,p=>(p.op==="lesson_edit"||p.op==="lesson_delete")&&Number(p.id)===Number(l.id));
  if(q.length)mn.append(pendChip(q[0].text));else{mn.append(btn("Edit",async()=>{const v=await ask("Edit lesson #"+l.id,[{key:"text",label:"Lesson",type:"textarea",value:g.title+": "+l.text}],"Queue edit");if(v&&v.text.trim())queue({op:"lesson_edit",id:l.id,text:v.text.trim()},"rewrite lesson #"+l.id)}),
   btn("Delete",()=>confirmThen("Delete lesson #"+l.id+"? It moves to the review Trash on the Pi, so it can be put back.",()=>queue({op:"lesson_delete",id:l.id},"delete lesson #"+l.id)),"danger"))}
  r.append(mn);lf.append(r)}list.append(lf)}

function attemptsTable(list,g,f){
 const s=G[g.id]=G[g.id]||{result:"all",cond:"all"};
 let att=g.attempts.filter(a=>!f||JSON.stringify(a).toLowerCase().includes(f));
 att=att.filter(a=>s.result==="all"||(s.result==="good"&&a.success&&a.counted)||(s.result==="bad"&&!a.success&&a.counted)||(s.result==="uncounted"&&!a.counted));
 att=att.filter(a=>s.cond==="all"||JSON.stringify(a.conditions,Object.keys(a.conditions).sort())===s.cond);
 const af=fold("Attempts ("+att.length+" of "+g.attempts.length+")",false);
 const fb=el("div");fb.style.margin="4px 0";
 for(const [k,t] of [["all","All"],["good","Good"],["bad","Not good"],["uncounted","Not counted"]])fb.append(btn(t,()=>{s.result=k;render()},s.result===k?"on":""));
 const cs=el("select");cs.append(Object.assign(el("option","","All floors and hardware"),{value:"all"}));for(const c of g.conditions_seen||[]){const o=el("option","",COND_LABEL(JSON.parse(c)));o.value=c;cs.append(o)}cs.value=s.cond;cs.onchange=()=>{s.cond=cs.value;render()};cs.style.marginLeft="8px";fb.append(cs);af.append(fb);
 if(!att.length){af.append(el("div","empty","No attempts match."));list.append(af);return}
 const t=el("table","gtbl"),h=el("tr");for(const x of ["#","When","Result","Time","Why it ended","Under",""])h.append(el("th","",x));t.append(h);
 for(const a of att){const tr=el("tr");if(a.retracted)tr.style.opacity=".55";
  const res=el("td");res.append(el("span","gchip "+(!a.counted?"":a.success?"ok":"bad"),!a.counted&&!a.retracted?"not counted":a.retracted?"retracted":a.success?"good":"not good"));
  tr.append(el("td","",a.number?"#"+a.number:"—"),el("td","",a.time),res,el("td","",a.seconds?Math.round(a.seconds)+" s":""),el("td","",(a.text||a.outcome||a.ended||"")+(a.ended&&a.ended!==a.text?" ("+a.ended+")":"")),el("td","",COND_LABEL(a.conditions||{})));
  const ac=el("td");const det=el("tr");det.style.display="none";const dc=el("td");dc.colSpan=7;
  const sx=Object.entries(a.settings||{}).map(([k,v])=>k.replace(/_/g," ")+" "+v).join(" · ");dc.append(el("div","meta","Settings used: "+(sx||"not recorded")));if(a.notes)dc.append(el("div","meta","Note: "+a.notes));det.append(dc);
  ac.append(btn("Details",()=>{det.style.display=det.style.display==="none"?"":"none"}));
  if(a.number){const sc=Object.entries(a.conditions||{}).map(([k,v])=>k+"="+v).join("|");const q=pend(g.id,p=>p.op==="verdict"&&Number(p.number)===a.number);
   if(q.length)ac.append(pendChip(q[0].text));else if(a.retracted&&!a.retired)ac.append(btn("Scored right after all",()=>queue({op:"verdict",goal:g.id,number:a.number,verdict:"right",scope:sc},"attempt #"+a.number+" was scored right")));
   else if(!a.retracted)ac.append(btn("Scored wrong",async()=>{const v=await ask("Attempt #"+a.number+" was scored wrong",[{key:"note",label:"Why (optional)",type:"text"}],"Queue it");if(v)queue({op:"verdict",goal:g.id,number:a.number,verdict:"wrong",note:v.note||undefined,scope:sc},"attempt #"+a.number+" was scored wrong")},"danger"))}
  tr.append(ac);t.append(tr,det)}
 af.append(t);list.append(af)}

async function editGoal(g){const df=g.definition||{};
 const v=await ask("Edit "+g.title,[{key:"title",label:"Name",value:df.title||g.title},{key:"attempts",label:"Attempts per session",type:"number",value:df.attempts,min:1,max:100,step:1},{key:"minutes",label:"Time limit per session (minutes)",type:"number",value:df.minutes,min:.5,max:240,step:"any"},
  {key:"min_pack_pct",label:"Pack needed to start an attempt (%)",type:"number",value:df.min_pack_pct,min:0,max:100,step:1},{key:"target_successes",label:"End early after this many successes (0 = use every attempt)",type:"number",value:df.target_successes||0,min:0,max:100,step:1},
  {key:"rest_between_s",label:"Rest between attempts (seconds)",type:"number",value:df.rest_between_s,min:0,max:600,step:"any"},{key:"start_words",label:"Start phrases (one per line, said after “G2,”)",type:"textarea",value:(df.start_words||[]).join("\n")}]);
 if(!v)return;const op={op:"set",goal:g.id},w=(df.start_words||[]).join("\n");
 for(const k of ["title","attempts","minutes","min_pack_pct","target_successes","rest_between_s"])if(v[k]!==null&&v[k]!==""&&String(v[k])!==String(k==="title"?(df.title||g.title):df[k]===undefined?"":df[k]))op[k]=v[k];
 if(v.start_words.trim()!==w.trim())op.start_words=v.start_words.split("\n").map(x=>x.trim()).filter(Boolean);
 if(Object.keys(op).length===2){toast("Nothing changed");return}queue(op,"change "+g.title)}

async function addGoal(){
 const v=await ask("Add a goal",[{key:"goal",label:"Short id (letters, digits, underscores)",hint:"For example ball_punt2. It is the name used by g2goal."},{key:"title",label:"Name"},{key:"approach",label:"Approach",type:"select",options:["ball_punt","walls"],value:"ball_punt",hint:"The approach is the code G2 runs; only these two exist today."},{key:"attempts",label:"Attempts per session",type:"number",value:10,min:1,max:100,step:1}],"Queue goal");
 if(!v)return;if(!/^[A-Za-z0-9_]+$/.test(v.goal||"")){toast("The id needs letters, digits and underscores");return}queue({op:"set",goal:v.goal,approach:v.approach,title:v.title||v.goal,attempts:v.attempts||10},"new goal "+v.goal)}

// ---- on the other tabs: what the tabs are showing and what still waits for the Pi
window.reviewPanel=function(list){const s=window.reviewState;if(!s||!s.mirror)return;
 const box=el("div","labelsum"),c=s.copy||{};
 box.append(el("b","","This is the copy on this Mac. "),document.createTextNode((c.has_memory?"Memory as of "+c.memory_from+". ":"No memory copy yet: press Sync now while the Pi is on. ")+"Edits are applied here at once and sent to the Pi when it is reachable (Sync now sends them first)."));
 if((s.pending||[]).length){const w=el("div");w.style.cssText="margin-top:6px;padding-top:6px;border-top:1px solid var(--line)";w.append(el("b","",s.pending.length+(s.pending.length===1?" edit is":" edits are")+" waiting for the Pi"));
  for(const p of s.pending){const r=el("div","meta",p.text);if(p.error){const e=el("div","meta","Last try failed: "+p.error);e.style.color="var(--x)";r.append(e)}
   if(p.cancellable)r.append(btn("Cancel",async()=>{try{window.reviewState=await api("/api/review/cancel",{id:p.id});load()}catch(e){toast("Failed: "+e.message)}},"danger"));w.append(r)}
  w.append(btn("Send to the Pi now",async()=>{toast("Sending…");try{const x=await api("/api/review/apply",{});window.reviewState=x;toast(x.message);load()}catch(e){toast("Failed: "+e.message)}},"on"));box.append(w)}
 list.append(box)};
window.g2ask=ask;window.g2btn=btn;
window.renderGoals=renderGoals;
})();
