# CLAUDE.md

Context for Claude Code sessions working in this repo. This file is read automatically at the
start of every session opened here — it points to the deeper docs rather than repeating them,
and tracks where things were left off so a fresh session can pick up without re-deriving
context.

## What this is

A from-scratch, high-radix arbitrated Ethernet crossbar fabric project — interview prep for
switch-silicon/high-radix networking roles. SystemVerilog RTL + a Python performance model +
the open-source EDA toolchain to check whether the design hits timing.

## Where the deep docs live (read these, don't ask to re-derive them)

- `docs/arch-spec.md` — architecture decision record: candidate topology comparison
  (monolithic crossbar, butterfly, Beneš, Batcher-Banyan, Clos), why Clos was selected, the
  multi-tier scaling math, interview talking-points checklist.
- `model/README.md` — Python VOQ + iSLIP performance model usage and design notes.
- `README.md` — toolchain setup, quick start, VS Code + git workflow.

## External tooling (not committed to this repo — see README.md for install steps)

- `~/eda/pdks/asap7` — ASAP7 PDK clone; extracted RVT Liberty files (TT/SS/FF corners) live
  under `~/eda/pdks/asap7_extracted/RVT/`.
- `~/eda/tools/OpenSTA` — built from source; binary symlinked to `/opt/homebrew/bin/sta`.
- `~/eda/tools/OpenROAD-flow-scripts` — cloned; run via `flow/util/docker_shell make ...`.
  Requires Docker Desktop running. No native arm64 image for `openroad/orfs` is published —
  it was pulled with `--platform linux/amd64` and runs under emulation.

## Key decisions made so far (don't relitigate without new information)

- **Topology: Clos, rearrangeable (m=n=8)** — selected over monolithic crossbar, plain
  butterfly, Beneš, and Batcher-Banyan. The deciding factor is that Clos's matching decomposes
  into small, parallel, local arbitration (radix 8/16, not 128), which is what makes it
  2 GHz-schedulable at high radix — not crosspoint count alone (Beneš is actually smaller but
  needs a global per-slot routing computation, which disqualifies it on speed, not size). Full
  reasoning and the crosspoint-equivalent math: `docs/arch-spec.md` §2–4.
- **Cell-based switching, fixed cell size** — packets are segmented into fixed-size cells at
  ingress specifically so a long packet can't monopolize an output link; iSLIP's per-cell
  round-robin grant naturally interleaves contending flows at cell granularity, which is the
  practical realization of "splitting bandwidth" on a slotted crossbar (true simultaneous
  fractional bandwidth isn't physically realizable — only one input can drive an output's
  physical link per cell slot).
- **RTL flit format must NOT include a timestamp field.** `gen_time` in `model/cell.py` is
  model-only, for latency measurement convenience in a non-synthesizable performance model.
  Carrying an absolute timestamp through the real hardware datapath would waste real silicon
  bits. In RTL, the testbench measures latency externally, keyed by a sequence/tag field that
  genuinely belongs in the flit (e.g. a `packet_id`/`seq` equivalent) — not by embedding time
  in the cell itself.
- **No company-specific references in `docs/arch-spec.md`.** The repo is intended to be
  publicly viewable — the technical reasoning stands on its own without attributing it to any
  specific company's undisclosed microarchitecture.
- **CIOQ with speedup S=2 (Milestone 3+), not a smarter scheduler, closes iSLIP's efficiency
  gap.** Full max-weight matching (the actual optimum) is O(N³) and irrelevant for 2 GHz
  hardware — ruled out as an RTL candidate, kept only as a hypothetical Python-only ceiling
  (never built). Measured on the model: speedup can't raise `aggregate_throughput` (flat across
  S — the ceiling is set by offered rate vs. the external line's 1-cell/slot cap), but
  `conditional_throughput_mean` converges 0.7427 → 1.0 as S goes 1.0 → 4.0. Real cost: at 448G
  line rate and 2 GHz, cell-time budget is only ~2.3 cycles at 64B cells — the arbiter must be
  pipelined (issue-rate, not decision latency, is the constraint), and cell size/speedup are
  jointly constrained by this, not decided from HOL-fairness alone. Full reasoning and the
  measured table: `docs/arch-spec.md` §7.
