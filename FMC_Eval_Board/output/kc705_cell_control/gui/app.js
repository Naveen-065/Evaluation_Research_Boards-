"use strict";
// Reference layout and chart: Evaluation_Research_Boards-/api_v1/gui/static.
// This adapter uses only SenseEval's validated /api/run and recorded ADC data.
const $ = id => document.getElementById(id);
const state = {selectedRun: "", manualRun: false, currentMin_uA: 0, currentMax_uA: 200};
const els = {chart: $("chart")};
const CURRENT_DISPLAY_SCALE = 1 / 0.5;
const LOG_DISPLAY_FLOOR_US = 0.2;
let latest = null, previousMode = "read", refreshInFlight = false;
const cells = [];
function scaleCurrent(v) { return Number.isFinite(v) ? v * CURRENT_DISPLAY_SCALE : v; }
function formatVoltage(v) { return Number.isFinite(v) ? v.toFixed(2) : "--"; }
function formatCell(c) { return c ? `r${String(c.row).padStart(2,"0")} c${String(c.col).padStart(2,"0")}` : "--"; }
function cellKey(c) { return c ? `${c.row}_${c.col}` : ""; }
function number(id) { return Number($(id).value); }
function currentRange() { return {min: state.currentMin_uA, max: state.currentMax_uA}; }

