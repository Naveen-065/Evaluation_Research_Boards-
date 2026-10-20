"""Explicit bench operations; uses existing SSH keys and verified host identity."""
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SSH=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','HostKeyAlias=100.86.99.88',
     '-J','ubuntu-24-04@100.98.132.51','fpga@10.0.2.2']
REMOTE='C:/Users/fpga.DESKTOP-CVDV1JP/kc705_scan_read'
VIVADO='C:/AMDDesignTools2/2026.1/Vivado/bin/vivado.bat'

def run(script,*args):
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    remote_log=f'{REMOTE}/evidence/{script}_{stamp}.log'
    cmd=SSH+[VIVADO,'-mode','batch','-source',f'{REMOTE}/{script}.tcl','-log',remote_log,
             '-journal',f'{REMOTE}/evidence/{script}_{stamp}.jou']
    if args: cmd+=['-tclargs',*map(str,args)]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
    output=p.stdout+'\n'+p.stderr
    (ROOT/'evidence'/f'{script}_{stamp}.log').write_text(output)
    print(output,flush=True)
    if p.returncode or 'ERROR:' in output: raise RuntimeError(f'{script} failed; inspect saved log')
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('script',choices=['program_bringup','program_si5351_2mhz','enable_dac_scan','enable_adc_10m','read_cell']);p.add_argument('args',nargs='*');a=p.parse_args();run(a.script,*a.args)
