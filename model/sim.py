#!/usr/bin/env python3
"""CLI runner for the VOQ + iSLIP performance model.

Example:
    python3 sim.py --n-ports 128 --load 0.9 --pattern hotspot \\
        --length-dist bimodal --cell-size 64 --slots 20000 --seed 1
"""

from __future__ import annotations

import argparse
import json

from fabric import SwitchSim
from traffic import TrafficConfig


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-ports", type=int, default=128)
    p.add_argument("--load", type=float, default=0.8, help="P(new packet/slot) per idle input")
    p.add_argument("--iterations", type=int, default=3, help="iSLIP iterations per slot")
    p.add_argument("--slots", type=int, default=20000)
    p.add_argument("--seed", type=int, default=0)

    p.add_argument("--pattern", choices=["uniform", "hotspot", "permutation", "bursty"], default="uniform")
    p.add_argument("--hotspot-ports", type=int, nargs="*", default=[0])
    p.add_argument("--hotspot-frac", type=float, default=0.7)
    p.add_argument("--bursty-mean-on", type=float, default=10.0)
    p.add_argument("--bursty-mean-off", type=float, default=10.0)

    p.add_argument("--length-dist", choices=["fixed", "uniform", "bimodal", "exponential"], default="bimodal")
    p.add_argument("--length-fixed-bytes", type=int, default=64)
    p.add_argument("--length-uniform-range", type=int, nargs=2, default=[64, 1518])
    p.add_argument("--length-bimodal", type=float, nargs=3, default=[64, 1518, 0.6],
                    help="small_bytes large_bytes P(small)")
    p.add_argument("--length-exponential-mean", type=int, default=512)

    p.add_argument("--cell-size", type=int, default=64, help="cell size in bytes")
    p.add_argument("--json", action="store_true", help="print summary as JSON")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    cfg = TrafficConfig(
        n_ports=args.n_ports,
        load=args.load,
        cell_size_bytes=args.cell_size,
        pattern=args.pattern,
        hotspot_ports=tuple(args.hotspot_ports),
        hotspot_frac=args.hotspot_frac,
        bursty_mean_on=args.bursty_mean_on,
        bursty_mean_off=args.bursty_mean_off,
        length_dist=args.length_dist,
        length_fixed_bytes=args.length_fixed_bytes,
        length_uniform_range=tuple(args.length_uniform_range),
        length_bimodal=tuple(args.length_bimodal),
        length_exponential_mean=args.length_exponential_mean,
        seed=args.seed,
    )

    sim = SwitchSim(cfg, iterations=args.iterations, seed=args.seed)
    summary = sim.run(args.slots)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        width = max(len(k) for k in summary)
        for k, v in summary.items():
            print(f"{k:<{width}} : {v}")


if __name__ == "__main__":
    main()
