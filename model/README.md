# VOQ + iSLIP performance model

A discrete-event, cell-slotted Python model of the VOQ + iSLIP switch fabric. Two purposes:

1. **Golden reference** — an independent implementation of iSLIP's matching behavior
   (request/grant/accept, rotating priority pointers, iteration-1-only pointer updates) to
   cross-check the RTL against once Milestone 1 exists.
2. **Performance-prediction tool** — sweep parameters (cell size, load, traffic pattern, port
   count) and get throughput/latency/fairness numbers cheaply, without waiting on RTL
   simulation runtime.

Deliberately **not** a bit-accurate datapath model — no physical flit/data width is
represented. A cell is metadata only (`src, dst, packet_id, seq, is_last, gen_time`); the
model's job is throughput/latency/fairness, which that's sufficient for. Bit-accurate datapath
timing belongs in the RTL testbench, which is the thing this model is compared against.

**`gen_time` is model-only and must not be mirrored in the RTL flit format.** It exists purely
for latency measurement convenience in this non-synthesizable model. Embedding a timestamp in
the actual hardware cell/flit would waste real silicon bits for no functional purpose — in the
RTL, latency should be measured by the testbench externally, keyed off a sequence/tag field
that genuinely is part of the flit (e.g. an equivalent of `packet_id`/`seq`), not by carrying
absolute time through the datapath.

## Files

- `cell.py` — the `Cell` metadata record.
- `traffic.py` — packet arrival, destination pattern, and length-distribution generation.
- `arbiter.py` — the iSLIP request/grant/accept matching algorithm, with a `RoundRobinPointer`
  primitive mirroring the RTL's planned `rr_pointer` module.
- `fabric.py` — VOQ bank + main per-slot simulation loop (`SwitchSim`).
- `metrics.py` — throughput, latency, and Jain's-fairness-index collection.
- `sim.py` — CLI entry point.

## Why `load` isn't packet-arrival probability

`load` means **fraction of cell-slot capacity offered per input** (1.0 = one cell's worth of
work every slot — the saturation point), not "probability of starting a whole packet each
slot." A packet spans multiple cells on average, so the actual per-slot packet-start
probability is calibrated as `load / avg_cells_per_packet`, where `avg_cells_per_packet` is
estimated by Monte Carlo sampling the configured length distribution
(`estimate_avg_cells_per_packet` in `traffic.py`). This keeps `load=X` meaning the same thing
regardless of what packet-length distribution is configured.

## Usage

```
python3 sim.py --n-ports 128 --load 0.9 --pattern hotspot --hotspot-frac 0.7 \
    --length-dist bimodal --cell-size 64 --iterations 3 --slots 20000 --seed 1
```

Traffic patterns: `uniform`, `hotspot` (`--hotspot-ports`, `--hotspot-frac`), `permutation`
(fixed conflict-free destination per input, a useful easy-case baseline), `bursty` (on/off
Markov-modulated arrivals, `--bursty-mean-on/off`).

Length distributions: `fixed`, `uniform` (`--length-uniform-range`), `bimodal`
(`--length-bimodal small large P(small)` — the default, modeling a mouse/elephant mix), or
`exponential` (`--length-exponential-mean`).

All randomness is seeded (`--seed`) for reproducibility — same seed, same result, which matters
once this is used as a regression baseline against RTL simulation.

## Sanity-checked behavior

- Low load (0.3, uniform): near-lossless, low latency.
- Saturation (1.0, uniform, N=16, 3 iterations): ~95.7% throughput — in the expected range for
  iSLIP under uniform traffic with a handful of iterations.
- Hotspot (0.8 concentration): throughput and fairness both collapse — correctly reflects that
  VOQ + iSLIP fixes head-of-line blocking, not fundamental output-capacity contention when
  traffic is concentrated on one output.

## A concrete experiment worth running

Sweep `--cell-size` (e.g. 32/64/128/256) under a bimodal mouse/elephant length mix and plot
mouse-flow packet completion latency vs. cell size — demonstrates directly why fixed-size cell
segmentation matters for fairness, rather than asserting it.
