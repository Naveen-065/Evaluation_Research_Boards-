"use strict";
const $=id=>document.getElementById(id);
let latest=null, cells=[], previousMode="read";
const value=id=>Number($(id).value);
function selectCell(r,c){$("row").value=r;$("col").value=c;highlight();}
function highlight(){
  const r=value("row"),c=value("col");cells.forEach((el,i)=>el.classList.toggle("selected",i===r*32+c));
  $("selectedCell").textContent=`Selected r${r} / c${c}`;
}
for(let n=0;n<32;n++){
  const a=document.createElement("span");a.textContent=n%4===0?n:"";$("colLabels").append(a);
  const b=document.createElement("span");b.textContent=n%4===0?n:"";$("rowLabels").append(b);
}
for(let r=0;r<32;r++)for(let c=0;c<32;c++){
  const b=document.createElement("button");b.className="cell";b.title=`r${r} / c${c} · unmeasured`;
  b.setAttribute("aria-label",`Select row ${r} column ${c}`);b.onclick=()=>selectCell(r,c);
  $("heatmap").append(b);cells.push(b);
}
function modeChanged(){
 const mode=$("mode").value,wb=mode.startsWith("wb_");
 if(wb&&!previousMode.startsWith("wb_"))selectCell(0,31);
 if(!wb&&previousMode.startsWith("wb_"))selectCell(0,0);
 previousMode=mode;
 $("scanPulse").hidden=wb||!["set","reset","cycle"].includes(mode);
 $("cycleField").hidden=!mode.includes("cycle");$("wbNote").hidden=!wb;
 $("modeClock").textContent=wb?"10 MHz WB":"2 MHz scan";
 $("run").textContent=$("dry_run").checked?"Preview operation":"Run on hardware";
}
function parameters(){return {mode:$("mode").value,row:value("row"),col:value("col"),
 set_v:value("set_v"),set_wl:value("set_wl"),reset_v:value("reset_v"),reset_wl:value("reset_wl"),
 hold:Math.round(value("pulse_ms")*2000),cycles:value("cycles"),dry_run:$("dry_run").checked};}
