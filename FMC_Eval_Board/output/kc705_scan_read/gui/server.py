"""Local read-only Caravel cell monitor for KC705 + SenseEval v1.2F.

Hardware operations are serialized. No arbitrary Tcl, rail settings, SET or
RESET programming commands are accepted over HTTP. No demonstration data.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
RUNS=ROOT/'runs'
LOCK=threading.Lock()
STATE_LOCK=threading.Lock()
STATE={'busy':False,'message':'Ready to check the bench connection.','last':None,'history':[],'checked':False}
HOST='fpga@100.86.99.88'
REMOTE='C:/Users/fpga.DESKTOP-CVDV1JP/kc705_scan_read'
VIVADO='C:/AMDDesignTools2/2026.1/Vivado/bin/vivado.bat'
PATH_NAMES=['READ / R9','RESET / R11','SET / R10','ADC4','ADC5']

def timestamp(): return datetime.now(timezone.utc).isoformat()

def deployment():
    path=ROOT/'evidence/deployment.json'
    if not path.exists(): return {'verified':False,'reason':'FPGA build, firmware flashing and bench validation are pending.'}
    data=json.loads(path.read_text())
    for name,digest in data.get('hashes',{}).items():
        p=ROOT/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            return {'verified':False,'reason':'Deployment files differ from the verified bench image.'}
    return data

def decode(h0,h1,row,col):
    a,b=int(h0,16),int(h1,16)
    if b>>224!=0x53435231: raise ValueError('Wrong FPGA image signature')
    if not a&(1<<9) or a&(1<<10) or a&(1<<8): raise ValueError('Read did not complete successfully')
    packet=(row<<10)|(col<<5)|row
    if ((a>>16)&65535)!=packet: raise ValueError('Returned cell address does not match request')
    nb,na=(a>>64)&65535,(a>>80)&65535
    # 128 x 0.5 us baseline / 1.2 ms active at independently checked 10 MSPS.
    if not 500<=nb<=800 or not 11000<=na<=13000: raise ValueError(f'Unexpected ADC window sizes: {nb}/{na}')
    channels=[]
    for ch in range(5):
        base=((a>>(96+32*ch))&0xffffffff)/nb
        active=((b>>(32*ch))&0xffffffff)/na
        if not 0<=base<=4095 or not 0<=active<=4095: raise ValueError('ADC code outside 12-bit range')
        v=(active-2048)/2048
        delta=(active-base)/2048
        rail_clipped=base<=0 or base>=4095 or active<=0 or active>=4095
        channels.append({'channel':ch+1,'path':PATH_NAMES[ch],'baseline_code':base,'active_code':active,
            'rail_clipped':rail_clipped,
            'adc_diff_mv':v*1000,'delta_adc_mv':delta*1000,
            'estimated_current_ua':v/(7*56)*1e6 if ch<3 and not rail_clipped else None,
            'delta_current_ua':delta/(7*56)*1e6 if ch<3 and not rail_clipped else None})
    return {'time':timestamp(),'row':row,'col':col,'packet':f'0x{packet:04X}',
        'baseline_samples':nb,'active_samples':na,'adc_rate_hz':10000000,'scan_clock_hz':2000000,
        'shunt_ohms':56,'nominal_gain':7,'calibrated':False,'clipped':bool(a&(1<<37)),
        'channels':channels,'raw_result0':h0,'raw_result1':h1}

def call_hardware(action,row,col):
    # VM relay reaches the same Windows host when its own Tailscale client is off.
    # HostKeyAlias checks the already-known Windows key; verification is not relaxed.
    args=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','HostKeyAlias=100.86.99.88',
        '-J','ubuntu-24-04@100.98.132.51','fpga@10.0.2.2',VIVADO,'-mode','batch',
        '-source',REMOTE+'/read_cell.tcl','-log',REMOTE+'/evidence/ui_read.log',
        '-journal',REMOTE+'/evidence/ui_read.jou','-tclargs',action,str(row),str(col)]
    run=subprocess.run(args,capture_output=True,text=True,timeout=100)
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence/ui_last.log').write_text(run.stdout+'\n'+run.stderr)
    if run.returncode or 'ERROR:' in run.stdout:
        lines=[l for l in (run.stdout+'\n'+run.stderr).splitlines() if 'ERROR:' in l or 'ssh:' in l]
        raise RuntimeError('\n'.join(lines[-3:]) or 'Vivado could not complete the request; see ui_last.log')
    found=[re.search(rf'SCAN_RESULT{i}=([0-9A-Fa-f]+)',run.stdout) for i in (0,1)]
    if not all(found): raise RuntimeError('No valid FPGA read result returned')
    return [x.group(1) for x in found]

def worker(action,row,col):
    try:
        h0,h1=call_hardware(action,row,col)
        if action=='read':
            result=decode(h0,h1,row,col)
            RUNS.mkdir(exist_ok=True)
            with (RUNS/'reads.jsonl').open('a') as f: f.write(json.dumps(result)+'\n')
            with STATE_LOCK:
                STATE['last']=result; STATE['history'].append(result)
                STATE['message']=f'Cell r{row:02d} c{col:02d} captured. '+('ADC clipping detected.' if result['clipped'] else 'Currents use nominal gain; calibration pending.')
        else:
            a=int(h0,16)
            if int(h1,16)>>224!=0x53435231: raise RuntimeError('Scan image signature mismatch')
            with STATE_LOCK:
                STATE['checked']=bool((a>>36)&1 and (a>>32)&1)
                STATE['message']='FPGA connected; ADC and scan interface ready.' if STATE['checked'] else 'FPGA connected; startup or scan interface enable is incomplete.'
    except Exception as exc:
        with STATE_LOCK: STATE['message']=str(exc); STATE['checked']=False
    finally:
        with STATE_LOCK: STATE['busy']=False
        LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def reply(self,status,value,kind='application/json'):
        data=json.dumps(value).encode() if kind=='application/json' else value
        self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path=='/': return self.reply(200,(HERE/'index.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/api/status':
            with STATE_LOCK: state=dict(STATE); state['history']=STATE['history'][-1024:]
            state['deployment']=deployment(); return self.reply(200,state)
        if self.path=='/api/export.csv':
            s=io.StringIO(); w=csv.writer(s)
            w.writerow(['utc','row','col','packet','path','baseline_code','active_code','adc_diff_mv','estimated_current_ua','delta_current_ua','calibrated'])
            with STATE_LOCK: rows=list(STATE['history'])
            for row in rows:
                for c in row['channels']:
                    w.writerow([row['time'],row['row'],row['col'],row['packet'],c['path'],c['baseline_code'],c['active_code'],c['adc_diff_mv'],c['estimated_current_ua'],c['delta_current_ua'],False])
            return self.reply(200,s.getvalue().encode(),'text/csv; charset=utf-8')
        self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if self.headers.get('Origin') not in (None,f'http://{self.headers.get("Host")}'):
            return self.reply(403,{'error':'Cross-origin command refused'})
        try:
            if self.path not in ['/api/read','/api/check']: raise ValueError('Unknown action')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<1024: raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(length)); row=body.get('row',0); col=body.get('col',0)
            if type(row)!=int or type(col)!=int or not 0<=row<=31 or not 0<=col<=31: raise ValueError('Row and column must be 0–31')
            action='read' if self.path=='/api/read' else 'status'
            if action=='read' and not deployment().get('verified'): raise ValueError('Hardware deployment has not been verified yet')
            if not LOCK.acquire(blocking=False): return self.reply(409,{'error':'A hardware operation is already running'})
            with STATE_LOCK: STATE.update(busy=True,message=f'{"Reading cell" if action=="read" else "Checking bench"} r{row:02d} c{col:02d}…')
            threading.Thread(target=worker,args=(action,row,col),daemon=True).start()
            return self.reply(202,{'started':True})
        except (ValueError,json.JSONDecodeError) as exc: return self.reply(400,{'error':str(exc)})
    def log_message(self,*args): pass

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8770); args=parser.parse_args()
    if (RUNS/'reads.jsonl').exists():
        for line in (RUNS/'reads.jsonl').read_text().splitlines():
            try: STATE['history'].append(json.loads(line))
            except ValueError: pass
        if STATE['history']: STATE['last']=STATE['history'][-1]
    print(f'Caravel read monitor: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()

if __name__=='__main__': main()
