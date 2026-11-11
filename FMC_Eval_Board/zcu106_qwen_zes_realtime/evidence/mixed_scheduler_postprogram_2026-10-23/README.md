# Mixed-scheduler physical parity trial — 2026-10-23

This directory preserves the first physical 72-byte parity programming trial
with FPGA bitmap operation 15 and its independent full 1Kbit readback. It is a
failed verification trial, not a valid physical EDAC result.

- Program job: `e9107b27095840e28eb6b420ad803f96`
- Read job: `3502ff4562dc4e01a8284a3c50ebeae8`
- Bitstream SHA-256 deployed for this trial:
  `541cfd8f25ee9ef70f8456714cc34e299f20525d1581be4e902bef98dc8c82a3`
  (the row-major interleaved SET/RESET scheduler image)
- Requested parity SHA-256: `45391f608395001fa5a1cae00284480a9d54c884254ba60a347e52ccbc774e5d`
- Reconstructed physical parity SHA-256: `6f60549e4fcb186cc6ec30d2e50e00015672dea538df117803031af801acbe8e`
- Program summary: 576/576 visited; 287 SET and 289 RESET targets;
  11 SET and 42 RESET attempts exhausted their bounded policy.
- Independent read: 1,024/1,024 cells; 280 parity mismatches, zero unknown
  samples, and zero read failures.
- Confusion over the 576 assigned cells: 223 `1→1`, 64 `1→0`, 73 `0→0`,
  and 216 `0→1`.

The scheduler's immediate per-cell verification was not accepted as proof of
stored parity: 187 RESET cells marked pass later read as LRS, and 62 SET cells
marked pass later read as HRS. The application therefore blocks physical
check/repair unless an independent read reconstructs the exact expected SHA.

The 448 spare cells (physical indices 576–1023) were not programmed, but they
are included in the full readback evidence and the frontend heatmap.

A second full read (`40eff80686e94d639850b56bfd3df66a`) was then acquired
without any intervening programming. It produced 276 mismatches and physical
parity SHA-256
`37dcd1fdc022d964268d4d7a6a891939bb5109481f8d293699f40a5e88b90fa5`.
Between the two reads, 24/576 assigned classifications changed (9 `0→1`,
15 `1→0`) with 0.926 µA mean absolute current change; only 1/448 spare
classifications changed, with 0.714 µA mean absolute change. This proves the
readback is not bit-stable enough for SHA-gated EDAC and motivates the saved
read-order/retention diagnostics before another destructive full rewrite.
