"""Read-only KiCad connectivity audit; does not test physical solder joints."""
import json
from pathlib import Path
import pcbnew

root = Path(__file__).resolve().parents[2]
board = pcbnew.LoadBoard(str(root/'CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb'))
connectivity = board.GetConnectivity()
report = {}
for net in ['LCLK_P', 'LCLK_N', 'ADCLK_P', 'ADCLK_N', 'FPGA_MCLKIN_C_P', 'FPGA_MCLKIN_C_N']:
    pads = [p for f in board.GetFootprints() for p in f.Pads() if p.GetNetname() == net]
    start = next(p for p in pads if p.GetParentFootprint().GetReference() == 'U14')
    queue = [start]
    seen = set()
    reached_pads = set()
    while queue:
        item = queue.pop()
        uid = item.m_Uuid.AsString()
        if uid in seen:
            continue
        seen.add(uid)
        for p in connectivity.GetConnectedPads(item):
            reached_pads.add(p.GetParentFootprint().GetReference()+'.'+p.GetNumber())
            if p.m_Uuid.AsString() not in seen:
                queue.append(p)
        for track in connectivity.GetConnectedTracks(item):
            if track.m_Uuid.AsString() not in seen:
                queue.append(track)
    report[net] = {
        'start': 'U14.'+start.GetNumber(),
        'all_pads_on_net': sorted(p.GetParentFootprint().GetReference()+'.'+p.GetNumber() for p in pads),
        'physically_connected_pads_in_design': sorted(reached_pads),
        'visited_items': len(seen)
    }
out = Path(__file__).resolve().parent/'evidence/pcb_clock_routes.json'
out.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
