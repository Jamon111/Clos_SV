"""Throughput, latency, and fairness metrics collection."""

from __future__ import annotations

import statistics
from collections import defaultdict


class Metrics:
    def __init__(self, n_ports: int):
        self.n = n_ports
        self.total_slots = 0
        self.cells_offered = 0
        self.cells_delivered = 0

        self.cell_latencies: list[int] = []
        self.packet_latencies: list[int] = []

        # per-(src,dst) flow delivered-cell counts, for fairness
        self.flow_delivered: dict[tuple[int, int], int] = defaultdict(int)

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

    def record_delivery(self, cell, now: int) -> None:
        self.cells_delivered += 1
        self.cell_latencies.append(now - cell.gen_time)
        self.flow_delivered[(cell.src, cell.dst)] += 1

        if cell.seq == 0:
            self._packet_gen_time[cell.packet_id] = cell.gen_time
        if cell.is_last:
            gen_time = self._packet_gen_time.pop(cell.packet_id, cell.gen_time)
            self.packet_latencies.append(now - gen_time)

    def tick(self) -> None:
        self.total_slots += 1

    def throughput(self) -> float:
        """Fraction of slot*port capacity actually delivered."""
        capacity = self.total_slots * self.n
        return self.cells_delivered / capacity if capacity else 0.0

    def jains_fairness_index(self) -> float:
        """1.0 = perfectly fair across all active (src,dst) flows."""
        values = list(self.flow_delivered.values())
        if not values:
            return 1.0
        n = len(values)
        sum_x = sum(values)
        sum_x2 = sum(v * v for v in values)
        return (sum_x ** 2) / (n * sum_x2) if sum_x2 else 1.0

    def summary(self) -> dict:
        def pct(data, p):
            if not data:
                return 0
            data = sorted(data)
            idx = min(len(data) - 1, int(len(data) * p))
            return data[idx]

        return {
            "slots": self.total_slots,
            "cells_offered": self.cells_offered,
            "cells_delivered": self.cells_delivered,
            "throughput": round(self.throughput(), 4),
            "cell_latency_mean": round(statistics.mean(self.cell_latencies), 2) if self.cell_latencies else 0,
            "cell_latency_p99": pct(self.cell_latencies, 0.99),
            "packet_latency_mean": round(statistics.mean(self.packet_latencies), 2) if self.packet_latencies else 0,
            "packet_latency_p99": pct(self.packet_latencies, 0.99),
            "jains_fairness_index": round(self.jains_fairness_index(), 4),
            "max_voq_age": max(self.max_voq_age_seen.values()) if self.max_voq_age_seen else 0,
        }
