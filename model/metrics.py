"""Throughput, latency, and fairness metrics collection.

`throughput` alone (cells delivered / (slots * N)) conflates two very
different things under a concentrated pattern like hotspot: scheduling
inefficiency at a congested resource, versus simply not offering enough
traffic to use the whole fabric's aggregate capacity (most destinations
sitting well under 1.0 by construction of the traffic pattern, not because
of a switch flaw). This module reports both the aggregate number and a
per-destination breakdown so the two effects aren't hidden inside one blended
average -- see `bottleneck_throughput` (how well is the busiest destination
served -- decoupled from overall fabric idle time) and
`conditional_throughput_mean` (averaged only over slots where a destination
actually had a backlogged request -- "throughput while packets are running").
"""

from __future__ import annotations

import statistics
from collections import defaultdict


class Metrics:
    def __init__(self, n_ports: int):
        self.n = n_ports
        self.total_slots = 0
        self.cells_offered = 0
        self.cells_delivered = 0
        self.packets_completed = 0

        self.cell_latencies: list[int] = []
        self.packet_latencies: list[int] = []

        # per-(src,dst) flow delivered-cell counts, for fairness
        self.flow_delivered: dict[tuple[int, int], int] = defaultdict(int)

        # per-destination delivered counts + "was backlogged this slot" counts,
        # to compute throughput conditional on there being work to do.
        self.dest_delivered: list[int] = [0] * n_ports
        self.dest_active_slots: list[int] = [0] * n_ports

        # oldest-cell age per VOQ, sampled each slot, for a starvation bound
        self.max_voq_age_seen: dict[tuple[int, int], int] = defaultdict(int)

        # open packets: packet_id -> gen_time, closed on last cell delivery
        self._packet_gen_time: dict[int, int] = {}

    def record_offered(self, n_cells: int) -> None:
        self.cells_offered += n_cells

    def record_voq_ages(self, ages: dict[tuple[int, int], int]) -> None:
        for k, age in ages.items():
            if age > self.max_voq_age_seen[k]:
                self.max_voq_age_seen[k] = age

    def record_dest_activity(self, active_dsts: set[int], matched_dsts: set[int]) -> None:
        """Called once per slot. `active_dsts` = destinations with >=1
        nonempty VOQ requesting them this slot; `matched_dsts` = destinations
        iSLIP actually served this slot (subset of active_dsts, unless
        matching failed to converge on an active one)."""
        for d in active_dsts:
            self.dest_active_slots[d] += 1
        for d in matched_dsts:
            self.dest_delivered[d] += 1

    def record_delivery(self, cell, now: int) -> None:
        self.cells_delivered += 1
        self.cell_latencies.append(now - cell.gen_time)
        self.flow_delivered[(cell.src, cell.dst)] += 1

        if cell.seq == 0:
            self._packet_gen_time[cell.packet_id] = cell.gen_time
        if cell.is_last:
            gen_time = self._packet_gen_time.pop(cell.packet_id, cell.gen_time)
            self.packet_latencies.append(now - gen_time)
            self.packets_completed += 1

    def tick(self) -> None:
        self.total_slots += 1

    def throughput(self) -> float:
        """Fraction of slot*port capacity actually delivered -- the aggregate
        number. Low under a concentrated pattern (hotspot) even with perfect
        scheduling, since most destinations are offered well under their own
        capacity by construction of the traffic pattern -- see module
        docstring. Compare against `bottleneck_throughput` and the
        theoretical best-case (theoretical.py) before concluding this is a
        scheduling problem."""
        capacity = self.total_slots * self.n
        return self.cells_delivered / capacity if capacity else 0.0

    def bottleneck_throughput(self) -> tuple[int, float]:
        """(destination, throughput) for whichever destination delivered the
        most cells -- typically the hotspot. Its own throughput approaching
        1.0 means the scheduler is serving the bottleneck at full rate; the
        aggregate number being low is then a traffic-pattern property, not a
        scheduling failure."""
        if self.total_slots == 0:
            return (0, 0.0)
        d = max(range(self.n), key=lambda i: self.dest_delivered[i])
        return (d, self.dest_delivered[d] / self.total_slots)

    def conditional_throughput_mean(self) -> float:
        """Averaged, across destinations that were ever backlogged, of
        (delivered / slots-while-backlogged) -- "throughput while packets
        are running," excluding slots where a destination had nothing
        queued at all. A work-conserving scheduler should keep this near
        1.0 per destination; well below 1.0 means iSLIP is failing to
        converge on available matches, not that traffic is sparse."""
        ratios = [
            self.dest_delivered[d] / self.dest_active_slots[d]
            for d in range(self.n)
            if self.dest_active_slots[d] > 0
        ]
        return statistics.mean(ratios) if ratios else 1.0

    def jains_fairness_index(self) -> float:
        """1.0 = perfectly fair across all active (src,dst) flows."""
        values = list(self.flow_delivered.values())
        if not values:
            return 1.0
        n = len(values)
        sum_x = sum(values)
        sum_x2 = sum(v * v for v in values)
        return (sum_x ** 2) / (n * sum_x2) if sum_x2 else 1.0

    def summary(self, cells_queued_at_end: int | None = None) -> dict:
        def pct(data, p):
            if not data:
                return 0
            data = sorted(data)
            idx = min(len(data) - 1, int(len(data) * p))
            return data[idx]

        bottleneck_dst, bottleneck_tput = self.bottleneck_throughput()

        out = {
            "slots": self.total_slots,
            "cells_offered": self.cells_offered,
            "cells_delivered": self.cells_delivered,
            "packets_completed": self.packets_completed,
            "aggregate_throughput": round(self.throughput(), 4),
            "bottleneck_destination": bottleneck_dst,
            "bottleneck_throughput": round(bottleneck_tput, 4),
            "conditional_throughput_mean": round(self.conditional_throughput_mean(), 4),
            "packets_completed_per_slot": round(self.packets_completed / self.total_slots, 4)
            if self.total_slots else 0,  # a rate, not normalized to [0,1] like the throughput fields
            "cell_latency_mean": round(statistics.mean(self.cell_latencies), 2) if self.cell_latencies else 0,
            "cell_latency_p99": pct(self.cell_latencies, 0.99),
            "packet_latency_mean": round(statistics.mean(self.packet_latencies), 2) if self.packet_latencies else 0,
            "packet_latency_p99": pct(self.packet_latencies, 0.99),
            "jains_fairness_index": round(self.jains_fairness_index(), 4),
            "max_voq_age": max(self.max_voq_age_seen.values()) if self.max_voq_age_seen else 0,
        }

        if cells_queued_at_end is not None:
            out["cells_queued_at_end"] = cells_queued_at_end
            conserved = self.cells_offered == self.cells_delivered + cells_queued_at_end
            out["conservation_check"] = "PASS (no drops)" if conserved else "FAIL -- cells lost, this is a bug"

        return out
