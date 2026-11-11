"""Run explicitly selected modes through the GUI HTTP API; save the results."""
import argparse
import json
import time
import urllib.request
from pathlib import Path
URL="http://127.0.0.1:8771"
ROOT=Path(__file__).resolve().parents[1]
def request(path,body=None):
    data=None if body is None else json.dumps(body).encode()
    with urllib.request.urlopen(urllib.request.Request(URL+path,data=data,headers={"Content-Type":"application/json"}),timeout=30) as r:
        return json.load(r)
def run(mode, **overrides):
    col=31 if mode.startswith("wb_") else 0
    parameters=dict(mode=mode,row=0,col=col,cycles=1,dry_run=False) | overrides
    if any(token in mode for token in ("set", "reset", "cycle")):
        assert (parameters["row"],parameters["col"]) == (0,col), "Programming is restricted to the approved test cell"
    job=request("/api/run",parameters)
    ident=job["job_id"]
    print(f"START {mode} r{parameters['row']}/c{parameters['col']} job={ident}",flush=True)
    last=-1
    while True:
        status=request("/api/status")
        j=next(x for x in status["jobs"] if x["id"]==ident)
        if j["result_count"]!=last:
            print(f"PROGRESS {mode} captures={j['result_count']} state={j['state']}",flush=True);last=j["result_count"]
        if j["state"]!="running":
            print("RESULT "+json.dumps(j),flush=True)
            if j["state"]!="completed": raise RuntimeError(j.get("error",j["state"]))
            return j
        time.sleep(5)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("modes",nargs="+");a=p.parse_args()
    for mode in a.modes: run(mode)
