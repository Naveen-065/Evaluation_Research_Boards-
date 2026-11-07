# Chip 4 r7/c1 WB RESET PWM/DAC direction-reversal record

- Date: 2026-11-07 (Asia/Singapore)
- Board/controller: Caravel ReRAM evaluation board with ZedBoard controller
- Device identity: user-declared chip 4 after a physical chip swap; no independent digital chip-ID register was available
- Cell: row 7, RTL column 1 only

## Executive finding

Increasing the commanded WB RESET voltage did not produce a monotonic RESET
response at fixed maximum PWM code `0xF0`.

- The previous maximum-PWM RESET at `2.5 V` moved the scan-debug median in the
  desired direction, from `39.344` to `37.611 uA`, but did not reach the
  `34.256 uA` RESET threshold.
- At `2.6 V`, the same `0xF0` PWM moved `35.606` to `34.645 uA`; only one of
  five postreads crossed the RESET threshold.
- At `2.7 V`, the same `0xF0` PWM reversed direction and increased the
  scan-debug median from `34.457` to `36.829 uA`.
- All three WB transactions returned ACK, four nonzero cached TDC words, and
  an unclipped RESET-shunt capture. The wrong-direction result therefore
  cannot be dismissed as an ACK-only transport event.
- The `2.7 V` R11 baseline was already `3613.773` ADC codes and the active
  window reached code `3793`. The `2.8`, `2.9`, and `3.0 V` tiers were not
  issued because the cell had reversed direction and the 12-bit ADC had
  limited remaining headroom.

The data prove a repeatable association between the WB RESET command/profile
and a wrong-direction current increase under some PWM/DAC conditions. They do
not, by themselves, prove that RESET DAC amplitude is the sole physical cause.
Possible contributors include RESET rail routing, polarity or selection in the
Caravel IP, pulse-width/state dependence, and cell history.

## Electrical and measurement paths

The board-schematic mapping used for these runs was:

| Function | Commanded DAC path | Shunt/ADC observation |
|---|---|---|
| WB RESET word-line rail | DAC4, `WL_RESET` | Not used as the cell-state measurement |
| WB RESET supply rail | DAC5, `VCC_RESET/VDDA2` | R11 to AIN3, digitized as ADC2 |
| Scan-debug read | Separate scan-read profile using the common read pin | R9/read channel; used for all cell-state decisions |

For each WB RESET transaction, DAC4 and DAC5 were commanded to the same
voltage. The other programming rails were off. The controller then restored
the 2 MHz scan-read DAC profile before collecting five postreads.

Commanded DAC values were not independently probed with a Saleae or oscilloscope
in this evaluation setup. The R11 capture confirms a RESET-path electrical
excursion but does not directly resolve the internal ReRAM cell PWM waveform.

## Transaction acceptance criteria

A transaction was accepted as processed only after all of the following:

1. WB ACK completed.
2. The cached WB TDC bank contained four nonzero words at indices 11 through
   14. This was the full-loop gate; ACK alone was not considered sufficient.
3. ADC2/R11 showed a sustained excursion and neither the baseline nor active
   window clipped.
4. The cell outcome was determined only from scan-debug reads after restoring
   the scan-read profile.
5. Sentinel drift remained below the `10 uA` hard stop.

The firmware configuration packets were already at the established maximum
repeat/retry payloads, and each programming transaction issued the identical
cell command twice as the silicon-pipeline workaround.

RESET success was defined as at least four of five postreads at or below
`34.2563054 uA` together with a directional decrease of at least `5 uA`.

## Detailed results

### A. Previous maximum-PWM RESET reference: 2.5 V / 0xF0

This transaction followed the fixed-`1.3 V` SET PWM-skew run. The SET ladder
had stopped at PWM `0x20` because all five scan postreads crossed the `35 uA`
SET separator; SET codes `0x40` through `0xF0` were cancelled.

| Field | Value |
|---|---|
| WB operation | RESET |
| PWM code | `0xF0` (maximum tested code) |
| DAC4 / DAC5 | `2.5 / 2.5 V` |
| Scan pre-median | `39.344012 uA` |
| Scan post-median | `37.610528 uA` |
| Scan delta | `-1.733484 uA` |
| Postread range | `36.015294..37.849779 uA` |
| RESET-side postreads | `0/5` |
| WB/TDC full-loop gate | PASS; four nonzero words; last `0x0007532F` |
| R11 baseline | mean `2445.639893`; range `2418..2475` codes |
| R11 active window | `2354..2670` codes |
| Sustained excursion | positive and negative detected; no clipping |
| Sentinel maximum drift | `0.437036 uA` |

Interpretation: the maximum PWM produced a downward movement at `2.5 V`, but
the cell remained on the high-current side. This was a partial RESET response,
not a confirmed RESET state.

