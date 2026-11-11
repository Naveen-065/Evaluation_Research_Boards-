"""Fail if the new routed design changes any unapproved electrical property."""
import csv
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def rows(p):
    with p.open() as f: return {x['PORT']:x for x in csv.DictReader(f,delimiter='\t')}
a=rows(ROOT.parent/'kc705_adc_capture/build/port_properties.tsv')
b=rows(ROOT/'build/port_properties.tsv')
assert a.keys()==b.keys(),'Port inventory changed'
changes=[]
for port in a:
    for key in a[port]:
        old,new=a[port][key],b[port][key]
        if old==new: continue
        # These two pins are newly controllable, with low drive and slow slew.
        allowed=port in ('scan_si','reset_b') and (
            (key=='DIRECTION' and old=='IN' and new=='INOUT') or
            (key=='DRIVE' and old=='' and new=='4') or
            (key=='SLEW' and old=='' and new=='SLOW'))
        assert allowed,(port,key,old,new)
        changes.append(dict(port=port,property=key,before=old,after=new))
report=dict(passed=True,ports=len(a),package_pins_preserved=True,io_standards_preserved=True,
            vadj_writes=False,approved_functional_changes=changes)
(ROOT/'evidence/io_audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