// Preserve stage identity so a pulse uses its own following read, never a
// different job's reading or the large current measured during programming.
function rampMetadata(row) {
  const m=String(row.operation).match(/__s(\d+)_v(\d+)_wl(\d+)$/);
  const op=String(row.operation).match(/^(?:before|after|confirm)_(set|reset)/)?.[1];
  return m&&op?{op,step:Number(m[1]),v:Number(m[2])/1000,wl:Number(m[3])/1000}:null;
}
function adaptScan(row, job, ramp=null) {
  const pulse = /^(set|reset)_pulse$/.test(row.operation);
  const operation = pulse ? row.operation.split("_")[0] : "read";
  const label=row.operation.split("__")[0].replace(/_(met|limit)$/,"");
  const stage = /^(before|after|confirm)_/.test(label) ? `read_${label}` : label;
  const ch = row.channels?.[2];
  const ok = !row.clipped && !ch?.clipped && Number.isFinite(ch?.delta_current_ua);
  const p = job?.parameters || {};
  return {
    cellAddress: {row: row.row, col: row.col}, operation, stage, job_id: row.job_id,
    ramp: Boolean(ramp || rampMetadata(row)),
    packet: row.packet, time: row.time, ok,
    current_uA: !pulse && ok ? ch.delta_current_ua : null,
    vcc_set_V: pulse ? ramp?.v??p[`${operation}_v`] : 0.5,
    vcc_wl_set_V: pulse ? ramp?.wl??p[`${operation}_wl`] : 2.5,
  };
}
function rowsFor(s) {
  const jobs = new Map(s.jobs.map(j => [j.id, j]));
  const rails = new Map();
  return s.history.filter(r => r.kind === "scan")
    .sort((a,b)=>Date.parse(a.time)-Date.parse(b.time))
    .map(r => {
      const meta=rampMetadata(r);
      if(meta)rails.set(`${r.job_id}:${meta.op}`,meta);
      return adaptScan(r,jobs.get(r.job_id),rails.get(`${r.job_id}:${r.operation.split("_")[0]}`));
    });
}
function ensureGrid() {
  if (cells.length) return;
  for (let r=0;r<32;r++) for (let c=0;c<32;c++) {
    const el=document.createElement("button");
    el.type="button"; el.className="cell"; el.dataset.key=`${r}_${c}`;
    el.title=`r${r} c${c}: no reading`; el.setAttribute("aria-label",`Select row ${r} column ${c}`);
    el.onclick=()=>{$("rowInput").value=r;$("colInput").value=c; highlight();};
    $("heatmap").append(el);cells.push(el);
  }
}
function highlight() {
  const key=`${number("rowInput")}_${number("colInput")}`;
  cells.forEach(el=>el.classList.toggle("selected",el.dataset.key===key));
}
function colorFor(v,min,max) {
  if (!Number.isFinite(v)) return "#2a2d34";
  const t=(Math.max(min,Math.min(max,v))-min)/(max-min);
  return `hsl(${205-t*170}, 78%, ${38+t*20}%)`;
}
function renderRuns(s) {
  const jobs=[...s.jobs].sort((a,b)=>Date.parse(b.started)-Date.parse(a.started));
  if (!state.manualRun) state.selectedRun=s.job?.id||jobs[0]?.id||"all";
  const signature=jobs.map(j=>`${j.id}:${j.state}`).join("|");
  if ($("runSelect").dataset.signature!==signature) {
    $("runSelect").replaceChildren();
    for (const j of [{id:"all",label:"All saved runs"},...jobs]) {
      const o=document.createElement("option");o.value=j.id;
      o.textContent=j.label||`${new Date(j.started).toLocaleTimeString()} · ${j.parameters.mode.replaceAll("_"," ")} · r${j.parameters.row}/c${j.parameters.col}`;
      o.title=j.id;$("runSelect").append(o);
    }
    $("runSelect").dataset.signature=signature;
  }
  $("runSelect").value=state.selectedRun;
  $("followBtn").textContent=state.manualRun?"PINNED":"FOLLOWING";
  $("followBtn").classList.toggle("active",!state.manualRun);
  $("followBtn").classList.toggle("pinned",state.manualRun);
  $("followBtn").title=state.manualRun?"Click to follow latest run":"Click to pin current run";
}
function renderHeatmap(rows, active) {
  const map=new Map(),{min,max}=currentRange();
  for(const r of rows) if(isRead(r)&&r.ok) map.set(cellKey(r.cellAddress),r);
  for(const el of cells) {
    const r=map.get(el.dataset.key),g=scaleCurrent(r?.current_uA);
    el.style.background=colorFor(g,min,max);
    el.classList.toggle("active",Boolean(latest?.busy&&active&&el.dataset.key===cellKey(active.cellAddress)));
    el.title=r?`${formatCell(r.cellAddress)}: ${g.toFixed(2)} µS estimated\n${r.current_uA.toFixed(3)} µA · SET / R10\n${new Date(r.time).toLocaleString()}`:`${el.dataset.key}: no reading`;
  }
}
function formatApiRow(r) {
  if(r.kind==="wb") return `WB ${r.operation.toUpperCase()} ${formatCell(r)}: ${r.selected} · coarse ${r.coarse}, fine ${r.fine} · ${r.matching_column?"TDC return; uncalibrated":"no valid TDC; unverified"}`;
  const ch=r.channels[2],g=scaleCurrent(ch?.delta_current_ua);
  const value=!r.clipped&&Number.isFinite(g)?`${g.toFixed(2)} µS estimated (${ch.delta_current_ua.toFixed(3)} µA)`:"invalid / clipped ADC result";
  const stage=r.operation.split("__")[0],meta=rampMetadata(r);
  const railText=meta?` · step ${meta.step}, VCC ${meta.v.toFixed(2)} V / WL ${meta.wl.toFixed(2)} V`:"";
  return `${stage.replaceAll("_"," ").toUpperCase()} ${formatCell(r)}: ${r.operation.endsWith("_pulse")?"pulse captured":value}${railText} · ${r.packet}`;
}
function jobErrorMessage(job) {
  if (job?.error === "Hardware process exited 255") {
    // Exit 255 alone cannot distinguish failure before launch from a lost
    // connection during a run. Do not imply that replaying a cycle is safe.
    return "SSH connection to FPGA PC failed (exit 255). Use Check bench; review the failed run before repeating a cycle.";
  }
  return job?.error || "";
}
function render(s) {
  latest=s;renderRuns(s);
  const all=rowsFor(s), selected=s.history.filter(r=>state.selectedRun==="all"||r.job_id===state.selectedRun)
    .sort((a,b)=>Date.parse(a.time)-Date.parse(b.time));
  const rows=all.filter(r=>state.selectedRun==="all"||r.job_id===state.selectedRun);
  const last=rows.at(-1),read=[...rows].reverse().find(r=>isRead(r)&&r.ok);
  const raw=selected.at(-1),job=s.jobs.find(j=>j.id===state.selectedRun);
  $("runLogLink").hidden=!s.api_revision||!job;
  if(job)$("runLogLink").href=`/api/run-log/${job.id}`;
  $("lastCell").textContent=formatCell(read?.cellAddress);
  $("lastCurrent").textContent=read?scaleCurrent(read.current_uA).toFixed(2):"--";
  $("activeCell").textContent=formatCell(raw||job?.parameters);
  $("opCompact").textContent=raw?.operation.replaceAll("_"," ")||job?.parameters.mode.replaceAll("_"," ")||"--";
  $("packetCompact").textContent=raw?.packet||"--";
  $("opDot").className=`dot ${raw?.operation.includes("read")?"read":raw?"program":""}`;
  const checked=job?.parameters.mode==="check"&&job.state==="completed"&&job.status;
  const bad=(raw?.kind==="wb"?!raw.matching_column:Boolean(raw?.clipped))
    ||(checked&&(!checked.adc_healthy||!checked.clock_present));
  $("apiSignal").className=`signal ${bad||job?.state==="failed"?"bad":raw||checked?"good":""}`;
  $("tickerText").replaceChildren();
  const messages=selected.slice(-2).reverse().map(formatApiRow);
  if(s.busy&&(!state.manualRun||state.selectedRun===s.job?.id)) messages.unshift(s.message);
  if(job?.error) messages.unshift(jobErrorMessage(job));
  if(!messages.length&&job?.parameters.mode==="check"&&job.state==="completed") {
    const h=job.status;
    messages.push(`Connection checked: FPGA reachable${h?`; ADC ${h.adc_healthy?"healthy":"NOT healthy"}, clock ${h.clock_present?"present":"MISSING"}, CPU ${h.cpu_reset_released?"running":"held in reset"}`:""}.`);
  }
  for(const [i,msg] of (messages.length?messages:["Waiting for API…","--"]).slice(0,2).entries()) {
    const line=document.createElement("div");line.className=`ticker-line ${i?"muted-line":""}`;
    line.textContent=msg;line.title=msg;$("tickerText").append(line);
  }
  $("commandBtn").disabled=s.busy||(!$("dryRunInput").checked&&!s.deployment.ready);
  $("killBtn").disabled=!s.busy;$("checkBtn").disabled=s.busy;
  $("commandNote").textContent=s.busy?s.message:(!s.deployment.ready?s.deployment.reason:jobErrorMessage(s.job)||s.message);
  $("validationNote").textContent=s.deployment.validation_note||"";
  const outcomes=selected.filter(r=>/_(met|limit)__s/.test(r.operation)).map(r=>{
    const meta=rampMetadata(r);
    return `${meta.op.toUpperCase()}: ${r.operation.includes("_met__")?"target confirmed (10 reads)":"limit reached; target NOT met"}`;
  });
  $("rampResult").textContent=outcomes.join(" · ");
  $("rampResult").hidden=!outcomes.length;
  const summary={history:rows,last};
  state.lastSummary=summary;
  renderHeatmap(all,last);renderChart(summary);highlight();
  const points=buildPulseSeries(rows),valid=points.filter(p=>Number.isFinite(p.current)&&p.current>0);
  $("traceSummary").textContent=`${valid.length} measured point${valid.length===1?"":"s"} · log scale`;
  $("traceNote").textContent=rows.length
    ? "Estimated G = SET-path ΔI / 0.5 V · 56 Ω, gain 7 nominal · pulse bars: requested WL voltage. Nonpositive readings are omitted from the log plot."
    : raw?.kind==="wb"?"This WB run has no ADC conductance trace. UART/TDC results appear in API return. Select a scan run to view its Read Trace.":"Run Read or select a saved scan run to view measured data.";
}
function modeChanged() {
  const mode=$("operationInput").value,wb=mode.startsWith("wb_");
  if(wb&&!previousMode.startsWith("wb_")){$("rowInput").value=0;$("colInput").value=31;}
  if(!wb&&previousMode.startsWith("wb_")){$("rowInput").value=0;$("colInput").value=0;}
  previousMode=mode;
  $("pulseSettings").hidden=wb||!["set","reset","cycle"].includes(mode);
  $("cycleField").hidden=!mode.includes("cycle");
  $("wbNote").hidden=!wb;highlight();
  $("rampNote").hidden=wb||!["set","reset","cycle"].includes(mode);
}
function parameters() {
  return {mode:$("operationInput").value,row:number("rowInput"),col:number("colInput"),
    set_v:number("set_v"),set_wl:number("set_wl"),reset_v:number("reset_v"),reset_wl:number("reset_wl"),
    hold:Math.round(number("pulse_ms")*2000),cycles:number("cycles"),dry_run:$("dryRunInput").checked};
}
async function post(path,body) {
  const res=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data=await res.json();if(!res.ok)throw Error(data.error||res.statusText);return data;
}
async function refresh() {
  if(refreshInFlight)return;refreshInFlight=true;
  try {
    const res=await fetch("/api/status",{cache:"no-store"});
    if(!res.ok)throw Error(`Status request failed (${res.status})`);
    render(await res.json());
  }catch(e){$("commandNote").textContent=`GUI offline: ${e.message}`;$("apiSignal").className="signal bad";$("commandBtn").disabled=true;}
  finally{refreshInFlight=false;}
}
// Reference chart functions are included below by the local source-copy step.