- **VOQ already is CIOQ's input side — no separate input buffer exists or is needed.** CIOQ =
  input-queueing (VOQ) + output-queueing (added) + speedup; `fabric.py`'s `voq` predates CIOQ,
  `output_queue` is the only thing CIOQ added. For Milestone 3's multi-stage Clos: the same
  two-buffer picture (VOQ at input, one output queue at output, nothing in between) only holds
  if CRRD reserves the whole input→middle→output path atomically per cell-time — preserve that
  property explicitly rather than introducing per-hop buffering as a scheduling workaround.

## Status / where we left off

- Toolchain, docs, and the Python model are done (see `README.md`'s roadmap checklist).
- The Python model now has debug/validation instrumentation
  (`conservation_check`, `bottleneck_throughput`, `conditional_throughput_mean`, and an
  independent theoretical best-case bound in `model/theoretical.py`) — added after a real
  question about a hotspot run's low aggregate throughput turned out to be the theoretically
  correct answer, not a bug. Read `model/README.md`'s "Reading the output" section before
  interpreting any future run's numbers, especially under non-uniform traffic patterns.
- The Python model also has log2-bucketed latency histograms (default-on, ASCII in text mode,
  structured under `histograms` in `--json`) and progress logging to stderr for long runs
  (default-on above 2000 slots, `--progress-interval 0` disables). The model is genuinely slow
  in pure Python at N=128 (~565 slots/s) -- keep that in mind before running large sweeps.
- The model now supports `--speedup` (CIOQ, see the key decision above) — verified S=1.0
  reproduces prior behavior bit-for-bit. Each unit of speedup roughly multiplies per-slot
  runtime, so large sweeps at high S are slow; use `--progress-interval` for visibility.
- The model also has a Little's Law consistency check (`littles_law_ratio` in the summary) —
  an independent cross-check (L=λW holds for any stable queueing system) against the model's
  own throughput/latency numbers. Ratio ≈1.0 confirms steady state; a large ratio (e.g. 74.7 on
  the oversubscribed hotspot config) is itself a correct diagnostic of a growing backlog, not a
  bug. `docs/arch-spec.md` §2.5 now also has a proper structural definition of CRRD (previously
  used throughout without ever being defined).
- The model now depends on NumPy (previously stdlib-only) — used for `voq_occ`, an incrementally
  maintained boolean occupancy array replacing a full O(N²) rebuild every internal round.
  Profiled before optimizing: got 2.23x (8.0s → 3.59s on the standard profiling workload), not
  more, because `RoundRobinPointer.select()` is called ~750K times/run on N=128 arrays and
  NumPy's per-call dispatch overhead is roughly constant regardless of array size — it doesn't
  pay for itself at this granularity the way the occupancy array's bulk `.any(axis=0)` does. A
  pure-Python integer-bitmask rewrite of just the round-robin selection was identified as the
  next lever (not implemented). Verified bit-for-bit identical to the pre-optimization
  implementation across every established regression baseline (hotspot, iterations curve,
  permutation, bursty, low-load uniform) at each step, not just at the end. Full writeup:
  `model/README.md`'s "Performance" section.
- **Milestone 1 RTL (8×8 VOQ + iSLIP) has not been started.** Next concrete action: implement
  `rr_pointer` (reusable rotating priority pointer, mirroring `model/arbiter.py`'s
  `RoundRobinPointer`) and `voq_bank`, per `docs/arch-spec.md` §6. When writing the RTL flit
  format, do not include a timestamp field (see the `gen_time` decision above).
