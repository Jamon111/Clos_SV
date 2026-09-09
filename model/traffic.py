"""Traffic generation: packet arrivals, destination patterns, length distributions.

A whole packet is generated and immediately segmented into cells at ingress
(matching real hardware: the ingress MAC buffers and segments the packet, then
its cells sit in the VOQ waiting for the crossbar's per-slot scheduling to pace
them out one at a time). Traffic generation is therefore decoupled from cell
pacing -- pacing emerges from VOQ + iSLIP, not from this module.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from cell import Cell


@dataclass
class TrafficConfig:
    n_ports: int
    load: float = 0.8                 # P(new packet this slot) per idle source
    cell_size_bytes: int = 64

    pattern: str = "uniform"          # "uniform" | "hotspot" | "permutation" | "bursty"
    hotspot_ports: tuple = (0,)
    hotspot_frac: float = 0.7         # fraction of traffic steered to hotspot_ports

    # bursty (on/off Markov-modulated) arrival, layered on top of `pattern`
    # for the destination choice; only affects *when* packets arrive.
    bursty_mean_on: float = 10.0      # mean slots in "on" (bursting) state
    bursty_mean_off: float = 10.0     # mean slots in "off" (idle) state

    length_dist: str = "bimodal"      # "fixed" | "uniform" | "bimodal" | "exponential"
    length_fixed_bytes: int = 64
    length_uniform_range: tuple = (64, 1518)
    length_bimodal: tuple = (64, 1518, 0.6)   # (small, large, P(small))
    length_exponential_mean: int = 512

    seed: int = 0


def _packet_length_bytes(rng: random.Random, cfg: TrafficConfig) -> int:
    if cfg.length_dist == "fixed":
        return cfg.length_fixed_bytes
    if cfg.length_dist == "uniform":
        lo, hi = cfg.length_uniform_range
        return rng.randint(lo, hi)
    if cfg.length_dist == "bimodal":
        small, large, p_small = cfg.length_bimodal
        return small if rng.random() < p_small else large
    if cfg.length_dist == "exponential":
        return max(cfg.cell_size_bytes, int(rng.expovariate(1.0 / cfg.length_exponential_mean)))
    raise ValueError(f"unknown length_dist: {cfg.length_dist}")


def _n_cells(length_bytes: int, cell_size_bytes: int) -> int:
    return max(1, -(-length_bytes // cell_size_bytes))  # ceil division


def estimate_avg_cells_per_packet(cfg: TrafficConfig, samples: int = 20000) -> float:
    """Monte Carlo estimate of E[cells per packet] for the configured length
    distribution. Used to convert `load` (fraction of cell-slot capacity) into
    a per-slot packet-start probability, independent of packet-size shape."""
    rng = random.Random(cfg.seed ^ 0x5EED)
    total = sum(_n_cells(_packet_length_bytes(rng, cfg), cfg.cell_size_bytes) for _ in range(samples))
    return total / samples


class TrafficSource:
    """Per-input traffic generator: decides, each slot, whether a new packet
    arrives and where it's going, and returns the packet pre-segmented into
    cells ready to enqueue into the correct VOQ.

    `load` in TrafficConfig is the target fraction of cell-slot capacity
    offered per input (1.0 == offering one cell's worth of work every slot,
    the saturation point) -- not a packet-start probability. Since a packet
    spans `avg_cells_per_packet` cells on average, the actual per-slot
    probability of *starting* a new packet is load / avg_cells_per_packet,
    so that mean offered cells/slot converges to `load` regardless of the
    configured packet-length distribution.
    """

    def __init__(self, src: int, cfg: TrafficConfig, rng: random.Random, avg_cells_per_packet: float):
        self.src = src
        self.cfg = cfg
        self.rng = rng
        self._next_packet_id = 0
        self._next_cell_id_fn = None  # injected by SwitchSim for global uniqueness
        self._packet_arrival_prob = min(1.0, cfg.load / avg_cells_per_packet)

        # bursty on/off state
        self._on = True
        self._remaining_in_state = self._draw_state_duration()

    def _draw_state_duration(self) -> int:
        mean = self.cfg.bursty_mean_on if self._on else self.cfg.bursty_mean_off
        return max(1, int(self.rng.expovariate(1.0 / mean)))

    def _advance_burst_state(self) -> None:
        if self.cfg.pattern != "bursty":
            return
        self._remaining_in_state -= 1
        if self._remaining_in_state <= 0:
            self._on = not self._on
            self._remaining_in_state = self._draw_state_duration()

    def _choose_destination(self, now: int) -> int:
        cfg = self.cfg
        if cfg.pattern == "permutation":
            return (self.src + 1) % cfg.n_ports  # fixed distinct destination per input
        if cfg.pattern in ("uniform", "bursty"):
            choices = [p for p in range(cfg.n_ports) if p != self.src]
            return self.rng.choice(choices)
        if cfg.pattern == "hotspot":
            if self.rng.random() < cfg.hotspot_frac:
                hot = [p for p in cfg.hotspot_ports if p != self.src] or [
                    p for p in range(cfg.n_ports) if p != self.src
                ]
                return self.rng.choice(hot)
            choices = [p for p in range(cfg.n_ports) if p != self.src]
            return self.rng.choice(choices)
        raise ValueError(f"unknown pattern: {cfg.pattern}")

    def maybe_generate(self, now: int) -> list[Cell] | None:
        """Called once per slot. Returns a list of cells for a newly generated
        packet, or None if no packet arrives this slot."""
        cfg = self.cfg
        self._advance_burst_state()

        arrives = self.rng.random() < self._packet_arrival_prob
        if cfg.pattern == "bursty":
            arrives = arrives and self._on

        if not arrives:
            return None

        dst = self._choose_destination(now)
        length_bytes = _packet_length_bytes(self.rng, cfg)
        n_cells = _n_cells(length_bytes, cfg.cell_size_bytes)

        packet_id = self._next_packet_id
        self._next_packet_id += 1

        cells = []
        for seq in range(n_cells):
            cells.append(
                Cell(
                    cell_id=self._next_cell_id_fn(),
                    src=self.src,
                    dst=dst,
                    packet_id=packet_id,
                    seq=seq,
                    is_last=(seq == n_cells - 1),
                    gen_time=now,
                )
            )
        return cells