function renderChart(summary) {
  const canvas = els.chart;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * dpr);
  canvas.height = Math.floor(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);
  ctx.fillStyle = "#111318";
  ctx.fillRect(0, 0, rect.width, rect.height);

  const pulses = buildPulseSeries(summary?.history || []);
  if (!pulses.length) { ctx.fillStyle="#9aa4af"; ctx.font="13px system-ui"; ctx.fillText("No scan reads in this run",24,50); return; }

  const padLeft = 72;
  const padRight = 18;
  const padTop = 24;
  const gap = 14;
  const topH = Math.max(120, rect.height * 0.56);
  const bottomY = padTop + topH + gap;
  const bottomH = rect.height - bottomY - 28;
  const plotW = rect.width - padLeft - padRight;
  const xFor = (index) => pulses.length === 1 ? padLeft + plotW / 2 : padLeft + plotW * index / (pulses.length - 1);

  const { min: requestedCurrentMin, max: requestedCurrentMax } = currentRange();
  // Log plots cannot represent zero or negative conductance. Keep the
  // user-selected range unchanged, but use the 0.2 uS display floor that
  // corresponds to 0.1 uA at the fixed 0.5 V read voltage.
  const currentMin = Math.max(LOG_DISPLAY_FLOOR_US, requestedCurrentMin);
  const currentMax = Math.max(requestedCurrentMax, currentMin * 10);
  const logCurrentMin = Math.log10(currentMin);
  const logCurrentSpan = Math.log10(currentMax) - logCurrentMin;
  const yCurrent = (value) => {
    const clamped = Math.max(currentMin, Math.min(currentMax, value));
    return padTop + topH - ((Math.log10(clamped) - logCurrentMin) / logCurrentSpan) * topH;
  };

  const voltageMax = Math.max(2, ...pulses.map((item) => Math.abs(item.voltage || 0)));
  const yZero = bottomY + bottomH / 2;
  const yVoltage = (value) => yZero - (value / voltageMax) * (bottomH / 2 - 6);

  drawPhaseBands(ctx, pulses, xFor, padLeft, plotW, bottomY, bottomH);
  drawAxes(ctx, padLeft, padTop, plotW, topH, bottomY, bottomH, rect.width, rect.height);
  drawLogCurrentGrid(ctx, padLeft, plotW, yCurrent, currentMin, currentMax);
  drawTransition(ctx, pulses, xFor, padTop, topH, bottomY, bottomH);
  drawCurrentTrace(ctx, pulses, xFor, yCurrent);
  drawVoltageBars(ctx, pulses, xFor, yZero, yVoltage);
  drawActiveVoltageBadge(ctx, summary?.last, padLeft, plotW, bottomY);
  drawLabels(ctx, pulses, currentMin, currentMax, voltageMax, padLeft, padTop, topH, bottomY, bottomH, rect.height);
}

