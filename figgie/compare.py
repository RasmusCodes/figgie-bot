"""Paired A/B comparison of bot variants.

Each variant takes the same seat-lottery against the same opponents on the
same seeds (same deals), so differences between variants are much less noisy
than separate tournaments.

    python -m figgie.compare "shark" "shark:read_weight=0" --games 2000
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Sequence

from .engine import Rules
from .tournament import run_tournament

FIELDS: Dict[str, List[str]] = {
    "mixed": ["hand", "counter", "noise"],
    "counters": ["counter", "counter", "counter"],
    "oracles": ["oracle", "oracle", "oracle"],
    "strong-mix": ["oshark", "oracle", "counter"],
    "osharks": ["oshark", "oshark", "oshark"],
    # adversarial stress test: the same table with and without the bid spoofing
    "spoofed": ["spoofer", "oracle", "counter"],
    "unspoofed": ["spoofer:every=0", "oracle", "counter"],
    # figgie.com-like dead-suit churn (cards dumped for $1-2, then bid back up), and a table
    # built to bait the shark's cheap-resale buying (see figgie.patterns)
    "fickle": ["fickle", "fickle", "fickle"],
    "baited": ["bait", "bait", "bait"],
    "bait-pair": ["bait", "bait", "fickle"],
    # other table sizes (the official game is 4 or 5 players)
    "duel": ["counter"],
    "duel-oracle": ["oracle"],
    "trio": ["counter", "oracle"],
    "five": ["hand", "counter", "noise", "oracle"],
}
DEFAULT_FIELDS = ["mixed", "counters", "oracles", "strong-mix", "osharks"]


def compare(
    variants: Sequence[str], fields: Dict[str, List[str]], games: int, seed: int, ticks: int, workers=None
) -> None:
    head = f"{'variant':<48}" + "".join(f"{f:>16}" for f in fields) + f"{'average':>10}"
    print(head)
    print("-" * len(head))
    for v in variants:
        cells, means = [], []
        for name, field in fields.items():
            lineup = [v] + list(field)
            res = run_tournament(lineup, games=games, seed=seed, rules=Rules(n_players=len(lineup), ticks=ticks), workers=workers)
            st = res.stats[v]
            cells.append(f"{st.mean:>+9.2f} ±{st.ci95:4.1f}")
            means.append(st.mean)
        print(f"{v:<48}" + "".join(f"{c:>16}" for c in cells) + f"{sum(means) / len(means):>+10.2f}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figgie.compare", description=__doc__.split("\n\n")[0])
    ap.add_argument("variants", nargs="+", help='bot specs, e.g. "shark" "shark:take_edge=2"')
    ap.add_argument("--games", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--ticks", type=int, default=240)
    ap.add_argument("--fields", default=",".join(DEFAULT_FIELDS), help=f"subset of: {', '.join(FIELDS)}")
    ap.add_argument("--workers", type=int, default=None, help="processes (default: CPUs - 1)")
    args = ap.parse_args(argv)
    fields = {f: FIELDS[f] for f in args.fields.split(",")}
    compare(args.variants, fields, args.games, args.seed, args.ticks, args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
