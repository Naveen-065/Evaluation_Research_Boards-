# Read-order diagnostic — 2026-10-23

This is a zero-write hardware diagnostic on the then-deployed `541cfd8f...`
row-major-interleaved image, which has since been superseded by the two-phase
`b69c7ac2...` image.
It reads physical rows 17 and 18 three times using independent Caravel op1
transactions in forward, reverse, and deterministic-random column order.  The
tool rejects programming opcodes and always finishes with an explicit abort and
the validated safe read profile.

| Order | Row 17 (assigned parity) | Row 18 (spare) | Mean current row 17 | Mean current row 18 |
|---|---:|---:|---:|---:|
| Forward | 30 LRS / 2 HRS | 2 LRS / 30 HRS | 50.820 uA | 24.650 uA |
| Reverse | 31 LRS / 1 HRS | 2 LRS / 30 HRS | 50.720 uA | 24.660 uA |
| Random (`20261023`) | 30 LRS / 2 HRS | 2 LRS / 30 HRS | 50.790 uA | 24.640 uA |

Pairwise coordinate-aligned results:

- forward versus reverse: 1/64 classification changes; mean absolute current
  delta 0.225452 uA (median 0.157028 uA, maximum 0.964722 uA);
- forward versus random: 0/64 classification changes; mean absolute current
  delta 0.262868 uA (median 0.232592 uA, maximum 0.727587 uA);
- reverse versus random: 1/64 classification changes; mean absolute current
  delta 0.246347 uA (median 0.198639 uA, maximum 0.725263 uA).

The sole changing coordinate is physical index 575 (`r17c31`), whose measured
current straddles the fixed 34.2563054 uA separator: 33.785898 uA forward,
34.750620 uA reverse, and 34.169375 uA random.  No spare-row classification
changed.

Conclusion: read acquisition order is not the dominant cause of the failed
576-bit parity image.  Except for one genuinely marginal cell, coordinates are
stable across opposite and randomized order.  This supports the earlier
evidence that programming/half-select disturbance, not GUI ordering or a
streamed-read artifact, dominates the physical SHA mismatch.  A new full-array
write should therefore not be attempted solely on the basis of changing read
order.

Raw evidence is preserved in `forward.csv/json`, `reverse.csv/json`, and
`random.csv/json`.
