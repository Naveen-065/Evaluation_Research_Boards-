# Hardware evidence

`preprogram_read_2026-10-23/` is the complete direct readback captured by GUI
job `b3e0224dd8534231a213553bcdb9c4aa` before the Qwen parity record was
programmed.  The JSON and CSV contain exactly 1,024 unique row-major cells:

- 24 LRS and 1,000 HRS at the 34.2563054-uA separator;
- 287 mismatches among the 576 assigned parity cells;
- zero unknown or failed reads; and
- reconstructed physical parity SHA-256
  `481d7885dce5fa86bfceeb5e09fd58586c8a307f588f484a4f968116e9bb62b2`,
  which does **not** match the encoded record.

This is intentionally retained as a baseline and must not be presented as a
post-program success.  The app correctly blocked physical EDAC use for it.
`parity_snapshot.json` records the exact requested 72-byte LSB-first parity
payload whose SHA-256 is
`45391f608395001fa5a1cae00284480a9d54c884254ba60a347e52ccbc774e5d`.

`mixed_scheduler_postprogram_2026-10-23/` preserves the subsequent physical
write plus independent full-array read. That trial reduced the mismatch count
only from 287 to 280 and is also explicitly rejected by the SHA gate; see its
README for the program/read confusion matrix.

`read_order_probe_2026-10-23/` contains a zero-write forward/reverse/random
read-order comparison on rows 17 and 18.  Only the marginal cell at `r17c31`
crossed the classifier in 64 coordinate-aligned reads; all spare-row states
were stable.  This rules out acquisition order as the dominant explanation for
the failed parity SHA and points back to programming/half-select disturbance.
