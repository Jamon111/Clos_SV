"""VOQ bank + crossbar scheduling loop tying traffic, arbitration, and
metrics together. One call to step() = one cell-time slot."""

from __future__ import annotations

import random
import sys
import time
from collections import deque

from arbiter import ISlipArbiter
from metrics import Metrics
from traffic import TrafficConfig, TrafficSource, estimate_avg_cells_per_packet


class SwitchSim:
    def __init__(
        self,
        cfg: TrafficConfig,
        iterations: int = 3,
        seed: int | None = None,
        speedup: float = 1.0,
    ):
        """speedup (S >= 1.0): ratio of internal fabric bandwidth to external
        line rate (CIOQ). S=1.0 is pure input-queueing -- the model's
        original behavior, reproduced exactly (see model/README.md's CIOQ
        section for the regression check). S>1.0 runs multiple internal
        iSLIP matching rounds per external cell-time, moving cells from VOQ
        into a per-destination output queue; the external line still drains
        at most 1 cell/slot from that output queue regardless of S -- S
        can never raise the external per-destination throughput ceiling
        (that's fixed by offered rate vs. the 1/slot line-rate cap), it can
        only help the scheduler get closer to a ceiling that already
        existed. Fractional S (e.g. 1.5) is supported via a credit
        accumulator that averages to S internal rounds/slot over time.
        """
        if speedup < 1.0:
            raise ValueError("speedup must be >= 1.0 -- CIOQ never runs the fabric slower than the line rate")

        self.cfg = cfg
        self.n = cfg.n_ports
        self.now = 0
        self.speedup = speedup
        self._speedup_credit = 0.0

        rng_seed = cfg.seed if seed is None else seed
        self._next_cell_id = 0

        self.rng = random.Random(rng_seed)
        avg_cells_per_packet = estimate_avg_cells_per_packet(cfg)
        self.avg_cells_per_packet = avg_cells_per_packet
        self.sources = [
            TrafficSource(i, cfg, random.Random(rng_seed + 1000 + i), avg_cells_per_packet)
            for i in range(self.n)
        ]
        for s in self.sources:
            s._next_cell_id_fn = self._alloc_cell_id

        # voq[src][dst] = deque of Cell, FIFO within a flow -- internal fabric side
        self.voq: list[list[deque]] = [[deque() for _ in range(self.n)] for _ in range(self.n)]
        self.voq_oldest_gen_time: list[list[int | None]] = [[None] * self.n for _ in range(self.n)]

        # output_queue[dst] = cells that have crossed the fabric, waiting for
        # the external line (the CIOQ "O" -- only present/needed when S>1;
        # at S=1 it's drained same-slot so it never actually backs up).
        self.output_queue: list[deque] = [deque() for _ in range(self.n)]

        self.arbiter = ISlipArbiter(self.n, iterations)
        self.metrics = Metrics(self.n)

    def _alloc_cell_id(self) -> int:
        cid = self._next_cell_id
        self._next_cell_id += 1
        return cid

    def step(self) -> None:
        now = self.now

        # 1) Traffic arrivals: segment new packets straight into their VOQ.
        for src, source in enumerate(self.sources):
            cells = source.maybe_generate(now)
            if cells:
                self.metrics.record_offered(len(cells))
                dst = cells[0].dst
                q = self.voq[src][dst]
                was_empty = not q
                q.extend(cells)
                if was_empty:
                    self.voq_oldest_gen_time[src][dst] = cells[0].gen_time

        # 2) Internal fabric: run `internal_rounds` iSLIP matches this
        # external slot (>1 only when speedup>1 models a faster-than-line
        # -rate crossbar), moving matched cells from VOQ into the
        # destination's output queue. Credit accumulator supports fractional
        # speedup (e.g. 1.5 -> alternating 1,2,1,2,... rounds/slot).
        self._speedup_credit += self.speedup
        internal_rounds = int(self._speedup_credit)
        self._speedup_credit -= internal_rounds

        requests = [
            {dst for dst in range(self.n) if self.voq[src][dst]} for src in range(self.n)
        ]
        for _ in range(internal_rounds):
            if not any(requests):
                break  # nothing left to match this slot
            matches = self.arbiter.match(requests)
            for src, dst in matches:
                q = self.voq[src][dst]
                cell = q.popleft()
                self.output_queue[dst].append(cell)
                self.voq_oldest_gen_time[src][dst] = q[0].gen_time if q else None
            requests = [
                {dst for dst in range(self.n) if self.voq[src][dst]} for src in range(self.n)
            ]

        # 3) Diagnostic: did each destination have work available (VOQ or
        # output queue) this slot, and did it actually transmit? See
        # metrics.py's conditional_throughput_mean docstring -- this is
        # specifically the metric that should improve when speedup>1 fixes
        # internal matching contention, since it's measured at the external
        # line, which speedup can never bypass.
        active_dsts = {dst for reqs in requests for dst in reqs} | {
            dst for dst in range(self.n) if self.output_queue[dst]
        }

        # 4) External egress: each output transmits at most 1 cell onto the
        # line this slot -- the external PHY rate, unaffected by speedup.
        delivered_dsts = set()
        for dst in range(self.n):
            oq = self.output_queue[dst]
            if oq:
                cell = oq.popleft()
                self.metrics.record_delivery(cell, now)
                delivered_dsts.add(dst)

        self.metrics.record_dest_activity(active_dsts, delivered_dsts)

        # 5) Track VOQ ages (starvation bound) before advancing time.
        ages = {}
        for src in range(self.n):
            for dst in range(self.n):
                gt = self.voq_oldest_gen_time[src][dst]
                if gt is not None:
                    ages[(src, dst)] = now - gt
        self.metrics.record_voq_ages(ages)

        self.metrics.tick()
        self.now += 1

    def cells_queued(self) -> int:
        """Cells still in flight, not delivered -- backlog, not drops (VOQs
        and the output queue are both unbounded; there is no drop path in
        this model). Split into fabric-side (VOQ) vs. line-side (output
        queue) backlog for interpretability."""
        voq_backlog = sum(len(self.voq[src][dst]) for src in range(self.n) for dst in range(self.n))
        oq_backlog = sum(len(q) for q in self.output_queue)
        return voq_backlog + oq_backlog

    def run(self, n_slots: int, progress_interval: int = 0, progress_stream=None) -> dict:
        """progress_interval=0 disables progress messages. Always written to
        `progress_stream` (default stderr), so `--json` on stdout stays
        parseable even with progress enabled."""
        stream = progress_stream if progress_stream is not None else sys.stderr
        start = time.monotonic()

        for i in range(n_slots):
            self.step()
            if progress_interval and (i + 1) % progress_interval == 0:
                elapsed = time.monotonic() - start
                rate = (i + 1) / elapsed if elapsed > 0 else 0.0
                print(
                    f"[progress] slot {i + 1}/{n_slots} ({100 * (i + 1) / n_slots:.0f}%) "
                    f"delivered={self.metrics.cells_delivered} queued={self.cells_queued()} "
                    f"elapsed={elapsed:.1f}s ({rate:.0f} slots/s)",
                    file=stream,
                )

        return self.metrics.summary(cells_queued_at_end=self.cells_queued())
