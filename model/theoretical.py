"""Analytical/Monte-Carlo best-case throughput bound, independent of the VOQ +
iSLIP simulation loop -- used to sanity-check simulated results against what
the offered traffic alone permits, so a "low throughput" number can be told
apart from an actual scheduling failure or a modeling bug.

Deliberately reuses the real TrafficSource generator (not a hand-derived
reimplementation of its distributions) so this bound reflects exactly what
the simulator offers, including bursty's duty-cycle effects -- but note this
means a bug shared by both this module and the simulator's traffic layer
would not be caught by comparing them. It *is* independent of the VOQ/iSLIP
scheduling logic, which is the part most likely to actually be wrong.
"""

from __future__ import annotations

import random

from traffic import TrafficConfig, TrafficSource, estimate_avg_cells_per_packet


def offered_rate_per_destination(cfg: TrafficConfig, samples: int = 50000) -> list[float]:
    """Expected offered cells/slot to each destination, estimated by running
    the real traffic generators alone (no VOQ, no arbitration) for `samples`
    slots and tallying cells by destination."""
    counts = [0] * cfg.n_ports
    avg_cells = estimate_avg_cells_per_packet(cfg)

    next_id = [0]

    def alloc() -> int:
        next_id[0] += 1
        return next_id[0]

    sources = [
        TrafficSource(i, cfg, random.Random(cfg.seed ^ 0xBEEF ^ i), avg_cells)
        for i in range(cfg.n_ports)
    ]
    for s in sources:
        s._next_cell_id_fn = alloc

    for t in range(samples):
        for s in sources:
            cells = s.maybe_generate(t)
            if cells:
                counts[cells[0].dst] += len(cells)

    return [c / samples for c in counts]


def best_case_throughput(cfg: TrafficConfig, samples: int = 50000) -> dict:
    """No scheduler, however good, can deliver more to a destination than is
    offered to it, or more than 1 cell/slot -- this is that ceiling."""
    rates = offered_rate_per_destination(cfg, samples)
    capped = [min(1.0, r) for r in rates]
    bottleneck = max(range(cfg.n_ports), key=lambda d: rates[d])
    return {
        "aggregate_best_case_throughput": round(sum(capped) / cfg.n_ports, 4),
        "bottleneck_destination": bottleneck,
        "bottleneck_offered_rate": round(rates[bottleneck], 3),
        "bottleneck_best_case_throughput": round(capped[bottleneck], 4),
        "median_dest_offered_rate": round(sorted(rates)[len(rates) // 2], 4),
    }
