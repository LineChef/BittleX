/* Picking several pictures at once on the Pictures tab of the review page (inserted into tools/g2_review.py's page at start-up).
   A box on every picture, Shift-click for a range, "Select all / none" and "Select by G2's guess" in each group header, and a bar at the bottom that sets one room, or one NAME, for everything picked, or
   accepts G2's suggested label for each (user, 2026-11-12: the "Not labeled" pictures come from different rooms and show different objects, so one picture at a time was too slow). Rooms go through setRooms()
   in the page and names through /api/pictures/name, so Undo works. */
(function(){
// ---- the choosing itself (no page needed: tools tests load this file with stubs)
const sel=new Set();                 // the paths picked
let reg=new Map();                   // path -> {p, card, input, group}: the pictures drawn right now
let last=null;                       // the last box clicked: {path, group}

function rangePaths(group,fromPath,toPath){const a=group.findIndex(q=>q.path===fromPath),b=group.findIndex(q=>q.path===toPath);if(a<0||b<0)return[toPath];const lo=Math.min(a,b),hi=Math.max(a,b);return group.slice(lo,hi+1).map(q=>q.path)}
function choose(paths,on){for(const p of paths){if(on)sel.add(p);else sel.delete(p)}}
function click(group,path,on,shift){                                      // one box: alone, or with Shift the whole run from the last box in the same group
 const from=last&&last.group===group&&last.path!==path?last.path:null;
 choose(shift&&from?rangePaths(group,from,path):[path],on);last={path,group}}
function allIn(group){return group.length>0&&group.every(q=>sel.has(q.path))}

// ---- the page parts, made when first needed
let bar=null,rooms=null,msg=null,inp=null,go=null,names=null,ninp=null,ngo=null,acc=null;
function ensureBar(){
 if(bar||typeof document==="undefined")return;
 const st=document.createElement("style");
 st.textContent=".selbox{position:absolute;left:6px;top:6px;z-index:2;width:22px;height:22px;margin:0;cursor:pointer;accent-color:var(--accent)}.card.picked{outline:3px solid var(--accent);outline-offset:-3px}"
  +"#selbar{position:fixed;left:0;right:0;bottom:0;z-index:20;display:none;gap:10px;align-items:center;flex-wrap:wrap;padding:10px 16px;background:var(--surface);border-top:2px solid var(--accent);box-shadow:0 -2px 10px rgba(0,0,0,.2)}"
  +"#selbar input[type=text]{flex:1;min-width:180px;max-width:320px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}"
  +"body.hasselbar{padding-bottom:120px}body.hasselbar .toast{bottom:130px}";
 document.head.append(st);
 bar=el("div","");bar.id="selbar";
 msg=el("b","","");rooms=document.createElement("datalist");rooms.id="selrooms";names=document.createElement("datalist");names.id="selnames";
 inp=document.createElement("input");inp.type="text";inp.setAttribute("list","selrooms");inp.placeholder="Room (kitchen, hallway, ...)";inp.setAttribute("aria-label","Room for the selected pictures");
 go=el("button","btn","Set room");go.style.cssText="background:var(--accent);color:#fff;border-color:var(--accent)";
 ninp=document.createElement("input");ninp.type="text";ninp.setAttribute("list","selnames");ninp.placeholder="What is it? (dishwasher, mug, ...)";ninp.setAttribute("aria-label","Name for the selected pictures");
 ngo=el("button","btn","Name them");ngo.style.cssText="background:var(--accent);color:#fff;border-color:var(--accent)";
 acc=el("button","btn","Accept G2's guesses");acc.title="Name each selected picture with the label G2 suggested for it (pictures with no guess are left alone)";
 const none=el("button","btn","Clear selection"),hint=el("span","meta","Shift-click a second picture to pick everything between.");
 go.onclick=apply;ngo.onclick=applyName;acc.onclick=acceptGuesses;none.onclick=()=>{sel.clear();last=null;update()};
 inp.onkeydown=ev=>{if(ev.key==="Enter"){ev.preventDefault();apply()}else if(ev.key==="Escape"){sel.clear();last=null;update()}};
 ninp.onkeydown=ev=>{if(ev.key==="Enter"){ev.preventDefault();applyName()}else if(ev.key==="Escape"){sel.clear();last=null;update()}};
 bar.append(msg,inp,rooms,go,ninp,names,ngo,acc,none,hint);document.body.append(bar)}
function knownNames(){const t=new Set();try{for(const p of data){if(p.name)t.add(p.name);if(p.guess&&p.guess.label)t.add(p.guess.label)}}catch(e){}if(window.lastName)t.add(window.lastName);return[...t].sort()}
function roomNames(){const s=new Set();try{for(const p of data)if(p.room)s.add(p.room)}catch(e){}if(window.lastRoom)s.add(window.lastRoom);return[...s].sort()}
async function apply(){
 const room=(inp.value||"").trim();if(!room){toast("Type the room first");inp.focus();return}
 const ps=[...sel].map(path=>reg.get(path)).filter(Boolean).map(r=>r.p);if(!ps.length){sel.clear();update();return}
 sel.clear();last=null;await setRooms(ps,room);inp.value="";update()}
function selected(){return [...sel].map(path=>reg.get(path)).filter(Boolean).map(r=>r.p)}
function undoNames(done){return async()=>{await api("/api/pictures/move",{pairs:done.flatMap(r=>r.named.map(m=>[m.to,m.from]))})}}
async function applyName(){                                                                // one name for everything picked
 const nm=(ninp.value||"").trim().replace(/\s+/g," ");if(!nm){toast("Type the name first");ninp.focus();return}
 const ps=selected();if(!ps.length){sel.clear();update();return}
 try{const r=await api("/api/pictures/name",{paths:ps.map(p=>p.path),name:nm});window.lastName=nm;sel.clear();last=null;ninp.value="";
  toast("Named "+ps.length+" picture(s): "+nm,undoNames([r]));load()}catch(e){toast("Failed: "+e.message)}}
async function acceptGuesses(){                                                            // each picked picture gets the label G2 suggested for it
 const by=new Map();for(const p of selected())if(p.guess&&p.guess.label&&!p.name){(by.get(p.guess.label)||by.set(p.guess.label,[]).get(p.guess.label)).push(p.path)}
 if(!by.size){toast("None of the selected pictures has a guess from G2");return}
 const done=[];let n=0;try{for(const [label,paths] of by){done.push(await api("/api/pictures/name",{paths,name:label}));n+=paths.length}}catch(e){toast("Failed: "+e.message);if(done.length)load();return}
 sel.clear();last=null;toast("Named "+n+" picture(s) with G2's guesses ("+[...by.keys()].join(", ")+")",undoNames(done));load()}
function update(){
 for(const [path,r] of reg){const on=sel.has(path);if(r.input.checked!==on)r.input.checked=on;r.card.classList.toggle("picked",on)}
 for(const f of groupRefresh)f();
 if(!bar)return;const n=sel.size;bar.style.display=n?"flex":"none";document.body.classList.toggle("hasselbar",n>0);
 if(n){msg.textContent=n+" selected";go.textContent="Set room for "+n;ngo.textContent="Name "+n;const g=selected().filter(p=>p.guess&&p.guess.label&&!p.name).length;acc.textContent="Accept G2's guesses ("+g+")";acc.disabled=!g;
  names.replaceChildren(...knownNames().map(x=>{const o=document.createElement("option");o.value=x;return o}));if(!inp.value&&window.lastRoom)inp.placeholder="Room for these (last used: "+window.lastRoom+")";rooms.replaceChildren(...roomNames().map(r=>{const o=document.createElement("option");o.value=r;return o}))}}
let groupRefresh=[];

window.picSelect={
 begin(on){reg=new Map();groupRefresh=[];if(on)ensureBar()},                                  // the page is being drawn again: the boxes are made again
 attach(card,p,group){                                                                       // a box on one picture
  const input=document.createElement("input");input.type="checkbox";input.className="selbox";input.title="Pick this picture (Shift-click another to pick everything between)";input.setAttribute("aria-label","Pick this picture");
  input.checked=sel.has(p.path);if(input.checked)card.classList.add("picked");
  input.onclick=ev=>{ev.stopPropagation();click(group,p.path,input.checked,ev.shiftKey);update()};
  card.append(input);reg.set(p.path,{p,card,input,group})},
 groupButtons(group){                                                                        // "Select all N" / "Select none" in a group's header
  const b=el("button","btn","");b.style.cssText="margin-left:6px;padding:1px 8px;font-size:.78rem";
  const paint=()=>{const all=allIn(group);b.textContent=all?"Select none":"Select all "+group.length;b.title=all?"Take these off the selection":"Pick every picture in this group, then set one room for them in the bar at the bottom"};
  b.onclick=ev=>{ev.stopPropagation();choose(group.map(q=>q.path),!allIn(group));update()};paint();groupRefresh.push(paint);
  const counts=new Map();for(const q of group)if(q.guess&&q.guess.label&&!q.name)counts.set(q.guess.label,(counts.get(q.guess.label)||0)+1);
  if(!counts.size)return b;                                                                 // with guesses: a menu that picks every picture G2 thinks is the same thing, to name them together
  const w=document.createElement("span"),m=document.createElement("select");m.style.cssText="margin-left:6px;font-size:.78rem;padding:1px 4px";m.title="Pick every picture G2 thinks is the same object, then name them from the bar at the bottom";
  const o0=document.createElement("option");o0.value="";o0.textContent="Select by G2's guess...";m.append(o0);
  for(const [label,n] of [...counts].sort((x,y)=>y[1]-x[1])){const o=document.createElement("option");o.value=label;o.textContent=label+" ("+n+")";m.append(o)}
  m.onclick=ev=>ev.stopPropagation();m.onchange=ev=>{ev.stopPropagation();if(m.value){choose(group.filter(q=>q.guess&&q.guess.label===m.value&&!q.name).map(q=>q.path),true);m.value="";update()}};
  w.append(b,m);return w},
 end(){                                                                                       // the page is drawn: pictures that are not on it any more (a filter, a room just set) leave the selection
  for(const path of [...sel])if(!reg.has(path))sel.delete(path);update()},
 leave(){sel.clear();last=null;reg=new Map();groupRefresh=[];if(bar){bar.style.display="none";document.body.classList.remove("hasselbar")}},      // another tab
 _logic:{rangePaths,choose,click,allIn,selection:()=>[...sel],reset:()=>{sel.clear();last=null}}
};
})();