function isRead(row) {
  return row?.operation === "read" || String(row?.stage || "").startsWith("read");
}

function isBeforeReadForPulse(read, pulse) {
  const match = String(read?.stage || "").match(/(?:^|_)read_before_(set|reset)$/);
  return Boolean(match && isRead(read) && read.ok !== false && pulse?.ok !== false
    && read.job_id === pulse?.job_id && pulse?.operation === match[1] && read.cellAddress && pulse.cellAddress
    && cellKey(read.cellAddress) === cellKey(pulse.cellAddress));
}

function buildPulseSeries(history) {
  const pulses = [];
  let pending = null;
  const rows = history.filter((row) => row?.cellAddress);
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    // Match the old pulse + after-read spacing. A paired before-read is
    // metadata for the upcoming pulse, not another X-axis position. Keep an
    // unpaired/latest before-read visible until that pulse actually exists.
    if (isBeforeReadForPulse(row, rows[index + 1])) continue;
    if (!isRead(row)) {
      pending = {
        cell: row.cellAddress,
        job_id: row.job_id,
        op: row.operation,
        packet: row.packet,
        voltage: signedVoltage(row),
        wl: row.vcc_wl_set_V,
        vcc: row.vcc_set_V,
        current: null,
        beforeCurrent: isBeforeReadForPulse(rows[index - 1], row)
          ? scaleCurrent(rows[index - 1].current_uA) : null,
      };
      pulses.push(pending);
      continue;
    }
    if (pending && pending.job_id === row.job_id && pending.current === null
      && cellKey(pending.cell) === cellKey(row.cellAddress)
      && !/(?:^|_)read_before_(set|reset)$/.test(String(row.stage || ""))) {
      pending.current = scaleCurrent(row.current_uA);
      pending.readStage = row.stage;
    } else {
      pulses.push({
        cell: row.cellAddress,
        op: "read",
        packet: row.packet,
        voltage: 0,
        current: scaleCurrent(row.current_uA),
      });
    }
  }
  // Keep a full bounded ramp cycle visible, including its initial confirmations.
  return pulses.slice(rows.some(row=>row.ramp)?-512:-80);
}

