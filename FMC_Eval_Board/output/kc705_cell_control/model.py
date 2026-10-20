"""Current PCB measurements and strict, shell-safe operation parameters."""
import math
from datetime import datetime, timezone

MODES = ["read", "set", "reset", "cycle", "column", "array",
         "wb_read", "wb_set", "wb_reset", "wb_cycle", "check"]
PATHS = ["READ / R9", "RESET / R11", "SET / R10", "ADC4", "ADC5"]
DEFAULTS = dict(mode="read", row=0, col=0, set_v=2.3, set_wl=1.3,
                reset_v=2.7, reset_wl=1.5, hold=2400, cycles=1, dry_run=True)

def now():
    return datetime.now(timezone.utc).isoformat()

def validate(data):
    if not isinstance(data, dict) or set(data)-set(DEFAULTS):
        raise ValueError("Unknown request fields")
    p = DEFAULTS | data
    if p["mode"] not in MODES:
        raise ValueError("Unknown operation")
    for key, lo, hi in [("row",0,31),("col",0,31),("hold",20,12000),("cycles",1,10)]:
        if type(p[key]) is not int or not lo <= p[key] <= hi:
            raise ValueError(f"{key} must be an integer from {lo} to {hi}")
    for key in ("set_v", "set_wl", "reset_v", "reset_wl"):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or not 0 <= p[key] <= 3:
            raise ValueError(f"{key} must be 0–3.0 V")
    if type(p["dry_run"]) is not bool:
        raise ValueError("dry_run must be boolean")
    return p

def plan(p):
    m=p["mode"]
    n=1024 if m=="array" else 32 if m=="column" else 1
    pulses=(2*p["cycles"] if "cycle" in m else 1) if any(x in m for x in ("set","reset","cycle")) else 0
    return {"cells":n, "program_operations":pulses,
            "test_cell":f'r{p["row"]}/c{p["col"]}',
            "clock_mhz":10 if m.startswith("wb_") else 2,
            "vdda1_v":3.0,"vccd2_v":1.8,"fmc_vadj_v":1.8,
            "pulse_ms":p["hold"]/2000,
            "note":"Plan only; no hardware access or synthetic measurements."}

def decode_scan(h0,h1,row,col,label,hold):
    a,b=int(h0,16),int(h1,16)
    if b>>224 != 0x53435232 or not a&(1<<9) or a&(1<<10) or a&(1<<8):
        raise ValueError("Invalid or failed FPGA capture")
    packet=(int(label=="set_pulse")<<15)|(row<<10)|(col<<5)|row
    if (a>>16)&65535 != packet:
        raise ValueError("FPGA cell/operation differs from request")
    nb,na=(a>>64)&65535,(a>>80)&65535
    # Clock-domain snapshots can differ by a few samples at window boundaries.
    if not 500<=nb<=800 or not max(1,hold*5-40)<=na<=hold*5+40:
        raise ValueError(f"Invalid ADC window: {nb}/{na} samples for {hold} clocks")
    channels=[]
    for i in range(5):
        base=((a>>(96+32*i))&0xffffffff)/nb
        active=((b>>(32*i))&0xffffffff)/na
        clipped=bool(a&(1<<(39+i)))
        if not 0<=base<=4095 or not 0<=active<=4095:
            raise ValueError("ADC sum outside 12-bit range")
        v=(active-2048)/2048
        delta=(active-base)/2048
        channels.append(dict(channel=i+1,path=PATHS[i],baseline_code=base,active_code=active,
            clipped=clipped,adc_diff_mv=v*1000,delta_adc_mv=delta*1000,
            estimated_current_ua=v/(7*56)*1e6 if i<3 and not clipped else None,
            delta_current_ua=delta/(7*56)*1e6 if i<3 and not clipped else None))
    return dict(kind="scan",time=now(),row=row,col=col,operation=label,packet=f"0x{packet:04X}",
                baseline_samples=nb,active_samples=na,channels=channels,calibrated=False,
                nominal_gain=7,shunt_ohms=56,clipped=bool(a&(1<<37)),raw0=h0,raw1=h1)

def decode_wb(words,row,col,op,packet):
    if len(words)!=15 or sorted(words)!=list(range(15)):
        raise ValueError("Incomplete Wishbone result bank")
    values=[]
    for i in range(15):
        h0,h1=words[i]; a,b=int(h0,16),int(h1,16)
        if b>>224!=0x53435232 or not a&(1<<38) or a&(1<<10):
            raise ValueError("Invalid Wishbone FPGA status")
        if ((b>>40)&0x7fff)!=0x7fff or not b&(1<<55) or b&(1<<56):
            raise ValueError("Wishbone mask/echo/protocol check failed")
        if ((b>>64)&0xffffffff)!=packet or ((b>>32)&255)!=0x80+i or ((b>>128)&15)!=i:
            raise ValueError("Wishbone echo/tag/index mismatch")
        values.append(b&0xffffffff)
    matching=[v for v in values if v and (v>>14)&31==col]
    selected=next(iter(matching),0)
    return dict(kind="wb",time=now(),row=row,col=col,operation=op,packet=f"0x{packet:08X}",
        words=[f"0x{v:08X}" for v in values],selected=f"0x{selected:08X}",
        nonzero=any(values),matching_column=bool(matching),coarse=(selected>>8)&63,
        fine=selected&255,extra=selected>>19,transport_verified=True,
        cell_state_verified=False,calibrated=False,
        note="TDC counts are not calibrated conductance. A command echo alone is not a cell-state check.")

def decode_trace(h1,index,baseline):
    b=int(h1,16); count=(b>>192)&511
    if b>>224!=0x54524332 or ((b>>201)&255)!=index or not 3<=count<=256:
        raise ValueError("Invalid measured trace header")
    result=[]
    for k in range(min(3,count-index)):
        word=(b>>(64*k))&((1<<64)-1)
        codes=[(word>>(12*i))&4095 for i in range(3)]
        phase=word>>56
        result.append(dict(index=index+k,time_us=((word>>36)&0xfffff)/10,
            phase=phase,codes=codes,
            delta_current_ua=[(code-baseline[i])/2048/392*1e6 for i,code in enumerate(codes)]))
    return count,result
