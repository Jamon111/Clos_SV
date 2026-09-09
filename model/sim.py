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
from theoretical import best_case_throughput
from traffic import TrafficConfig


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-ports", type=int, default=128)
    p.add_argument("--load", type=float, default=0.8, help="P(new packet/slot) per idle input")
    p.add_argument("--iterations", type=int, default=3, help="iSLIP iterations per slot")
    p.add_argument("--speedup", type=float, default=1.0,
                    help="CIOQ internal fabric speedup over external line rate, >=1.0 "
                         "(1.0 = pure input-queued, the model's original behavior)")
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
    p.add_argument("--no-theoretical", action="store_true",
                    help="skip the theoretical best-case bound (it's a separate Monte Carlo pass)")
    p.add_argument("--no-histogram", action="store_true", help="skip latency histograms")
    p.add_argument("--progress-interval", type=int, default=None,
                    help="print progress every N slots to stderr (default: auto, ~10 updates "
                         "for runs of 2000+ slots; pass 0 to disable)")
    return p.parse_args()


def print_ascii_histogram(title: str, hist: list[tuple[str, int]], bar_width: int = 40) -> None:
    print(f"--- {title} ---")
    if not hist:
        print("(no data)")
        return
    max_count = max(c for _, c in hist)
    label_width = max(len(label) for label, _ in hist)
    for label, count in hist:
        bar_len = round(bar_width * count / max_count) if max_count else 0
        print(f"{label:>{label_width}} slots | {'#' * bar_len:<{bar_width}} {count}")


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

    if args.progress_interval is not None:
        progress_interval = args.progress_interval
    else:
        progress_interval = max(1, args.slots // 10) if args.slots >= 2000 else 0

    sim = SwitchSim(cfg, iterations=args.iterations, seed=args.seed, speedup=args.speedup)
    summary = sim.run(args.slots, progress_interval=progress_interval)
    histograms = None if args.no_histogram else sim.metrics.latency_histograms()

    theoretical = None if args.no_theoretical else best_case_throughput(cfg)

    if args.json:
        print(json.dumps(
            {"actual": summary, "theoretical_best_case": theoretical, "histograms": histograms},
            indent=2,
        ))
        return

    width = max(len(k) for k in summary)
    if theoretical:
        print("=== theoretical best-case (offered traffic alone, no simulation) ===")
        for k, v in theoretical.items():
            print(f"{k:<{width}} : {v}")
        print()
    print("=== simulated actual (VOQ + iSLIP) ===")
    for k, v in summary.items():
        print(f"{k:<{width}} : {v}")

    if histograms:
        print()
        print_ascii_histogram("cell latency histogram (slots)", histograms["cell_latency_histogram"])
        print()
        print_ascii_histogram("packet latency histogram (slots)", histograms["packet_latency_histogram"])


if __name__ == "__main__":
    main()