function signedVoltage(row) {
  const value = Number.isFinite(row.vcc_wl_set_V) ? row.vcc_wl_set_V : row.vcc_set_V;
  if (!Number.isFinite(value)) return 0;
  return row.operation === "set" ? -value : value;
}

function drawAxes(ctx, left, top, width, topH, bottomY, bottomH, totalW, totalH) {
  ctx.strokeStyle = "#d9dee6";
  ctx.lineWidth = 1.2;
  ctx.strokeRect(left, top, width, topH);
  ctx.strokeRect(left, bottomY, width, bottomH);
  ctx.strokeStyle = "#8b949e";
  ctx.beginPath();
  ctx.moveTo(left, bottomY + bottomH / 2);
  ctx.lineTo(left + width, bottomY + bottomH / 2);
  ctx.stroke();
  ctx.fillStyle = "#d9dee6";
  ctx.font = "12px system-ui";
  ctx.save();
  ctx.translate(14, top + topH / 2 + 34);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("G (µS, log)", 0, 0);
  ctx.restore();
  ctx.save();
  ctx.translate(14, bottomY + bottomH / 2 + 28);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Voltage (V)", 0, 0);
  ctx.restore();
  ctx.fillText("Pulse", totalW / 2 - 12, totalH - 8);
}

function drawLogCurrentGrid(ctx, left, width, yCurrent, currentMin, currentMax) {
  const firstDecade = Math.floor(Math.log10(currentMin));
  const lastDecade = Math.ceil(Math.log10(currentMax));
  const ticks = [];
  for (let decade = firstDecade; decade <= lastDecade; decade += 1) {
    const base = 10 ** decade;
    for (const multiplier of [1, 2, 5]) {
      const value = multiplier * base;
      if (value >= currentMin - 1e-12 && value <= currentMax + 1e-12) {
        ticks.push({ value, major: multiplier === 1 });
      }
    }
  }

  ctx.save();
  ctx.font = "11px system-ui";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (const tick of ticks) {
    const y = yCurrent(tick.value);
    ctx.strokeStyle = tick.major ? "rgba(154, 164, 175, 0.34)" : "rgba(154, 164, 175, 0.16)";
    ctx.lineWidth = tick.major ? 1 : 0.7;
    ctx.setLineDash(tick.major ? [] : [2, 4]);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + width, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = tick.major ? "#d7dde3" : "#9aa4af";
    const label = tick.value < 1 ? tick.value.toFixed(1) : Number(tick.value.toPrecision(3)).toString();
    ctx.fillText(label, left - 8, y);
  }
  ctx.restore();
}

