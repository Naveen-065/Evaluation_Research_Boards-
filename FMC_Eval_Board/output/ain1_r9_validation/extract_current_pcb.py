from pathlib import Path
import json
import pcbnew

root=Path(__file__).resolve().parent
board=pcbnew.LoadBoard(str(root.parents[1]/'CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb'))
pads=[]
for f in board.GetFootprints():
    for p in f.Pads():
        pads.append({'ref':f.GetReference(),'value':f.GetValue(),'pad':p.GetNumber(),
                     'net':p.GetNetname(),'x_mm':pcbnew.ToMM(p.GetPosition().x),
                     'y_mm':pcbnew.ToMM(p.GetPosition().y)})
(root/'current_pcb_pads.json').write_text(json.dumps(pads,indent=2))
refs={'R9','R31','R33','R34','R37','R38','U10','NT1'}
for p in pads:
    if p['ref'] in refs:
        print(p['ref'],p['value'],p['pad'],p['net'])
connectivity=board.GetConnectivity()
route_report={}
for net in ['AIN1_P','AIN1_N','Net-(U10-IN+)','Net-(U10-IN-)',
            '/ADC/C1RGP','/ADC/C1RGN','Net-(U10-OUT+)','Net-(U10-OUT-)',
            'AMP1_P','AMP1_N','OUT1_P','OUT1_N']:
    on_net=[p for f in board.GetFootprints() for p in f.Pads() if p.GetNetname()==net]
    queue=[on_net[0]]
    seen=set()
    reached=set()
    while queue:
        item=queue.pop()
        uid=item.m_Uuid.AsString()
        if uid in seen: continue
        seen.add(uid)
        for p in connectivity.GetConnectedPads(item):
            reached.add(p.GetParentFootprint().GetReference()+'.'+p.GetNumber())
            queue.append(p)
        queue.extend(connectivity.GetConnectedTracks(item))
    expected={p.GetParentFootprint().GetReference()+'.'+p.GetNumber() for p in on_net}
    route_report[net]={'expected':sorted(expected),'reached':sorted(reached),
                       'all_connected_in_pcb_design':expected.issubset(reached)}
(root/'pcb_path_connectivity.json').write_text(json.dumps(route_report,indent=2))
assert all(r['all_connected_in_pcb_design'] for r in route_report.values()),route_report
print('PCB_R9_U10_ADC1_FMC_ROUTE_CONNECTIVITY_PASS')