### B. Voltage-skew tier 1: 2.6 V / 0xF0

| Field | Value |
|---|---|
| WB operation | RESET |
| PWM code | `0xF0` |
| DAC4 / DAC5 | `2.6 / 2.6 V` |
| Scan pre-median | `35.606438 uA` |
| Scan post-median | `34.644526 uA` |
| Scan delta | `-0.961912 uA` |
| Postread range | `33.268641..35.184654 uA` |
| RESET-side postreads | `1/5` |
| WB/TDC full-loop gate | PASS; four nonzero words; last `0x0007C615` |
| R11 baseline | mean `2910.108398`; range `2876..2948` codes |
| R11 active window | `2815..3129` codes |
| Sustained excursion | positive detected; no clipping |
| Sentinel maximum drift | `0.175462 uA` |

Interpretation: raising the tied RESET rails by `0.1 V` still moved the cell
downward, but less than the `2.5 V` reference and far below the required
directional change. One postread entered the nominal RESET range, while four
did not.

### C. Voltage-skew tier 2: 2.7 V / 0xF0

| Field | Value |
|---|---|
| WB operation | RESET |
| PWM code | `0xF0` |
| DAC4 / DAC5 | `2.7 / 2.7 V` |
| Scan pre-median | `34.456516 uA` |
| Scan post-median | `36.829455 uA` |
| Scan delta | `+2.372939 uA` |
| Postread range | `36.535938..37.363450 uA` |
| RESET-side postreads | `0/5` |
| WB/TDC full-loop gate | PASS; four nonzero words; last `0x0007832B` |
| R11 baseline | mean `3613.772949`; range `3572..3657` codes |
| R11 active window | `3520..3793` codes |
| Sustained excursion | positive detected; no clipping |
| Sentinel maximum drift | `0.282105 uA` |

Interpretation: the accepted RESET transaction increased current instead of
decreasing it. The five postreads were all above the RESET separator. Because
the WB/TDC and R11 gates passed, this is a cell-state direction reversal after
a processed WB RESET transaction, not merely a missing packet.

## Related wrong-direction observations

The direction reversal was not unique to the final `2.7 V / 0xF0` tier:

| RESET condition | Scan result | Observation |
|---|---:|---|
| `2.5 V / 0x80` | `26.666 -> 29.129 uA` (`+2.463 uA`) | Mid-PWM RESET increased current, although all postreads remained below the RESET threshold. |
| `2.9 V / 0x10` | `42.967 -> 67.158 uA` (`+24.191 uA`) | Minimum-PWM voltage search produced a large wrong-direction jump; both R11 windows saturated, so the planned 3.0 V tier was cancelled. |

These runs began from different cell states and are not a controlled
point-for-point voltage comparison. They are included because they show that
wrong-direction movement can occur at both short and long RESET PWM codes.

## Why the experiment stopped at 2.7 V

The experiment was intentionally not extended to 2.8, 2.9, or 3.0 V:

- The `2.7 V` tier moved in the wrong direction by `+2.373 uA`.
- Its active R11 maximum was `3793`, leaving only `302` codes below 12-bit
  full scale (`4095`).
- The R11 baseline rose from `2910.108` codes at 2.6 V to `3613.773` codes at
  2.7 V, so another equal voltage increment had a material risk of clipping.
- A previous 2.9 V RESET run had already saturated both R11 windows and caused
  a large wrong-direction state change.

Continuing the voltage ladder would therefore increase electrical stress while
reducing observability and without evidence of monotonic RESET improvement.

## Conclusions and diagnostic implications

1. More RESET voltage is not a valid monotonic correction for this cell and
   state at maximum PWM.
2. WB ACK, four nonzero TDC returns, and R11 activity confirm that the WB path
   processed the transactions; the failure is not explained by ACK-only packet
   receipt.
3. The observed state transition is determined by independent scan-debug reads,
   so the wrong-direction result is not inferred from the WB TDC value.
4. The current evidence does not isolate the mechanism. The next diagnostic
   should distinguish DAC4/DAC5 rail routing and polarity, internal RESET
   selection, and cell-history effects. Direct scan-debug RESET is known to
   recover this cell through a separate DAC2/DAC3 programming path, so it is a
   useful control but not proof that WB timing alone is faulty.
5. Any future WB RESET work should begin with a low-current recovery, keep the
   R11 ADC below saturation, and use small single-variable steps with scan-debug
   outcome reads after every accepted WB transaction.

## Machine-readable companion

See [`results.csv`](results.csv) for the previous maximum-PWM reference, the
2.6/2.7 V voltage-skew tiers, the cancelled higher tiers, and the related
wrong-direction observations.
