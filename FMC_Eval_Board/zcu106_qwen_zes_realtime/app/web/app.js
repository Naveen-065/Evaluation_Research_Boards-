"use strict";

const $ = id => document.getElementById(id);
const state = {capabilities: null, protection: null, memoryMap: null, sessionId: null, stream: null, mapTimer: null, mapWatchTimer: null};
const mapCells = [];

function setClass(element, kind) {
  element.classList.remove("neutral", "good", "bad", "warning");
  element.classList.add(kind);
}
function shortHash(value) { return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "—"; }
function log(message) {
  const row = document.createElement("div");
  row.textContent = `${new Date().toLocaleTimeString()} · ${message}`;
  $("eventLog").prepend(row);
  while ($("eventLog").children.length > 40) $("eventLog").lastElementChild.remove();
}
async function api(path, body) {
  const options = body === undefined ? {cache: "no-store"} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function protectionBusy(busy) {
  for (const id of ["initializeBtn", "injectBtn", "checkBtn", "repairBtn"]) $(id).disabled = busy;
}
function renderProtection(p) {
  state.protection = p;
  if (p.initialized && ["reference", "board"].includes(p.edac_mode)) {
    $("edacMode").value = p.edac_mode;
  }
  const real = p.runtime?.real_model;
  $("tensorName").textContent = p.tensor?.name || "—";
  $("tensorName").title = p.tensor ? `${p.tensor.dtype} · ${p.tensor.device} · ${p.tensor.shape?.join("×")}` : "";
  $("injectedBits").textContent = `${p.last_injection?.injected_bits || 0} bits`;
  $("decoderResult").textContent = p.last_check?.outcome || "—";
  $("baselineSha").textContent = shortHash(p.baseline_sha256);
  $("baselineSha").title = p.baseline_sha256 || "";
  $("currentSha").textContent = shortHash(p.current_sha256);
  $("currentSha").title = p.current_sha256 || "";
  $("paritySha").textContent = p.parity_bytes ? `${p.parity_bytes} B · ${shortHash(p.parity_sha256)}` : "—";
  if (!p.initialized) {
    $("shaBadge").textContent = "Not initialized"; setClass($("shaBadge"), "neutral");
  } else if (p.sha_verified) {
    $("shaBadge").textContent = "SHA verified"; setClass($("shaBadge"), "good");
  } else {
    $("shaBadge").textContent = real ? "Live tensor differs" : "Demo block differs"; setClass($("shaBadge"), "warning");
  }
  let message = p.initialized ? `${p.edac_mode} parity protects ${real ? "a live Qwen tensor" : "the synthetic demo block"}.` : "Initialize protection to begin.";
  if (p.last_check) message += ` ${p.last_check.outcome}; ${p.last_check.observed_bit_errors_vs_sha_baseline} bit error(s) vs baseline; parity: ${p.last_check.parity_source}.`;
  $("protectionMessage").textContent = message;
  if (state.memoryMap) renderMap(state.memoryMap);
}
function renderCapabilities(c) {
  state.capabilities = c;
  const runtime = c.runtime;
  $("runtimeChip").textContent = runtime.real_model ? "Qwen · local" : "Runtime · demo";
  setClass($("runtimeChip"), runtime.real_model ? "good" : "warning");
  $("runtimeDetail").textContent = runtime.label;
  $("runtimeBanner").hidden = runtime.real_model;
  $("runtimeBanner").textContent = runtime.real_model ? "" : `${runtime.label}. ${runtime.limitation}`;
  const board = c.edac_modes.board;
  const targetLabel = board.target_label || board.info?.target_label || "ZES relay host";
  const executionKind = board.execution_kind || (board.real_board === false ? "vm" : "board");
  const executionLabel = executionKind === "vm" ? "VM" : "embedded board";
  $("edacChip").textContent = board.available
    ? `ZES · ${executionLabel} · connected · ${targetLabel}`
    : `ZES · ${executionLabel} · offline`;
  setClass($("edacChip"), board.available ? "good" : "warning");
  $("boardEdacOption").textContent = `${targetLabel} · vendor ZES1 · ${executionLabel}`;
  $("boardEdacOption").disabled = !board.available;
  if (!board.available && $("edacMode").value === "board") $("edacMode").value = "reference";
  $("relayDetail").textContent = board.available
    ? `${targetLabel} · ${executionLabel} execution · ${board.info.protocol} · ${board.info.vendor_version || "connected"}`
    : `${targetLabel} · ${executionLabel} execution · ${board.info?.error || "Not configured"}`;
  const hw = c.hardware;
  const fpgaLocked = hw.tools_ready && !hw.exclusive_mode;
  $("fpgaChip").textContent = hw.configured
    ? "FPGA direct · ready"
    : (fpgaLocked ? "FPGA direct · locked" : "FPGA tools · incomplete");
  setClass($("fpgaChip"), hw.configured ? "good" : (fpgaLocked ? "warning" : "bad"));
  $("senseDetail").textContent = hw.configured
    ? `Exclusive direct bitmap Tcl · legacy port 8771 must remain closed`
    : (!hw.exclusive_mode
      ? `Direct FPGA disabled · relaunch with -ExclusiveHardware after stopping port 8771`
      : `Missing Vivado or bitmap Tcl; probes ${hw.probes_file_present ? "present" : "not built"}`);
  renderProtection(c.protection);
  const percent = c.fault_model.one_bit_percent;
  $("berResolution").textContent = `1 bit = ${percent.toFixed(6)}% of this block. Actual BER is quantized to whole bits.`;
}
async function refreshCapabilities() {
  try { renderCapabilities(await api("/api/capabilities")); }
  catch (error) { log(error.message); $("runtimeBanner").hidden = false; $("runtimeBanner").textContent = error.message; }
}
async function protectionAction(path, body, label) {
  protectionBusy(true); $("protectionMessage").textContent = `${label}…`;
  try {
    const p = await api(path, body); renderProtection(p);
    if (path.endsWith("/initialize")) await refreshMap();
    log(`${label} complete.`);
  }
  catch (error) { $("protectionMessage").textContent = error.message; log(error.message); }
  finally { protectionBusy(false); }
}

function initMemoryMap() {
  for (let index = 0; index < 1024; index++) {
    const cell = document.createElement("div");
    cell.className = "memory-cell unknown";
    cell.setAttribute("role", "gridcell"); cell.dataset.index = index;
    cell.title = `r${Math.floor(index / 32)} c${index % 32} · index ${index} · no readback`;
    $("memoryMap").append(cell); mapCells.push(cell);
  }
}
function renderMap(map) {
  state.memoryMap = map;
  const physicalUsable = Boolean(map.physical_parity?.usable_for_check_repair);
  $("physicalParityOption").disabled = !physicalUsable;
  if (!physicalUsable && $("paritySource").value === "physical") $("paritySource").value = "host";
  const running = ["submitted", "running", "cancelling"].includes(map.state);
  const programRunning = ["submitted", "running"].includes(map.bitmap_job?.state);
  const initialized = Boolean(state.protection?.initialized);
  const toolsReady = Boolean(state.capabilities?.hardware?.configured);
  $("readMapBtn").disabled = running || programRunning || !initialized || !toolsReady;
  $("simulateMapBtn").disabled = running || programRunning || !initialized;
  $("programMapBtn").disabled = running || programRunning || !initialized || !toolsReady;
  $("cancelMapBtn").disabled = !running || map.source === "bitmap-direct-readback";
  const progress = programRunning ? map.bitmap_job : map;
  $("mapProgress").max = progress.total || 1024;
  $("mapProgress").value = progress.completed || 0;
  $("mapProgressText").textContent = `${progress.completed || 0} / ${progress.total || 1024}`;
  let mapMessage = (programRunning ? map.bitmap_job.message : map.message) || map.state;
  if (!programRunning && map.physical_parity?.available) {
    mapMessage += map.physical_parity.sha_verified
      ? " Physical parity SHA matches the encoded 72-byte record."
      : " Physical parity SHA mismatch: EDAC use is blocked.";
  }
  $("mapMessage").textContent = mapMessage;
  const simulation = map.source === "simulation";
  $("mapSource").textContent = simulation ? "SIMULATION · no FPGA read" : (map.source === "bitmap-program-readback" ? "Program readback" : (map.source?.includes("readback") ? "Hardware readback" : "No readback"));
  const issueCount = Number(map.mismatches || 0) + Number(map.unknown || 0) + Number(map.failed || 0);
  setClass($("mapSource"), simulation ? "warning" : (map.state === "failed" ? "bad" : (map.state === "completed" ? (issueCount ? "warning" : "good") : "neutral")));
  const byIndex = new Map((Array.isArray(map.cells) ? map.cells : []).map(cell => [cell.index, cell]));
  for (let index = 0; index < 1024; index++) {
    const cell = mapCells[index];
    const data = byIndex.get(index);
    if (!data) {
      cell.className = "memory-cell unknown"; cell.textContent = "";
      cell.title = `r${Math.floor(index / 32)} c${index % 32} · index ${index} · no current readback`;
      cell.setAttribute("aria-label", cell.title); continue;
    }
    cell.className = `memory-cell ${data.classification}`;
    // A visible digit is evidence, not intent.  Keep the requested parity bit
    // in the tooltip, but show 0/1 only after measured (or explicitly
    // simulated) readback supplied an observed bit.
    cell.textContent = data.observed_bit === 0 || data.observed_bit === 1
      ? String(data.observed_bit) : "";
    const current = Number.isFinite(data.current_ua) ? `${Number(data.current_ua).toFixed(3)} µA` : "unknown current";
    cell.title = `r${data.row} c${data.col} · index ${data.index}\n${data.role} · logical parity ${data.logical_bit ?? "—"} · observed ${data.observed_bit ?? "—"}\n${current} · ${data.classification}\nsource: ${data.source || "no readback"}`;
    cell.setAttribute("aria-label", cell.title.replaceAll("\n", ", "));
  }
  if ((running || programRunning) && !state.mapTimer) state.mapTimer = setInterval(refreshMap, 1500);
  if (!running && !programRunning && state.mapTimer) { clearInterval(state.mapTimer); state.mapTimer = null; }
}
async function refreshMap() {
  try { renderMap(await api("/api/memory-map")); }
  catch (error) { $("mapMessage").textContent = error.message; }
}

function closeStream() { if (state.stream) state.stream.close(); state.stream = null; }
function startStream(path) {
  closeStream();
  const source = new EventSource(path); state.stream = source;
  source.addEventListener("token", event => { const data = JSON.parse(event.data); $("response").textContent += data.token; });
  source.addEventListener("hardware", event => { const data = JSON.parse(event.data); $("probeDetail").textContent = data.message || data.state; });
  source.addEventListener("hardware_complete", event => { const data = JSON.parse(event.data); $("probeDetail").textContent = data.error || `${data.state} · ${data.outputs?.length || 0} columns`; });
  source.addEventListener("error", event => {
    if (event.data) { const data = JSON.parse(event.data); $("inferenceMessage").textContent = data.message; log(data.message); }
  });
  source.addEventListener("complete", event => {
    const data = JSON.parse(event.data); $("streamState").textContent = data.state; setClass($("streamState"), data.state === "completed" ? "good" : "warning");
    $("generateBtn").disabled = false; $("cancelBtn").disabled = true; $("tokenMeta").textContent = data.state; closeStream();
  });
  source.onerror = () => { if (state.stream) $("inferenceMessage").textContent = "Stream reconnecting…"; };
}

$("initializeBtn").onclick = () => protectionAction("/api/protection/initialize", {edac_mode: $("edacMode").value}, "Encoding parity");
$("injectBtn").onclick = () => protectionAction("/api/protection/inject", {error_percent: Number($("berNumber").value), seed: Number($("seed").value)}, "Injecting exact BER");
$("checkBtn").onclick = () => protectionAction("/api/protection/check", {threshold: Number($("threshold").value), parity_source: $("paritySource").value}, "Checking without mutation");
$("repairBtn").onclick = () => protectionAction("/api/protection/repair", {threshold: Number($("threshold").value), parity_source: $("paritySource").value}, "Repairing and verifying SHA");
$("berRange").oninput = () => { $("berNumber").value = $("berRange").value; };
$("berNumber").oninput = () => { const value = Number($("berNumber").value); if (value <= 5) $("berRange").value = value; };
$("promptForm").onsubmit = async event => {
  event.preventDefault(); closeStream(); $("response").textContent = "";
  $("generateBtn").disabled = true; $("cancelBtn").disabled = false;
  $("streamState").textContent = "Streaming"; setClass($("streamState"), "warning");
  $("tokenMeta").textContent = "Live SSE"; $("probeDetail").textContent = $("hardwareProbe").checked ? "Starting" : "Off";
  try {
    const data = await api("/api/inference", {prompt: $("prompt").value, seed: Number($("seed").value),
      max_new_tokens: Number($("maxTokens").value), hardware_mode: $("hardwareProbe").checked ? "probe" : "off"});
    state.sessionId = data.session_id; startStream(data.events); log(`Inference ${data.session_id.slice(0, 8)} started.`);
  } catch (error) {
    $("inferenceMessage").textContent = error.message; $("generateBtn").disabled = false; $("cancelBtn").disabled = true;
  }
};
$("cancelBtn").onclick = async () => { if (state.sessionId) try { await api(`/api/inference/${state.sessionId}/cancel`, {}); } catch (error) { log(error.message); } };
$("readMapBtn").onclick = async () => { try { renderMap(await api("/api/memory-map/read", {simulation: false})); log("Physical 1Kbit read submitted."); } catch (error) { $("mapMessage").textContent = error.message; } };
$("programMapBtn").onclick = async () => {
  if (!confirm("Program the 576 encoded parity cells now? Physical cells 0..575 may receive SET/RESET pulses; spares 576..1023 are untouched.")) return;
  try { renderMap(await api("/api/memory-map/program", {})); log("Direct parity bitmap programming submitted."); }
  catch (error) { $("mapMessage").textContent = error.message; }
};
$("simulateMapBtn").onclick = async () => { try { renderMap(await api("/api/memory-map/read", {simulation: true})); log("Explicit simulation map requested; no FPGA command."); } catch (error) { $("mapMessage").textContent = error.message; } };
$("cancelMapBtn").onclick = async () => { try { renderMap(await api("/api/memory-map/cancel", {})); } catch (error) { $("mapMessage").textContent = error.message; } };
$("refreshBtn").onclick = async () => { await refreshCapabilities(); await refreshMap(); };

initMemoryMap(); refreshCapabilities(); refreshMap();
// Keep a low-rate discovery poll alive so jobs submitted by the local API (or
// another browser tab) appear without requiring a reload. renderMap adds the
// faster 1.5 s poll only while a read/program operation is active.
state.mapWatchTimer = setInterval(refreshMap, 5000);
