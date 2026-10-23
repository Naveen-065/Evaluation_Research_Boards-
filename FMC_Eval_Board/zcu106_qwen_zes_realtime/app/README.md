# Local Qwen + ZES control app

This folder is a self-contained PC host application for the ZCU106/Qwen/ZES
experiment. It uses only the Python standard library for the web server and
control plane. The browser UI is served only on loopback.

## What is real, and what is a fallback

- With `QWEN_MODEL_PATH` set to a local Transformers-compatible Qwen model,
  BER injection changes exactly 1 KiB of a **live in-memory model tensor**.
  Inference and tensor mutation share one lock, and model files are never
  written.
- Without a valid local model plus PyTorch and Transformers, the UI displays a
  prominent `Deterministic demo fallback (not Qwen)` banner. The fallback
  verifies the UI, streaming, BER, EDAC, and hardware orchestration only.
- `reference` EDAC is a transparent single-bit-correction mock. `board` EDAC
  talks to the AArch64 relay over the persistent binary `ZES1/v1` protocol; it
  is never silently emulated.
- The protected object is one 1 KiB tensor view, not the complete Qwen model.

## Start

From this directory:

```powershell
.\run.ps1
```

Then open <http://127.0.0.1:8780/>. To use another port:

```powershell
.\run.ps1 -Port 8781
```

Optional environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `QWEN_MODEL_PATH` | Local Qwen model directory with `config.json` | demo fallback |
| `ZES_EDAC_HOST` | ZCU106 Linux relay IP on the isolated Ethernet link | board EDAC disabled |
| `ZES_EDAC_PORT` | Binary relay port | `9106` |
| `ZES_EDAC_THRESHOLD` | Default vendor decoder threshold, 1 through 8192 | `3` |
| `SENSEEVAL_URL` | Legacy service used only for conflict checks and the optional row probe | `http://127.0.0.1:8771` |
| `BITMAP_VIVADO` | Vivado batch launcher | `C:/Xilinx/Vivado/2022.2/bin/vivado.bat` |
| `RERAM_FAILED_CELLS` | Semicolon-separated known-failed physical coordinates, e.g. `2,7;9,11` | empty |
| `RERAM_EXCLUSIVE_HARDWARE` | Enables direct Vivado control only after the legacy port 8771 service is stopped; prefer `run.ps1 -ExclusiveHardware` | disabled |

PyTorch, Transformers, and all model files are optional and are never
downloaded automatically.

## Experimental flow

1. Select an EDAC backend and choose **Initialize & encode parity**. The app
   snapshots a live 1024-byte tensor view and generates 72 opaque parity bytes.
   Hardware initialization, bitmap program/read, EDAC check/repair, and the
   optional row probe share one operation gate.  If a complete physical map
   restored from disk has the exact same encoded-parity SHA, initialization
   retains and binds it; a different SHA invalidates it.
2. Choose **Program parity to X1** to map those 576 bits row-major to physical
   ReRAM indices 0 through 575. The app creates 32 hexadecimal row words; bit 0
   of word 0 is physical `(row 0, column 0)`. Indices 576 through 1023 are
   spares and are not programmed.
3. Choose **Read parity map** for a direct 1024-cell readback. The 32x32 heatmap
   is classified from measured current, not from the requested bits. The
   **Simulation** button is always marked as such and issues no FPGA command.
   The 576 measured parity bits are reconstructed only from a complete real
   readback. Their SHA-256 must exactly match the encoded 72-byte record before
   they can be selected as EDAC input.
4. Inject a BER. The percentage is quantized to an exact number of unique bit
   flips in the 8192-bit live view. **Check** does not mutate memory. **Repair**
   accepts a board correction only when the returned bytes match the original
   SHA-256 baseline; an uncorrectable response leaves the live tensor intact.
   Choose `Host encoded copy · not X1` for the in-memory parity returned by the
   encoder, or `Physical X1 readback · SHA-gated` for the verified ReRAM copy.
   The app never reports host parity as physical hardware readback.
5. Prompt the active runtime. Tokens arrive over server-sent events. The
   optional FPGA row probe is asynchronous and read-only.

Direct bitmap jobs call `../fpga/tools/bitmap_program.tcl` and
`../fpga/tools/bitmap_read.tcl`. They require the new bitmap-capable bitstream
and `.ltx` probes. Because the legacy service has no shared lock protocol,
direct jobs fail closed unless it is no longer listening on port 8771 and the
app was explicitly started with `-ExclusiveHardware`. A process-wide file lease
also prevents two copies of this app from launching Vivado simultaneously.
Programming and readback are serialized in the app; direct readback cannot be
cancelled mid-run because the Tcl tool must restore the safe read profile.
On restart, the app restores the newest complete 1Kbit hardware read plus its
matching parity snapshot as display-only historical evidence.  It validates
all 1,024 unique physical coordinates and the 72-byte snapshot hash before
showing it.  Restored evidence is never eligible for EDAC until the current
live tensor is initialized and produces that exact encoded-parity SHA.

The ZES relay protocol has no authentication or encryption. Keep port 9106 on
the isolated board link or protect it with a firewall/VPN.

## HTTP API

- `GET /api/capabilities`, `GET /api/protection`
- `POST /api/protection/initialize|inject|check|repair`
- `POST /api/inference`, `GET /api/inference/<id>/events`
- `GET /api/memory-map`
- `POST /api/memory-map/program|read|cancel`

Run the host tests:

```powershell
python -m unittest discover -s tests -v
node --check web/app.js
```

