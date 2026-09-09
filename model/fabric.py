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
    def __init__(self, cfg: TrafficConfig, iterations: int = 3, seed: int | None = None):
        self.cfg = cfg
        self.n = cfg.n_ports
        self.now = 0

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

        # voq[src][dst] = deque of Cell, FIFO within a flow
        self.voq: list[list[deque]] = [[deque() for _ in range(self.n)] for _ in range(self.n)]
        self.voq_oldest_gen_time: list[list[int | None]] = [[None] * self.n for _ in range(self.n)]

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

        # 2) Build request bitmap from non-empty VOQs.
        requests = [
            {dst for dst in range(self.n) if self.voq[src][dst]} for src in range(self.n)
        ]
        active_dsts = {dst for reqs in requests for dst in reqs}

        # 3) Run iSLIP matching for this slot.
        matches = self.arbiter.match(requests)

        # 4) Deliver one cell per matched (src, dst) pair.
        for src, dst in matches:
            q = self.voq[src][dst]
            cell = q.popleft()
            self.metrics.record_delivery(cell, now)
            self.voq_oldest_gen_time[src][dst] = q[0].gen_time if q else None

        self.metrics.record_dest_activity(active_dsts, {dst for _, dst in matches})

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
        """Cells still sitting in VOQs, not delivered -- backlog, not drops
        (VOQs here are unbounded; there is no drop path in this model)."""
        return sum(len(self.voq[src][dst]) for src in range(self.n) for dst in range(self.n))

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
