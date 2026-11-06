/* The Conversations tab of the review page (inserted into tools/g2_review.py's page at start-up): exchanges grouped into conversations, a "likely false triggers" panel with one button to delete them, and checkboxes for the rest. */
(function(){
const FILL=new Set(("a an the and or but so if as of to in on at by for with from up out off it its is are was be been am do does did have has had not no yes yeah yep nope ok okay i me my we us you your he she him her they them this that these those there here what why how who when where which while than then just like ah oh uh um er hm hmm huh mm mhm eh ha well right alright").split(" "));
const CLARIFY=/(only caught|didn.t (quite |really )?(catch|get|hear)|missed (part|the|some)|not sure what you mean|say that again|could you (say|repeat)|cut off|got a bit lost|didn.t follow|just says)/i;
const GAP_MIN=3;                                   // rows closer together than this are one conversation
const words=t=>((t||"").toLowerCase().match(/[a-z']+/g)||[]);
// a turn of one or two words that is all filler, or that G2 could only answer with "I only caught..." / "say that again": a wake word that was not a call
const likelyFalse=r=>{const w=words(r.user_text);if(!w.length)return true;if(w.length>2)return false;return w.every(x=>FILL.has(x))||CLARIFY.test(r.assistant_text||"")};
const keepIgn=()=>{try{return new Set(JSON.parse(localStorage.getItem("g2KeepExchanges")||"[]"))}catch(e){return new Set()}};
const addKeep=id=>{try{const s=keepIgn();s.add(id);localStorage.setItem("g2KeepExchanges",JSON.stringify([...s]))}catch(e){}};
const when=ts=>{const d=new Date((ts||"").replace(" ","T"));if(isNaN(d))return ts||"";const mo=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];let h=d.getHours();const ap=h>=12?"PM":"AM";h=h%12||12;return mo[d.getMonth()]+" "+d.getDate()+", "+h+":"+String(d.getMinutes()).padStart(2,"0")+" "+ap};
const stamp=r=>new Date((r.ts||"").replace(" ","T")).getTime();
const sel=new Set();                                // ids ticked for "Delete selected"
async function deleteRows(rows,label){
 const done=[];let failed=0;
 for(const r of rows){try{const t=await api("/api/delete",{kind:"exchanges",id:r.id});done.push(t.trash_id)}catch(x){failed++}}
 sel.clear();load();
 toast(label+": "+done.length+" moved to the Trash"+(failed?"; "+failed+" failed":"")+".",async()=>{for(const id of done){try{await api("/api/restore",{trash_id:id})}catch(x){}}load()})}
function rowLine(r,withBox){
 const row=el("div","row"),main=el("div","main");
 if(withBox){const cb=el("input");cb.type="checkbox";cb.checked=sel.has(r.id);cb.style.cssText="margin-right:8px;flex:none";cb.onchange=()=>{if(cb.checked)sel.add(r.id);else sel.delete(r.id);window.renderExchangesBar&&window.renderExchangesBar()};row.append(cb)}
 main.append(el("div","",r.user_text||"(nothing)"),el("div","q",r.assistant_text||"(no reply)"),el("div","meta",when(r.ts)+(r.actions?" · "+r.actions:"")));
 row.append(main,xbtn(async()=>{await deleteRows([r],"Deleted")}));return row}
function renderExchanges(list,f){
 const all=(data||[]).filter(r=>!f||JSON.stringify(r).toLowerCase().includes(f)).slice().sort((a,b)=>stamp(a)-stamp(b)||a.id-b.id);
 const keep=keepIgn(),maybe=all.filter(r=>likelyFalse(r)&&!keep.has(r.id)),real=all.filter(r=>!maybe.includes(r));
 if(!all.length){list.append(el("div","empty","Nothing here."));return}
 // 1. likely false triggers
 const box=el("div","labelsum");box.style.borderColor="#e0c15a";
 if(!maybe.length){box.append(el("b","","No likely false triggers."),el("div","sub","Short fillers after a wake word are no longer saved at all, so new ones should stop appearing."))}
 else{box.append(el("b","",maybe.length+(maybe.length===1?" exchange looks":" exchanges look")+" like a false wake word"));
  box.append(el("div","sub","One or two filler words (“yeah”, “the”, “ah”), or something G2 could only answer with “I only caught…”. Nothing is deleted until you press the button; they go to the Trash with an Undo."));
  const row=el("div");row.style.margin="6px 0";
  const del=window.g2btn("Delete all "+maybe.length,()=>{if(confirm("Move these "+maybe.length+" exchanges to the Trash?"))deleteRows(maybe,"Deleted")},"danger");row.append(del);box.append(row);
  const fl=fold("Show them",maybe.length<=8);
  for(const r of maybe){const l=el("div","meta");l.append(document.createTextNode(when(r.ts)+" · “"+(r.user_text||"")+"” → "+((r.assistant_text||"(no reply)").slice(0,70))+" "));
   l.append(window.g2btn("Keep",()=>{addKeep(r.id);render()}));fl.append(l)}
  box.append(fl)}
 list.append(box);
 // 2. the rest, grouped into conversations
 const groups=[];for(const r of real){const g=groups[groups.length-1];if(g&&stamp(r)-stamp(g[g.length-1])<=GAP_MIN*60000)g.push(r);else groups.push([r])}
 const bar=el("div");bar.style.cssText="margin:8px 0;display:flex;gap:8px;align-items:center";
 window.renderExchangesBar=()=>{bar.replaceChildren();const n=[...sel].filter(id=>real.some(r=>r.id===id)).length;
  bar.append(el("span","meta",real.length+" exchanges in "+groups.length+" conversations (newest first)"));
  if(n){bar.append(window.g2btn("Delete selected ("+n+")",()=>deleteRows(real.filter(r=>sel.has(r.id)),"Deleted"),"danger"),window.g2btn("Clear selection",()=>{sel.clear();render()}))}};
 window.renderExchangesBar();list.append(bar);
 window.openConv=window.openConv||{};
 groups.slice().reverse().forEach((g,i)=>{const key=g[0].id;if(!(key in window.openConv))window.openConv[key]=i<3;                 // the three newest conversations start open
  const head=el("div","group");head.style.cssText="cursor:pointer;display:flex;gap:8px;align-items:center";
  const gcb=el("input");gcb.type="checkbox";gcb.checked=g.every(r=>sel.has(r.id));gcb.title="Select the whole conversation";gcb.onclick=ev=>{ev.stopPropagation();for(const r of g){if(gcb.checked)sel.add(r.id);else sel.delete(r.id)}render()};
  const caret=el("span","caret");const title=el("span","",when(g[0].ts)+" · "+g.length+(g.length===1?" exchange":" exchanges")+" · “"+(g[0].user_text||"").slice(0,60)+"”");
  head.append(gcb,caret,title,window.g2btn("Delete conversation",()=>{if(g.length===1||confirm("Move this conversation ("+g.length+" exchanges) to the Trash?"))deleteRows(g,"Deleted")},"danger"));
  const body=el("div");const sync=()=>{const o=window.openConv[key];caret.textContent=o?"▾":"▸";body.style.display=o?"":"none"};
  head.onclick=ev=>{if(ev.target.closest&&ev.target.closest("button,input"))return;window.openConv[key]=!window.openConv[key];sync()};
  for(const r of g)body.append(rowLine(r,true));sync();list.append(head,body)})}
window.renderExchanges=renderExchanges;window.g2exchangesFalse=likelyFalse;
})();
