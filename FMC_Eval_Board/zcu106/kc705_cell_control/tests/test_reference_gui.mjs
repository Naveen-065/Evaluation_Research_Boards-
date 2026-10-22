// Data/command integration tests; browser checks separately verify the layout.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
const root=new URL("../",import.meta.url);
const html=fs.readFileSync(new URL("gui/index.html",root),"utf8");
const source=fs.readFileSync(new URL("gui/app.js",root),"utf8");
const drawn=[];
class Element {
  constructor(){this.value="";this.checked=false;this.children=[];this.style={};this.dataset={};this.classList={toggle(){}};}
  append(...x){this.children.push(...x);}
  replaceChildren(...x){this.children=x;}
  setAttribute(){}
  getBoundingClientRect(){return {width:1000,height:245};}
  getContext(){return new Proxy({measureText:s=>({width:s.length*6}),arc:(...args)=>drawn.push(args)},{get:(o,p)=>o[p]??(()=>{})});}
}
const elements={};
for(const tag of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){
  const el=elements[tag[1]]=new Element();
  el.value=(tag[0].match(/\bvalue="([^"]+)"/)||[])[1]||"";
  el.checked=/\bchecked\b/.test(tag[0]);
}
elements.operationInput.value="read";
const requests=[];
const empty={busy:false,job:null,history:[],jobs:[],message:"Fixture",deployment:{ready:false}};
const context=vm.createContext({
  document:{getElementById(id){assert.ok(elements[id],`Missing ${id}`);return elements[id];},createElement(){return new Element();}},
  window:{devicePixelRatio:1,addEventListener(){}},
  fetch:async(path,options)=>{
    requests.push({path,body:options?.body&&JSON.parse(options.body)});
    return {ok:true,json:async()=>options?{dry_run:true,plan:{fixture:true}}:empty};
  },setInterval(){},console
});
vm.runInContext(source,context);
await new Promise(r=>setImmediate(r));
assert.equal(elements.heatmap.children.length,1024);
assert.equal([...html.matchAll(/<canvas\b/g)].length,1,"Only the reference Read Trace is visible");
assert.ok(!html.includes('id="waveform"'));
for(const mode of ["read","set","reset","cycle","column","array","wb_read","wb_set","wb_reset","wb_cycle"]){
  elements.operationInput.value=mode;elements.operationInput.onchange();
  await elements.commandForm.onsubmit({preventDefault(){}});
  const p=requests.filter(x=>x.path==="/api/run").at(-1).body;
  assert.equal(p.mode,mode);assert.equal(p.dry_run,true);
  assert.equal(p.col,mode.startsWith("wb_")?31:0);
  assert.equal(p.hold,2400);
}
const reset=JSON.parse(fs.readFileSync(new URL("runs/d66f25357c54475ab3585b99f90408eb.json",root),"utf8"));
const rows=reset.results.filter(r=>r.kind==="scan").map(r=>context.adaptScan(r,reset));
const series=context.buildPulseSeries(rows);
assert.equal(series.length,1,"before/pulse/after use one pulse position");
assert.equal(series[0].voltage,2.88,"RESET bars use saved WL settings, not current form inputs");
assert.equal(series[0].beforeCurrent,rows[0].current_uA*2);
assert.equal(series[0].current,rows[2].current_uA*2);
assert.ok(series[0].current < series[0].beforeCurrent,"Saved reset response remains visible");
const pulse=rows[1],after=rows[2];
assert.equal(context.buildPulseSeries([pulse,{...after,job_id:"another-run"}]).length,2,"Never join reads across jobs");
assert.equal(context.buildPulseSeries([pulse,{...after,cellAddress:{row:1,col:0}}]).length,2,"Never join different cells");
const clipped=context.adaptScan({...reset.results[2],clipped:true},reset);
assert.equal(clipped.current_uA,null);
drawn.length=0;
context.drawCurrentTrace(elements.chart.getContext(),[{current:-2},{current:0},{current:null},{current:4}],i=>i,v=>v);
assert.equal(drawn.length,1,"Zero, negative and invalid readings are not drawn on the logarithmic trace");
context.render({...empty,deployment:{ready:true},job:reset,jobs:[reset],history:reset.results});
assert.equal(elements.lastCurrent.textContent,(rows[2].current_uA*2).toFixed(2));
assert.match(elements.traceSummary.textContent,/1 measured point/);
elements.currentMinInput.value="20";elements.currentMinInput.oninput();
elements.currentMaxInput.value="75";elements.currentMaxInput.oninput();
assert.deepEqual({...context.conductancePlotRange()},{min:20,max:75},"Read Trace honors the exact shared Min/Max bounds");
assert.match(elements.traceSummary.textContent,/20–75 µS/);
elements.currentMinInput.value="0";elements.currentMinInput.oninput();
elements.currentMaxInput.value="200";elements.currentMaxInput.oninput();
assert.deepEqual({...context.conductancePlotRange()},{min:0.2,max:200},"Only zero is lifted to the logarithmic display floor");
const wb=JSON.parse(fs.readFileSync(new URL("runs/c1701cc7754a4cafb6dce07c0fc1c297.json",root),"utf8"));
context.render({...empty,deployment:{ready:true},job:wb,jobs:[wb],history:wb.results});
assert.equal(elements.lastCurrent.textContent,"--","WB TDC data is not converted into ADC conductance");
assert.match(elements.tickerText.children[0].textContent,/no valid TDC; unverified/);
console.log("PASS: all ten payloads, saved RESET pulse/read association, job isolation, invalid/log values, WB status, single-chart layout.");
const rampBefore={...reset.results[0],operation:"before_reset__s1_v2300_wl940"};
const rampPulse={...reset.results[1],operation:"reset_pulse"};
const rampAfter={...reset.results[2],operation:"after_reset_limit__s1_v2300_wl940"};
const rampState={...empty,deployment:{ready:true},job:reset,jobs:[reset],history:[rampBefore,rampPulse,rampAfter]};
const rampRows=context.rowsFor(rampState);
const rampSeries=context.buildPulseSeries(rampRows);
assert.equal(rampSeries[0].voltage,0.94,"Ramp bars use the actual step WL, not the ceiling");
assert.equal(rampSeries[0].vcc,2.3);
assert.equal(rampSeries[0].current,rampRows[2].current_uA*2);
context.render(rampState);
assert.match(elements.rampResult.textContent,/RESET: limit reached; target NOT met/);
context.render({...rampState,history:[{...rampAfter,operation:"confirm_reset_10_met__s1_v2300_wl940"}]});
assert.match(elements.rampResult.textContent,/target confirmed \(10 reads\)/);
console.log("PASS: actual ramp rails, pulse/read pairing and truthful target outcomes.");
const connectionFailure={id:"ssh-failed",parameters:{mode:"cycle",row:0,col:0},started:new Date().toISOString(),
  state:"failed",error:"Hardware process exited 255"};
