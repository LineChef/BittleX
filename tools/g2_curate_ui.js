/* Two "do the curating for me" panels of the review page (inserted into tools/g2_review.py's page at start-up):
   the Observations tab's suggested clean-up (near-duplicates, captions too short to recall) and the Pictures tab's Curate panel (the pictures the automatic filter set aside).
   Nothing changes until the button is pressed; deleted records and pictures go to the Trash, and the toast has an Undo. */
(function(){
// ---- Observations
let obsTidy=null,obsFor=null;
const obsIgn=()=>{try{return new Set(JSON.parse(localStorage.getItem("g2ObsKeep")||"[]"))}catch(e){return new Set()}};
const addObsIgn=id=>{try{const s=obsIgn();s.add(id);localStorage.setItem("g2ObsKeep",JSON.stringify([...s]))}catch(e){}};
async function deleteObservations(rows){
 const done=[];let failed=0;
 for(const r of rows){try{const t=await api("/api/delete",{kind:"observations",id:r.id});done.push(t.trash_id)}catch(x){failed++}}
 obsFor=null;load();
 toast(done.length+" observations moved to the Trash"+(failed?"; "+failed+" failed":"")+".",async()=>{for(const id of done){try{await api("/api/restore",{trash_id:id})}catch(x){}}obsFor=null;load()})}
function observationsPanel(list){
 if(obsFor!==data){obsFor=data;obsTidy=null;api("/api/observations/tidy").then(t=>{obsTidy=t;render()}).catch(e=>{obsTidy={error:e.message};render()})}
 const box=el("div","labelsum");box.style.borderColor="#7fb069";
 if(!obsTidy){box.append(el("div","meta","Working out suggested clean-ups…"));list.append(box);return}
 if(obsTidy.error){box.append(el("div","meta","Could not check: "+obsTidy.error));list.append(box);return}
 const keep=obsIgn(),sug=obsTidy.suggestions.filter(s=>!keep.has(s.id)&&(data||[]).some(r=>r.id===s.id));
 if(!sug.length){box.append(el("b","","Suggested clean-up: nothing to do."),el("div","sub","No near-duplicate observations and none too short to recall."));list.append(box);return}
 box.append(el("b","","Suggested clean-up: "+sug.length+(sug.length===1?" observation":" observations")+" to delete"));
 box.append(el("div","sub","Near-duplicates (the better-labelled or newer one is kept) and captions of two words or fewer. Nothing changes until you press the button; they go to the Trash with an Undo."));
 const row=el("div");row.style.margin="6px 0";
 row.append(window.g2btn("Delete all "+sug.length,()=>{if(confirm("Move these "+sug.length+" observations to the Trash?"))deleteObservations(sug.map(s=>({id:s.id})))},"danger"));box.append(row);
 const fl=fold("Show them",sug.length<=8);
 for(const s of sug){const l=el("div","meta");l.append(document.createTextNode("#"+s.id+" “"+s.caption+"” — "+s.why+" "));l.append(window.g2btn("Keep",()=>{addObsIgn(s.id);render()}));fl.append(l)}
 box.append(fl);list.append(box)}
window.observationsPanel=observationsPanel;

// ---- Pictures: Curate
const WHY={duplicate:"a near-duplicate of a better picture",people:"has a person in it"};
function curatePanel(list){
 const bad=(data||[]).filter(p=>p.group!=="looks"&&p.group!=="named"&&["rejected","duplicate","people"].includes(p.status));
 const weak=(data||[]).filter(p=>p.group==="named"&&p.status==="weak").length,all=(data||[]).filter(p=>p.group!=="looks").length;
 const box=el("div","labelsum");box.style.borderColor="#7fb069";
 if(!bad.length){box.append(el("b","","Curate: nothing to set aside."),el("div","sub",all+" pictures checked (brightness, sharpness, cut-off, people, near-duplicates)."+(weak?" "+weak+" named pictures are weak but kept, as you named them.":"")));list.append(box);return}
 const by={};for(const p of bad){const k=p.status==="rejected"?(p.reason||"filtered out"):WHY[p.status];(by[k]=by[k]||[]).push(p)}
 box.append(el("b","","Curate: "+bad.length+" of "+all+" pictures are set aside"));
 box.append(el("div","sub",Object.keys(by).sort((a,b)=>by[b].length-by[a].length).map(k=>by[k].length+" "+k).join(" · ")+". Pictures you named are never removed. Nothing is deleted until you press the button; they go to the Trash with an Undo."));
 const row=el("div");row.style.margin="6px 0";
 const del=window.g2btn("Delete all "+bad.length+" set-aside pictures",async()=>{if(!confirm("Move these "+bad.length+" pictures to the Trash?"))return;const ps=bad.map(q=>q.path);
  try{await api("/api/pictures/trash",{paths:ps});data=data.filter(d=>!ps.includes(d.path));render();toast(ps.length+" pictures moved to the Trash",async()=>{await api("/api/pictures/restore",{paths:ps});load()})}catch(e){toast("Failed: "+e.message)}},"danger");
 row.append(del);box.append(row);
 const fl=fold("Look at them first ("+bad.length+")",false);
 fl.addEventListener("toggle",()=>{if(!fl.open||fl.dataset.drawn)return;fl.dataset.drawn="1";const grid=el("div","grid");
  for(const p of bad.slice(0,60)){const c=el("div","card");const im=el("img");im.loading="lazy";im.src="/img/"+p.path.split("/").map(encodeURIComponent).join("/")+"?t="+TOKEN;im.alt=p.status;
   c.append(im,el("div","meta",p.status==="rejected"?(p.reason||"filtered out"):WHY[p.status]));grid.append(c)}
  fl.append(grid);if(bad.length>60)fl.append(el("div","meta","…and "+(bad.length-60)+" more"))});
 box.append(fl);list.append(box)}
window.curatePanel=curatePanel;
})();