function drawThresholds(ctx, left, width, yCurrent, currentMin, currentMax, thresholds) {
  const visible = [
    ["SET", Number(thresholds.set), "#ff3b4f"],
    ["RESET", Number(thresholds.reset), "#6ab6df"],
  ].filter(([, rawThreshold]) => Number.isFinite(rawThreshold));
  const usedY = [];
  visible.forEach(([label, rawThreshold, color]) => {
    const threshold = rawThreshold;
    if (threshold < currentMin || threshold > currentMax) return;
    const y = yCurrent(threshold);
    let labelY = y - 7;
    for (const prevY of usedY) {
      if (Math.abs(labelY - prevY) < 16) labelY = prevY + 16;
    }
    usedY.push(labelY);
    ctx.strokeStyle = color;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + width, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = "12px system-ui";
    const text = `${label} ${threshold.toFixed(2)} uS`;
    const textW = ctx.measureText(text).width;
    const textX = left + width - textW - 8;
    ctx.fillStyle = "rgba(17, 19, 24, 0.88)";
    ctx.fillRect(textX - 4, labelY - 11, textW + 8, 15);
    ctx.fillStyle = color;
    ctx.fillText(text, textX, labelY);
  });
}

function drawTransition(ctx, pulses, xFor, top, topH, bottomY, bottomH) {
  const index = pulses.findIndex((item, i) => item.op === "reset" && pulses.slice(0, i).some((prev) => prev.op === "set"));
  if (index < 0) return;
  const x = xFor(index);
  ctx.strokeStyle = "#d9dee6";
  ctx.setLineDash([6, 5]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottomY + bottomH);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawPhaseBands(ctx, pulses, xFor, left, width, bottomY, bottomH) {
  const bands = [];
  let start = null;
  let op = null;
  pulses.forEach((item, index) => {
    const nextOp = item.op === "set" || item.op === "reset" ? item.op : op;
    if (nextOp !== op) {
      if (op && start !== null) bands.push({ op, start, end: index - 1 });
      op = nextOp;
      start = index;
    }
  });
  if (op && start !== null) bands.push({ op, start, end: pulses.length - 1 });

  bands.forEach((band) => {
    const x1 = band.start <= 0 ? left : xFor(band.start) - 4;
    const x2 = band.end >= pulses.length - 1 ? left + width : xFor(band.end) + 4;
    ctx.fillStyle = band.op === "set" ? "rgba(255, 59, 79, 0.08)" : "rgba(106, 182, 223, 0.1)";
    ctx.fillRect(x1, bottomY, Math.max(2, x2 - x1), bottomH);
    ctx.fillStyle = band.op === "set" ? "#ff6c79" : "#8bcced";
    ctx.font = "600 11px system-ui";
    ctx.fillText(band.op.toUpperCase(), Math.min(x1 + 6, left + width - 44), bottomY + 14);
  });
}

function drawCurrentTrace(ctx, pulses, xFor, yCurrent) {
  const points = pulses
    .map((item, index) => ({ ...item, index }))
    .filter((item) => Number.isFinite(item.current) && item.current > 0);
  ctx.strokeStyle = "#4fb3ad";
  ctx.lineWidth = 1.7;
  ctx.beginPath();
  points.forEach((item, i) => {
    const x = xFor(item.index);
    const y = yCurrent(item.current);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  for (const item of points) {
    const x = xFor(item.index);
    const y = yCurrent(item.current);
    ctx.fillStyle = "#111318";
    ctx.strokeStyle = "#6bd2cc";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

function drawVoltageBars(ctx, pulses, xFor, yZero, yVoltage) {
  const barW = Math.max(2, Math.min(8, 460 / Math.max(20, pulses.length)));
  pulses.forEach((item, index) => {
    if (!Number.isFinite(item.voltage) || item.voltage === 0) return;
    const x = xFor(index);
    const y = yVoltage(item.voltage);
    ctx.strokeStyle = item.op === "set" ? "#ff3b4f" : "#6ab6df";
    ctx.lineWidth = barW;
    ctx.beginPath();
    ctx.moveTo(x, yZero);
    ctx.lineTo(x, y);
    ctx.stroke();
  });
}

function drawActiveVoltageBadge(ctx, row, left, width, bottomY) {
  if (!row || !(row.operation === "set" || row.operation === "reset")) return;
  const op = row.operation.toUpperCase();
  const color = row.operation === "set" ? "#ff6c79" : "#8bcced";
  const text = `${op}  Vcc ${formatVoltage(row.vcc_set_V)}V  WL ${formatVoltage(row.vcc_wl_set_V)}V`;
  ctx.font = "600 12px system-ui";
  const textW = ctx.measureText(text).width;
  const x = left + width - textW - 10;
  const y = bottomY + 17;
  ctx.fillStyle = "rgba(17, 19, 24, 0.9)";
  ctx.fillRect(x - 6, y - 13, textW + 12, 18);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

function drawLabels(ctx, pulses, currentMin, currentMax, voltageMax, left, top, topH, bottomY, bottomH, totalH) {
  const cell = pulses.find((item) => item.cell)?.cell;
  ctx.fillStyle = "#f3f5f7";
  ctx.font = "600 13px system-ui";
  const multi = new Set(pulses.map(p=>cellKey(p.cell))).size > 1;
  ctx.fillText(multi ? "Multiple cells" : cell ? `Cell (${cell.row},${cell.col})` : "Cell", left, 16);
  ctx.font = "12px system-ui";
  ctx.fillStyle = "#9aa4af";
  ctx.textAlign = "right";
  ctx.fillText(`+${voltageMax.toFixed(2)}V`, left - 8, bottomY + 11);
  ctx.fillText("0.00V", left - 8, bottomY + bottomH / 2 + 4);
  ctx.fillText(`-${voltageMax.toFixed(2)}V`, left - 8, bottomY + bottomH - 4);
  ctx.textAlign = "left";
  ctx.fillStyle = "#ff3b4f";
  ctx.fillRect(left + 250, totalH - 42, 28, 5);
  ctx.fillText("SET", left + 286, totalH - 36);
  ctx.fillStyle = "#6ab6df";
  ctx.fillRect(left + 340, totalH - 42, 28, 5);
  ctx.fillText("RESET", left + 376, totalH - 36);
}


// UI bindings: all commands pass through the existing SenseEval API.
$("commandForm").onsubmit=async e=>{
  e.preventDefault();$("commandBtn").disabled=true;
  try{
    const data=await post("/api/run",parameters());
    $("preview").hidden=!data.dry_run;
    if(data.dry_run){
      if(["set","reset","cycle"].includes(data.parameters?.mode)){
        data.plan.program_operations_meaning="Ramp phases; each may contain multiple pulses";
        data.plan.scan_ramp={set_target_uA:35,reset_target_uA:5,confirmation_reads:10,
          hard_rail_limit_v:3,read_rails_v:[0.5,2.5],controls:"VCC/WL fields are sweep ceilings; stop when confirmed or exhausted"};
      }
      $("previewText").textContent=JSON.stringify(data,null,2);
    }
    else {state.manualRun=false;state.selectedRun=data.job_id;}
    await refresh();
  }catch(e){$("commandNote").textContent=e.message;$("commandBtn").disabled=false;}
};
$("killBtn").onclick=async()=>{
  try{await post("/api/cancel",{});$("commandNote").textContent="Stopping; waiting for read-profile restoration.";}
  catch(e){$("commandNote").textContent=e.message;}
};
$("checkBtn").onclick=async()=>{
  try{
    const data=await post("/api/run",{mode:"check",dry_run:false});
    state.manualRun=false;state.selectedRun=data.job_id;
    $("preview").hidden=true;await refresh();
  }
  catch(e){$("commandNote").textContent=e.message;}
};
$("closePreview").onclick=()=>{$("preview").hidden=true;};
$("operationInput").onchange=modeChanged;
$("dryRunInput").onchange=()=>latest&&render(latest);
$("rowInput").onchange=highlight;$("colInput").onchange=highlight;
$("runSelect").onchange=()=>{state.manualRun=true;state.selectedRun=$("runSelect").value;if(latest)render(latest);};
$("followBtn").onclick=()=>{state.manualRun=!state.manualRun;if(latest)render(latest);};
for(const [part,ids] of [["min",["currentMinRange","currentMinInput"]],["max",["currentMaxRange","currentMaxInput"]]]){
  for(const id of ids)$(id).oninput=()=>{
    const v=number(id);if(!Number.isFinite(v))return;
    if(part==="min")state.currentMin_uA=Math.max(0,Math.min(state.currentMax_uA-5,v));
    else state.currentMax_uA=Math.min(300,Math.max(state.currentMin_uA+5,v));
    $("currentMinRange").value=$("currentMinInput").value=state.currentMin_uA;
    $("currentMaxRange").value=$("currentMaxInput").value=state.currentMax_uA;
    if(latest)render(latest);
  };
}
ensureGrid();modeChanged();refresh();setInterval(refresh,1500);
window.addEventListener("resize",()=>{if(state.lastSummary)renderChart(state.lastSummary);});
