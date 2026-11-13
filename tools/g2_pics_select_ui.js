/* Picking several pictures at once on the Pictures tab of the review page (inserted into tools/g2_review.py's page at start-up).
   A box on every picture, Shift-click for a range, "Select all / none" in each group header, and a bar at the bottom that sets one room for everything picked (user, 2026-11-12: the "Not labeled" pictures come
   from different rooms, so setting the room of the whole group, or one picture at a time, was not enough). The rooms are saved through setRooms() in the page, so Undo works. */
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
let bar=null,rooms=null,msg=null,inp=null,go=null;
function ensureBar(){
 if(bar||typeof document==="undefined")return;
 const st=document.createElement("style");
 st.textContent=".selbox{position:absolute;left:6px;top:6px;z-index:2;width:22px;height:22px;margin:0;cursor:pointer;accent-color:var(--accent)}.card.picked{outline:3px solid var(--accent);outline-offset:-3px}"
  +"#selbar{position:fixed;left:0;right:0;bottom:0;z-index:20;display:none;gap:10px;align-items:center;flex-wrap:wrap;padding:10px 16px;background:var(--surface);border-top:2px solid var(--accent);box-shadow:0 -2px 10px rgba(0,0,0,.2)}"
  +"#selbar input[type=text]{flex:1;min-width:180px;max-width:320px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}"
  +"body.hasselbar{padding-bottom:70px}body.hasselbar .toast{bottom:84px}";
 document.head.append(st);
 bar=el("div","");bar.id="selbar";
 msg=el("b","","");rooms=document.createElement("datalist");rooms.id="selrooms";
 inp=document.createElement("input");inp.type="text";inp.setAttribute("list","selrooms");inp.placeholder="Room for these (kitchen, hallway, ...)";inp.setAttribute("aria-label","Room for the selected pictures");
 go=el("button","btn","Set room");go.style.cssText="background:var(--accent);color:#fff;border-color:var(--accent)";
 const none=el("button","btn","Clear selection"),hint=el("span","meta","Shift-click a second picture to pick everything between.");
 go.onclick=apply;none.onclick=()=>{sel.clear();last=null;update()};
 inp.onkeydown=ev=>{if(ev.key==="Enter"){ev.preventDefault();apply()}else if(ev.key==="Escape"){sel.clear();last=null;update()}};
 bar.append(msg,inp,rooms,go,none,hint);document.body.append(bar)}
function roomNames(){const s=new Set();try{for(const p of data)if(p.room)s.add(p.room)}catch(e){}if(window.lastRoom)s.add(window.lastRoom);return[...s].sort()}
async function apply(){
 const room=(inp.value||"").trim();if(!room){toast("Type the room first");inp.focus();return}
 const ps=[...sel].map(path=>reg.get(path)).filter(Boolean).map(r=>r.p);if(!ps.length){sel.clear();update();return}
 sel.clear();last=null;await setRooms(ps,room);inp.value="";update()}
function update(){
 for(const [path,r] of reg){const on=sel.has(path);if(r.input.checked!==on)r.input.checked=on;r.card.classList.toggle("picked",on)}
 for(const f of groupRefresh)f();
 if(!bar)return;const n=sel.size;bar.style.display=n?"flex":"none";document.body.classList.toggle("hasselbar",n>0);
 if(n){msg.textContent=n+" selected";go.textContent="Set room for "+n;if(!inp.value&&window.lastRoom)inp.placeholder="Room for these (last used: "+window.lastRoom+")";rooms.replaceChildren(...roomNames().map(r=>{const o=document.createElement("option");o.value=r;return o}))}}
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
  b.onclick=ev=>{ev.stopPropagation();choose(group.map(q=>q.path),!allIn(group));update()};paint();groupRefresh.push(paint);return b},
 end(){                                                                                       // the page is drawn: pictures that are not on it any more (a filter, a room just set) leave the selection
  for(const path of [...sel])if(!reg.has(path))sel.delete(path);update()},
 leave(){sel.clear();last=null;reg=new Map();groupRefresh=[];if(bar){bar.style.display="none";document.body.classList.remove("hasselbar")}},      // another tab
 _logic:{rangePaths,choose,click,allIn,selection:()=>[...sel],reset:()=>{sel.clear();last=null}}
};
})();