context.render({...empty,deployment:{ready:true},job:connectionFailure,jobs:[connectionFailure]});
assert.match(elements.tickerText.children[0].textContent,/SSH connection to FPGA PC failed/);
assert.match(elements.commandNote.textContent,/review the failed run before repeating a cycle/);
assert.equal(context.jobErrorMessage({...connectionFailure,error:"ADC not healthy"}),"ADC not healthy");
const connectionCheck={...connectionFailure,id:"ssh-checked",parameters:{mode:"check",row:0,col:0},
  state:"completed",error:undefined,status:{adc_healthy:true,clock_present:true,cpu_reset_released:false}};
context.render({...empty,deployment:{ready:true},job:connectionCheck,jobs:[connectionCheck]});
assert.match(elements.tickerText.children[0].textContent,/FPGA reachable; ADC healthy, clock present, CPU held in reset/);
assert.equal(elements.apiSignal.className,"signal good");
context.render({...empty,deployment:{ready:true},job:{...connectionCheck,status:{...connectionCheck.status,adc_healthy:false}},
  jobs:[{...connectionCheck,status:{...connectionCheck.status,adc_healthy:false}}]});
assert.equal(elements.apiSignal.className,"signal bad");
assert.equal(elements.runLogLink.hidden,true,"Older APIs do not expose a broken log link");
context.render({...empty,api_revision:"ssh-startup-retry-v1",deployment:{ready:true},job:connectionFailure,jobs:[connectionFailure]});
assert.equal(elements.runLogLink.href,"/api/run-log/ssh-failed");
assert.equal(elements.runLogLink.hidden,false);
await elements.checkBtn.onclick();
assert.deepEqual(requests.filter(x=>x.path==="/api/run").at(-1).body,{mode:"check",dry_run:false});
assert.equal(elements.followBtn.textContent,"FOLLOWING","Check bench switches away from the old failed run");
console.log("PASS: SSH failure guidance and successful connection status; no automatic programming retry.");