async function post(path,body){
 const res=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 const data=await res.json();if(!res.ok)throw Error(data.error||res.statusText);return data;
}
$("runForm").onsubmit=async e=>{
 e.preventDefault();$("run").disabled=true;
 try{
  const p=parameters(),data=await post("/api/run",p);
  if(data.dry_run){$("preview").hidden=false;$("previewText").textContent=JSON.stringify(data,null,2);$("preview").scrollIntoView({behavior:"smooth",block:"nearest"});}
  else $("preview").hidden=true;
  await refresh();
 }catch(e){$("message").textContent=e.message;$("run").disabled=false;}
};
$("check").onclick=async()=>{try{await post("/api/run",{mode:"check",dry_run:false});await refresh();}catch(e){$("message").textContent=e.message;}};
$("cancel").onclick=async()=>{try{await post("/api/cancel",{});$("message").textContent="Stopping; waiting for read-profile restoration.";}catch(e){$("message").textContent=e.message;}};
$("closePreview").onclick=()=>{$("preview").hidden=true;};
$("mode").onchange=modeChanged;$("dry_run").onchange=()=>{modeChanged();render(latest);};
$("row").onchange=highlight;$("col").onchange=highlight;$("mapSource").onchange=()=>render(latest);
function fmt(x){return x===null||!Number.isFinite(x)?"—":x.toFixed(3);}
function drawWaveform(history){
 const cv=$("waveform"),dpr=window.devicePixelRatio||1,w=cv.clientWidth,h=220;
 cv.width=w*dpr;cv.height=h*dpr;const ctx=cv.getContext("2d");ctx.scale(dpr,dpr);
 const capture=[...history].reverse().find(r=>r.kind==="scan"&&r.trace?.length);
 const pts=capture?.trace||[],checked=[$("traceRead").checked,$("traceReset").checked,$("traceSet").checked];
 const values=pts.flatMap(p=>p.delta_current_ua.filter((_,i)=>checked[i]));
 let lo=values.length?Math.min(0,...values):0,hi=values.length?Math.max(...values):1;
 if(hi-lo<1){lo-=.5;hi+=.5;}const margin=(hi-lo)*.08;lo-=margin;hi+=margin;
 const left=58,right=w-16,top=15,bottom=183;
 const maxT=pts.length?pts.at(-1).time_us:1350;
 const x=t=>left+t/Math.max(1,maxT)*(right-left),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
 ctx.clearRect(0,0,w,h);
 const selected=pts.filter(p=>p.phase===6);
 if(selected.length){
  ctx.fillStyle="#29323d";ctx.fillRect(x(selected[0].time_us),top,x(selected.at(-1).time_us)-x(selected[0].time_us),bottom-top);
  ctx.fillStyle="#8fa0b5";ctx.font="10px system-ui";ctx.fillText("CELL SELECTED",x(selected[0].time_us)+8,top+13);
 }
 ctx.font="10px system-ui";
 for(let i=0;i<=4;i++){
  const yy=top+(bottom-top)*i/4;ctx.strokeStyle="#303640";ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();
  ctx.fillStyle="#939ba9";ctx.fillText((hi-(hi-lo)*i/4).toFixed(1),4,yy+3);
  const xx=left+(right-left)*i/4;ctx.fillText((maxT*i/4/1000).toFixed(2),xx-10,bottom+19);
 }
 ctx.fillStyle="#939ba9";ctx.fillText("Time from baseline start · ms",Math.max(left,w/2-70),216);
 if(!pts.length){ctx.fillStyle="#a7b5c5";ctx.font="13px system-ui";ctx.fillText("Waiting for a measured ADC read trace",left+20,95);return;}
 ["#54cfaa","#e8b86e","#77aaff"].forEach((color,ch)=>{
  if(!checked[ch])return;ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();
  pts.forEach((p,i)=>{i?ctx.lineTo(x(p.time_us),y(p.delta_current_ua[ch])):ctx.moveTo(x(p.time_us),y(p.delta_current_ua[ch]));});ctx.stroke();
 });
 $("waveCell").textContent=`· r${capture.row}/c${capture.col} · ${capture.operation.replaceAll("_"," ")}`;
 $("waveNote").textContent=`${pts.length}/${capture.trace_expected} measured points · ADC 10 MSPS, trace decimated to ${pts.length>1?(pts[1].time_us-pts[0].time_us).toFixed(1):"—"} µs spacing · shaded region is the cell-selection window · ${new Date(capture.time).toLocaleTimeString()}`;
}
["traceRead","traceReset","traceSet"].forEach(id=>$(id).onchange=()=>latest&&drawWaveform(latest.history));
function drawTrace(rows){
 const cv=$("trace"),dpr=window.devicePixelRatio||1,w=cv.clientWidth,h=170;
 cv.width=w*dpr;cv.height=h*dpr;const ctx=cv.getContext("2d");ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
 const vals=rows.filter(x=>x.kind==="scan"&&!x.operation.endsWith("_pulse")).slice(-100).map(x=>x.channels[2].delta_current_ua).filter(Number.isFinite);
 ctx.font="10px system-ui";ctx.fillStyle="#939ba9";
 if(!vals.length){ctx.fillText("Waiting for measured reads",20,75);return;}
 let lo=Math.min(...vals),hi=Math.max(...vals);if(hi-lo<.1){lo-=.05;hi+=.05;}
 for(let i=0;i<4;i++){const y=15+i*40;ctx.strokeStyle="#303640";ctx.beginPath();ctx.moveTo(48,y);ctx.lineTo(w-10,y);ctx.stroke();ctx.fillText((hi-(hi-lo)*i/3).toFixed(2),0,y+4);}
 ctx.strokeStyle="#54cfaa";ctx.lineWidth=1.8;ctx.beginPath();
 vals.forEach((v,i)=>{const x=48+i*(w-60)/Math.max(1,vals.length-1),y=15+(hi-v)/(hi-lo)*120;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
 if(vals.length===1){ctx.beginPath();ctx.arc(48,15+(hi-vals[0])/(hi-lo)*120,3,0,7);ctx.fillStyle="#54cfaa";ctx.fill();}
 $("traceNote").textContent=`${vals.length} most recent read windows · program-pulse samples excluded`;
}
function render(s){
 if(!s)return;latest=s;
 $("connection").textContent=s.busy?"Bench running":s.deployment.ready?"Control image ready":"Deployment pending";
 $("connection").classList.toggle("warn",!s.deployment.ready);
 $("validationNote").hidden=!s.deployment.validation_note;
 $("validationNote").textContent=s.deployment.validation_note||"";
 $("check").disabled=s.busy;$("run").disabled=s.busy||(!$("dry_run").checked&&!s.deployment.ready);$("cancel").disabled=!s.busy;
 $("message").textContent=s.message;$("jobLabel").textContent=(s.job?.state||"ready").toUpperCase();
 $("resultCount").textContent=s.job?`${s.job.result_count} captures`:"";
 const mode=s.job?.parameters.mode,expected=mode==="array"?1024:mode==="column"?32:mode?.includes("cycle")?(mode==="wb_cycle"?5:6)*(s.job.parameters.cycles||1):["set","reset"].includes(mode)?3:1;
 $("progress").max=expected;$("progress").value=s.job?.result_count||0;
 const scan=[...s.history].reverse().find(x=>x.kind==="scan"&&!x.operation.endsWith("_pulse"));
 if(scan){["readCurrent","resetCurrent","setCurrent"].forEach((id,i)=>$(id).textContent=fmt(scan.channels[i].delta_current_ua));}
 const wb=[...s.history].reverse().find(x=>x.kind==="wb");
 if(wb){$("wbReturn").textContent=wb.selected;$("wbCounts").textContent=wb.matching_column?`Coarse ${wb.coarse} · fine ${wb.fine} · c${wb.col}`:"Unverified: no nonzero return matching selected column";}
 const map=new Map(),source=$("mapSource").value;
 for(const r of s.history){
  if(r.kind!==source||r.operation.endsWith("_pulse"))continue;
  const v=source==="scan"?r.channels[2].delta_current_ua:(r.matching_column?r.fine:null);
  if(Number.isFinite(v))map.set(r.row*32+r.col,{v,r});
 }
 const vals=[...map.values()].map(x=>x.v),lo=vals.length?Math.min(...vals):0,hi=vals.length?Math.max(...vals):1;
 cells.forEach((el,i)=>{const x=map.get(i);if(!x){el.style.background="";el.title=`r${Math.floor(i/32)} / c${i%32} · unmeasured`;return;}
  const t=hi===lo?.55:(x.v-lo)/(hi-lo);el.style.background=`rgb(${Math.round(31+53*t)},${Math.round(70+137*t)},${Math.round(87+83*t)})`;el.title=`r${x.r.row}/c${x.r.col} · ${x.v.toFixed(3)} ${source==="scan"?"ΔµA nominal":"fine count"} · ${x.r.time}`;});
 $("mapSummary").textContent=`${map.size} / 1024 cells measured`;$("legendMin").textContent=vals.length?lo.toFixed(2):"—";$("legendMax").textContent=vals.length?hi.toFixed(2):"—";
 $("runTotal").textContent=`${s.jobs.length} runs`;$("journal").replaceChildren();
 for(const j of [...s.jobs].reverse().slice(0,12)){
  const div=document.createElement("div");div.className="journal-row";const left=document.createElement("div"),right=document.createElement("span");
  left.textContent=`${j.parameters.mode.replaceAll("_"," ").toUpperCase()} · r${j.parameters.row}/c${j.parameters.col}`;
  const small=document.createElement("small");small.textContent=`${new Date(j.started).toLocaleTimeString()} · ${j.result_count} captures`;left.append(small);
  const invalidWB=j.state==="completed"&&j.parameters.mode.startsWith("wb_")&&s.history.some(r=>r.job_id===j.id&&r.kind==="wb"&&!r.matching_column);
  right.textContent=invalidWB?"no valid TDC":j.state;right.className=`state-${invalidWB?"unverified":j.state}`;div.append(left,right);div.title=j.error||(invalidWB?"Command transport completed; cell reading is unverified.":"");$("journal").append(div);
 }
 highlight();drawTrace(s.history);drawWaveform(s.history);
}
async function refresh(){try{const r=await fetch("/api/status");render(await r.json());}catch(e){$("connection").textContent="GUI offline";$("message").textContent=e.message;}}
modeChanged();highlight();drawWaveform([]);refresh();setInterval(refresh,1500);window.addEventListener("resize",()=>{if(latest){drawTrace(latest.history);drawWaveform(latest.history);}});
