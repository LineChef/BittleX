/* The Goals tab's "success since the start" (inserted into tools/g2_review.py's page at start-up, before the Goals tab code). goalSeries() is plain arithmetic on the attempts of one goal (also run in node by the
   tests); goalChart() draws it: the success rate over every counted attempt since the goal began, the rate over the last few attempts, and where the setting, floor or hardware changed. */
(function(){
const WIN=10;                                                                   // attempts in the rolling rate

function condKey(c){c=c||{};return [c.attachment,c.floor,c.hw].filter(Boolean).join(" | ")}

// attempts: the goal's attempts in any order (counted ones only are used), oldest first after sorting by raw_time.
function goalSeries(attempts,win){
 win=win||WIN;
 const a=(attempts||[]).filter(x=>x.counted).slice().sort((p,q)=>String(p.raw_time||"").localeCompare(String(q.raw_time||"")));
 const pts=[];let wins=0;
 a.forEach((x,i)=>{
  if(x.success)wins++;
  const n=i+1,from=Math.max(0,n-win);let rs=0;for(let k=from;k<n;k++)if(a[k].success)rs++;
  pts.push({n,number:x.number,time:x.time,success:!!x.success,cum:wins/n,roll:rs/(n-from),key:condKey(x.conditions)})});
 const n=a.length,rate=arr=>arr.filter(x=>x.success).length/arr.length;
 let trend=null;                                                                // the last w attempts against the w before them (w = win, or half of what there is when there are fewer)
 if(n>=6){const w=Math.max(1,Math.min(win,Math.floor(n/2))),last=a.slice(n-w),prev=a.slice(n-2*w,n-w);trend={w,last:rate(last),prev:rate(prev),delta:rate(last)-rate(prev)}}
 const changes=[];for(let i=1;i<pts.length;i++)if(pts[i].key!==pts[i-1].key)changes.push({at:i,from:pts[i-1].key||"?",to:pts[i].key||"?"});
 const firstHalf=n>=4?rate(a.slice(0,Math.floor(n/2))):null,secondHalf=n>=4?rate(a.slice(Math.floor(n/2))):null;
 return {points:pts,n,wins,overall:n?wins/n:null,roll:n?pts[n-1].roll:null,win,trend,changes,firstHalf,secondHalf}}

const pct=x=>Math.round(100*x)+"%";
function trendText(s){
 if(!s.trend)return s.n?"needs at least 6 counted attempts":"no counted attempts yet";
 const d=Math.round(100*s.trend.delta),arrow=d>0?"▲":d<0?"▼":"▬";
 return arrow+" "+(d>0?"+":"")+d+" points"}

// the chart: returns [svg, caption element]; the page's el() and the page's colour variables are used
function goalChart(s){
 const NS="http://www.w3.org/2000/svg",W=560,H=110,L=34,B=16,pw=W-L-8,n=s.n;
 const svg=document.createElementNS(NS,"svg");svg.setAttribute("viewBox","0 0 "+W+" "+(H+B+12));svg.setAttribute("width",W);svg.style.cssText="display:block;max-width:100%;margin:6px 0 2px";
 const mk=(tag,at,txt)=>{const e=document.createElementNS(NS,tag);for(const k in at)e.setAttribute(k,at[k]);if(txt!==undefined)e.textContent=txt;svg.append(e);return e};
 const X=i=>L+(n<=1?pw/2:pw*i/(n-1)),Y=r=>4+(H-8)*(1-r);
 for(const g of [0,.5,1]){mk("line",{x1:L,x2:W-8,y1:Y(g),y2:Y(g),stroke:"var(--line)","stroke-width":1});mk("text",{x:L-4,y:Y(g)+3,"text-anchor":"end","font-size":9,fill:"var(--muted)"},Math.round(g*100)+"%")}
 for(const c of s.changes){const e=mk("line",{x1:X(c.at)-.5*(n>1?pw/(n-1):0),x2:X(c.at)-.5*(n>1?pw/(n-1):0),y1:4,y2:H-4,stroke:"var(--muted)","stroke-dasharray":"3 3","stroke-width":1});const t=document.createElementNS(NS,"title");t.textContent="changed from "+c.from+" to "+c.to;e.append(t)}
 const path=(key,color,w,dash)=>{if(n<2)return;const d=s.points.map((p,i)=>(i?"L":"M")+X(i).toFixed(1)+" "+Y(p[key]).toFixed(1)).join(" ");const e=mk("path",{d,fill:"none",stroke:color,"stroke-width":w});if(dash)e.setAttribute("stroke-dasharray",dash)};
 path("roll","var(--ok)",1.5,"4 2");path("cum","var(--accent)",2.5);
 s.points.forEach((p,i)=>{                                                    // a dot per attempt on the cumulative line, with what it was
  const c=mk("circle",{cx:X(i),cy:Y(p.cum),r:n>80?1.5:2.6,fill:"var(--accent)"});const t=document.createElementNS(NS,"title");
  t.textContent="Attempt "+(p.number||p.n)+" ("+p.time+"): "+(p.success?"good":"not good")+". Since the start: "+pct(p.cum)+" of "+p.n+". Last "+Math.min(s.win,p.n)+": "+pct(p.roll);c.append(t);
  mk("rect",{x:X(i)-Math.max(.6,Math.min(3,pw/Math.max(1,n)/2-.2)),y:H+2,width:Math.max(1.2,Math.min(6,pw/Math.max(1,n)-.4)),height:7,fill:p.success?"var(--ok)":"var(--x)"})});   // the outcome of every attempt in a strip below
 if(n){mk("text",{x:L,y:H+B+9,"font-size":9,fill:"var(--muted)","text-anchor":"start"},s.points[0].time);mk("text",{x:W-8,y:H+B+9,"font-size":9,fill:"var(--muted)","text-anchor":"end"},s.points[n-1].time)}
 const cap=document.createElement("div");cap.className="meta";
 const sw=(color,dash,text)=>{const i=document.createElement("span");i.style.cssText="display:inline-block;width:18px;height:0;border-top:3px "+(dash?"dashed":"solid")+" "+color+";vertical-align:middle;margin:0 4px 0 10px";cap.append(i,document.createTextNode(text))};
 cap.append(document.createTextNode("Every counted attempt since the goal started, oldest to newest (hover a dot for the attempt)."));
 sw("var(--accent)",false,"success since the start");sw("var(--ok)",true,"last "+s.win+" attempts");
 if(s.changes.length)cap.append(document.createTextNode(" · dotted lines: the setting, floor or hardware changed"));
 cap.append(document.createTextNode(" · the strip under the chart is each attempt (green good, red not good)"));
 return [svg,cap]}

if(typeof window!=="undefined"){window.goalSeries=goalSeries;window.goalChart=goalChart;window.goalTrendText=trendText}
if(typeof module!=="undefined")module.exports={goalSeries,trendText};
})();
