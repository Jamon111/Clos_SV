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
- `theoretical.py` — analytical/Monte-Carlo best-case throughput bound, independent of the
  VOQ/iSLIP simulation loop, printed alongside actual results for comparison (use
  `--no-theoretical` to skip it).
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

## Reading the output: which throughput number means what

`aggregate_throughput` (cells delivered / (slots × N)) is low under a concentrated pattern like
hotspot *even with a perfectly-behaving scheduler* — most destinations are offered well under
their own 1-cell/slot capacity by construction of the traffic pattern, and that idle capacity
drags the system-wide average down. That's a traffic-pattern property, not a scheduling
failure, and a single blended number can't tell the two apart. Three additional fields exist
specifically so you don't have to guess which one you're looking at:

- **`theoretical_best_case` block** (from `theoretical.py`) — the ceiling implied by the
  offered traffic alone, computed independently of the simulation. If `aggregate_throughput`
  is close to `aggregate_best_case_throughput`, the simulated result is behaving correctly for
  that config, not failing.
- **`bottleneck_throughput`** — the busiest destination's own delivered/slots ratio. Under
  hotspot traffic this should approach 1.0, proving the scheduler is serving the bottleneck at
  full rate regardless of what the aggregate number looks like.
- **`conditional_throughput_mean`** — averaged, across destinations that were ever backlogged,
  of (delivered / slots-while-backlogged): "throughput while packets are actually queued,"
  excluding slots where a destination had nothing to send at all. Meaningfully below 1.0 here
  is a real (not buggy) iSLIP effect worth knowing: an input holding cells for both the hotspot
  and a lightly-loaded destination can have its accept-phase round-robin pick the hotspot grant
  in a given slot, silently dropping an otherwise-uncontested grant for the cold destination
  that slot — the classic "maximal, not maximum, matching" property. More iSLIP iterations only
  recover this when another idle input was also requesting that same cold destination that
  slot; under heavy single-hotspot bias there often isn't one, so `--iterations` can stop
  changing the result entirely (verified: iterations 3 and 7 gave bit-identical results for a
  heavily hotspot-biased config, while the same sweep under uniform traffic reproduces the
  classic iSLIP curve — 88.5% → 94.4% → 95.7% → 95.8% at N=16, load=1.0 — confirming iteration
  count is correctly wired and the hotspot case's flatness is a property of that traffic
  pattern, not a bug).
- **`conservation_check`** — `cells_offered == cells_delivered + cells_queued_at_end`. VOQs in
  this model are unbounded (no `maxlen`, no drop path anywhere in `fabric.py`), so
  `cells_offered - cells_delivered` is backlog still sitting in queue, never a drop. This field
  makes that an explicit, checked invariant rather than something to take on faith — it prints
  `FAIL -- cells lost, this is a bug` if it's ever violated.

## Sanity-checked behavior

- Low load (0.3, uniform): near-lossless, low latency.
- Saturation (1.0, uniform, N=16, 3 iterations): ~95.7% throughput — in the expected range for
  iSLIP under uniform traffic with a handful of iterations.
- Hotspot (N=128, load=0.9, default single hotspot port + 0.7 frac): `aggregate_throughput`
  0.2807 vs. hand-derived and Monte-Carlo `aggregate_best_case_throughput` ≈ 0.281–0.282 —
  matches closely, confirming the low number is the theoretically correct answer for this
  config, not a bug. `bottleneck_throughput` = 1.0 (the hotspot port is fully saturated, served
  at capacity) while 127 other destinations sit well under their own capacity by construction
  of the traffic pattern.

## A concrete experiment worth running

Sweep `--cell-size` (e.g. 32/64/128/256) under a bimodal mouse/elephant length mix and plot
mouse-flow packet completion latency vs. cell size — demonstrates directly why fixed-size cell
segmentation matters for fairness, rather than asserting it.
