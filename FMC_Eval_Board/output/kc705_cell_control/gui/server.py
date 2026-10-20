"""Loopback-only GUI/API. Jobs use the same validated hardware runner."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ssh_transport import CONNECT_TIMEOUT_SECONDS, MAX_CONNECT_ATTEMPTS, RemoteRun

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model import DEFAULTS, MODES, now, validate, plan, decode_scan, decode_wb, decode_trace
HERE=Path(__file__).resolve().parent
SSH=["ssh","-o","BatchMode=yes","-o",f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
     "-o","ConnectionAttempts=1","-o","ServerAliveInterval=15","-o","ServerAliveCountMax=3",
     "-o","HostKeyAlias=100.86.99.88",
     "-J","ubuntu-24-04@100.98.132.51","fpga@10.0.2.2"]
REMOTE="C:/Users/fpga.DESKTOP-CVDV1JP/kc705_cell_control"
VIVADO="C:/AMDDesignTools2/2026.1/Vivado/bin/vivado.bat"
LOCK=threading.RLock()
STATE={"busy":False,"job":None,"history":[],"jobs":[],"message":"Check connection to begin."}
API_REVISION="ssh-startup-retry-v1"

def update_message(message):
    with LOCK: STATE["message"]=message

def require_recovery(job, reason):
    job["requires_recovery"]=True
    state=deployment()
    state.update(ready=False,reason=reason,recovery_job=job["id"])
    (ROOT/"evidence/deployment.json").write_text(json.dumps(state,indent=2))

def deployment():
    p=ROOT/"evidence/deployment.json"
    if not p.exists(): return {"ready":False,"reason":"Full-control image is being built and verified."}
    data=json.loads(p.read_text())
    for name,digest in data.get("hashes",{}).items():
        path=ROOT/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            return {"ready":False,"reason":"Deployment files differ from recorded hardware image."}
    return data

def save_result(job,result):
    result["job_id"]=job["id"]
    with LOCK:
        job["results"].append(result)
        STATE["history"].append(result)
        STATE["message"]=f'{result["kind"].upper()} r{result["row"]}/c{result["col"]}: {result["operation"]}'
    with (ROOT/"runs"/f'{job["id"]}.jsonl').open("a",encoding="utf-8") as f:
        f.write(json.dumps(result)+"\n")

def worker(job):
    p=job["parameters"]; ident=job["id"]
    args=[p[k] for k in ("mode","row","col","set_v","set_wl","reset_v","reset_wl","hold","cycles")]+[ident]
    cmd=SSH+[VIVADO,"-mode","batch","-source",REMOTE+"/control.tcl",
        "-log",REMOTE+f"/evidence/{ident}.log","-journal",REMOTE+f"/evidence/{ident}.jou",
        "-tclargs",*map(str,args)]
    wb={}; errors=[]; complete=False
    try:
        with (ROOT/"runs"/f"{ident}.log").open("w",encoding="utf-8") as log:
            remote=RemoteRun(cmd,job,log,update_message)
            for line in remote:
                if line.startswith(("ERROR:", "RESTORE_FAILED", "Known KC705 JTAG cable not found",
                                    "Controller timeout", "Controller fault", "ADC not healthy")):
                    errors.append(line.strip())
                if line.startswith("EVENT "):
                    with LOCK: STATE["message"]=line.strip()[6:]
                if line.startswith("CONTROL_STATUS "):
                    _,h0,h1=line.split(); a,b=int(h0,16),int(h1,16)
                    if b>>224!=0x53435232: raise ValueError("Wrong control image")
                    with LOCK: job["status"]={"adc_healthy":bool(a&(1<<36)),
                        "interface_enabled":bool(a&(1<<32)),"clock_present":bool(a&(1<<35)),
                        "cpu_reset_released":bool(a&(1<<34))}
                if line.startswith("CELL_RESULT "):
                    _,r,c,label,hold,h0,h1=line.split()
                    save_result(job,decode_scan(h0,h1,int(r),int(c),label,int(hold)))
                if line.startswith("WB_WORD "):
                    _,r,c,op,idx,packet,h0,h1=line.split()
                    wb[int(idx)]=(h0,h1); wb_meta=(int(r),int(c),op,int(packet,16))
                if line.startswith("WB_COMPLETE "):
                    save_result(job,decode_wb(wb,*wb_meta)); wb={}
                if line.startswith("TRACE_CHUNK "):
                    _,index,h1=line.split()
                    result=job["results"][-1]
                    if result["kind"]!="scan": raise ValueError("Trace without scan capture")
                    count,points=decode_trace(h1,int(index),[c["baseline_code"] for c in result["channels"][:3]])
                    with LOCK:
                        trace=result.setdefault("trace",[])
                        if len(trace)!=int(index): raise ValueError("ADC trace gap or duplicate")
                        trace.extend(points); result["trace_expected"]=count
                    if len(trace)==count:
                        (ROOT/"runs"/f"{ident}_trace.json").write_text(json.dumps({
                            "row":result["row"],"col":result["col"],"operation":result["operation"],
                            "adc_rate_hz":10000000,"trace":trace},indent=2))
                if line.startswith("JOB_COMPLETE "): complete=True
            code=remote.returncode
            if code == 255:
                job["remote_execution"]="not_started" if remote.prelaunch_failure or remote.cancelled_before_launch else "uncertain"
                if job["remote_execution"]=="uncertain" and not complete and p["mode"]!="check":
                    require_recovery(job,"SSH disconnected without confirmed cleanup; inspect the previous run before another operation.")
            if code or errors: raise RuntimeError("; ".join(errors[-3:]) or remote.failure_message())
            if not complete and p["mode"]!="check": raise RuntimeError("Missing completion/restoration confirmation")
            if not p["mode"].startswith("wb_") and p["mode"]!="check":
                result=job["results"][-1]
                if len(result.get("trace",[]))!=result.get("trace_expected",-1):
                    raise RuntimeError("Measured ADC trace incomplete")
        with LOCK: job["state"]="completed"; STATE["message"]="Completed; scan read profile restored and CPU held." if p["mode"]!="check" else "Connection checked."
    except Exception as exc:
        with LOCK:
            job["state"]="cancelled" if job.get("cancel_requested") else "failed"
            job["error"]=str(exc); STATE["message"]=str(exc)
        # If decoding failed while Vivado is still running, request the same
        # controller abort used by the GUI, then drain its restoration path.
        process=remote.process if "remote" in locals() else None
        if process is not None and process.poll() is None:
            try: request_cancel(ident)
            except Exception as cancel_error: job["error"]+=f"; cancellation delivery failed: {cancel_error}"
            try: process.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                job["error"]+="; remote cleanup unconfirmed—check hardware before another command"
                require_recovery(job,"Previous remote operation did not confirm cleanup; reinitialize before running.")
    finally:
        with LOCK:
            job["finished"]=now(); STATE["busy"]=False
        (ROOT/"runs"/f"{ident}.json").write_text(json.dumps(job,indent=2),encoding="utf-8")

def request_cancel(ident):
    # UUID is generated by the server, never inserted from unchecked HTTP input.
    uuid.UUID(hex=ident)
    command=f'powershell -NoProfile -Command "Set-Content -LiteralPath \'{REMOTE}/runs/{ident}.stop\' -Value stop"'
    p=subprocess.run(SSH+[command],capture_output=True,text=True,timeout=45)
    if p.returncode: raise RuntimeError("Could not deliver cancellation to the FPGA host")

class Handler(BaseHTTPRequestHandler):
    def reply(self,code,data,kind="application/json"):
        raw=json.dumps(data).encode() if kind=="application/json" else data
        self.send_response(code); self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store")
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        assets={"/":"index.html","/app.js":"app.js","/styles.css":"styles.css"}
        if self.path in assets:
            f=HERE/assets[self.path]
            return self.reply(200,f.read_bytes(),{".html":"text/html; charset=utf-8",".js":"text/javascript",".css":"text/css"}[f.suffix])
        if self.path=="/api/status":
            with LOCK:
                state={**STATE,"history":STATE["history"][-4096:],"jobs":STATE["jobs"][-50:]}
                # Active results are already in history; don't duplicate large arrays.
                if state["job"]: state["job"]={k:v for k,v in state["job"].items() if k!="results"}|{"result_count":len(state["job"]["results"])}
                state["jobs"]=[{k:v for k,v in j.items() if k!="results"}|{"result_count":len(j["results"])} for j in state["jobs"]]
                return self.reply(200,state|{"deployment":deployment(),"defaults":DEFAULTS,"modes":MODES,
                    "api_revision":API_REVISION,"transport":{"connect_timeout_seconds":CONNECT_TIMEOUT_SECONDS,
                    "max_connect_attempts":MAX_CONNECT_ATTEMPTS,"retry_only_before_remote_execution":True}})
        if self.path.startswith("/api/run-log/"):
            ident=self.path.removeprefix("/api/run-log/")
            try:
                if uuid.UUID(hex=ident).hex!=ident: raise ValueError("Invalid job ID")
            except ValueError:
                return self.reply(400,{"error":"Invalid job ID"})
            path=ROOT/"runs"/f"{ident}.log"
            if not path.exists(): return self.reply(404,{"error":"Run log not found"})
            return self.reply(200,path.read_bytes()[-32768:],"text/plain; charset=utf-8")
        if self.path=="/api/export.csv":
            buf=io.StringIO(); writer=csv.writer(buf)
            writer.writerow(["utc","job","kind","operation","row","col","path","active_code","delta_current_uA_nominal","wb_words","calibrated"])
            with LOCK: rows=list(STATE["history"])
            for row in rows:
                if row["kind"]=="scan":
                    for c in row["channels"][:3]:
                        writer.writerow([row["time"],row["job_id"],"scan",row["operation"],row["row"],row["col"],c["path"],c["active_code"],c["delta_current_ua"],"",False])
                else: writer.writerow([row["time"],row["job_id"],"wb",row["operation"],row["row"],row["col"],"","",""," ".join(row["words"]),False])
            return self.reply(200,buf.getvalue().encode(),"text/csv; charset=utf-8")
        if self.path=="/api/trace.csv":
            buf=io.StringIO(); writer=csv.writer(buf)
            writer.writerow(["row","col","time_us","phase","adc1_read_code","adc2_reset_code","adc3_set_code",
                             "read_delta_uA_nominal","reset_delta_uA_nominal","set_delta_uA_nominal"])
            with LOCK: row=next((r for r in reversed(STATE["history"]) if r.get("trace")),None)
            if row:
                for p in row["trace"]:
                    writer.writerow([row["row"],row["col"],p["time_us"],p["phase"],*p["codes"],*p["delta_current_ua"]])
            return self.reply(200,buf.getvalue().encode(),"text/csv; charset=utf-8")
        self.reply(404,{"error":"Not found"})
    def do_POST(self):
        if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"):
            return self.reply(403,{"error":"Local host required"})
        if self.headers.get("Origin") not in (None,f'http://{self.headers.get("Host")}'):
            return self.reply(403,{"error":"Cross-origin request refused"})
        try:
            n=int(self.headers.get("Content-Length","0"))
            if not 0<n<4096: raise ValueError("Invalid request length")
            body=json.loads(self.rfile.read(n))
            if self.path=="/api/cancel":
                with LOCK:
                    job=STATE["job"]
                    if not STATE["busy"] or not job: raise ValueError("No active job")
                    job["cancel_requested"]=True
                request_cancel(job["id"])
                return self.reply(202,{"message":"Cancellation requested; waiting for rail restoration."})
            if self.path!="/api/run": return self.reply(404,{"error":"Not found"})
            p=validate(body)
            if p["dry_run"]: return self.reply(200,{"dry_run":True,"parameters":p,"plan":plan(p)})
            with LOCK:
                if STATE["busy"]: return self.reply(409,{"error":"A hardware job is running"})
                if p["mode"]!="check" and not deployment().get("ready"):
                    return self.reply(409,{"error":deployment().get("reason","Hardware deployment pending")})
                job={"id":uuid.uuid4().hex,"parameters":p,"state":"running","started":now(),"results":[]}
                STATE.update(busy=True,job=job,message=f'Starting {p["mode"]}'); STATE["jobs"].append(job)
            threading.Thread(target=worker,args=(job,),daemon=True).start()
            self.reply(202,{"job_id":job["id"]})
        except (ValueError,TypeError,RuntimeError) as exc: self.reply(400,{"error":str(exc)})
    def log_message(self,*args): pass

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--port",type=int,default=8771); args=parser.parse_args()
    for path in sorted((ROOT/"runs").glob("*.json")):
        try:
            job=json.loads(path.read_text())
            if "parameters" not in job: continue
            STATE["jobs"].append(job); STATE["history"].extend(job.get("results",[]))
        except (ValueError,KeyError): pass
    print(f"SenseEval control: http://127.0.0.1:{args.port}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()
