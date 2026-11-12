"""Command line:  python -m figgie {watch,bench} ...

  python -m figgie watch --lineup shark,hand,counter,noise --seed 7
  python -m figgie bench --lineup shark,hand,hand,counter --games 1000
  python -m figgie bench --lineup "shark,shark:take_edge=2,hand,counter"
"""
from __future__ import annotations

import argparse
import sys

from .engine import Rules
from .tournament import REGISTRY, run_tournament, watch


def _lineup(text: str):
    return [s.strip() for s in _split_specs(text) if s.strip()]


def _split_specs(text: str):
    """Split on commas that start a new bot (``name`` or ``name:``), not on the
    commas between one bot's ``param=value`` pairs."""
    specs, cur = [], ""
    for chunk in text.split(","):
        head = chunk.strip().split(":", 1)[0].split("=", 1)[0].strip().lower()
        if cur and head in REGISTRY and "=" not in chunk.split(":", 1)[0]:
            specs.append(cur)
            cur = chunk
        else:
            cur = f"{cur},{chunk}" if cur else chunk
    if cur:
        specs.append(cur)
    return specs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figgie", description="Figgie engine, bots and tournaments")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="play one game and print the play-by-play")
    w.add_argument("--lineup", default="shark,hand,counter,noise", help="comma-separated bots, one per seat")
    w.add_argument("--seed", type=int, default=None)
    w.add_argument("--ticks", type=int, default=240)
    w.add_argument("--quotes", action="store_true", help="also print every new bid/offer")
    w.add_argument("--beliefs-every", type=int, default=40, help="print shark beliefs every N ticks (0 = never)")

    b = sub.add_parser("bench", help="run a tournament and report average P&L per bot")
    b.add_argument("--lineup", default="shark,hand,counter,noise")
    b.add_argument("--games", type=int, default=400)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--ticks", type=int, default=240)
    b.add_argument("--workers", type=int, default=None, help="processes (default: CPUs - 1)")

    args = ap.parse_args(argv)
    lineup = _lineup(args.lineup)
    rules = Rules(n_players=len(lineup), ticks=args.ticks)
    if args.cmd == "watch":
        watch(lineup, seed=args.seed, rules=rules, belief_every=args.beliefs_every, show_quotes=args.quotes)
    else:
        def progress(done: int, total: int) -> None:
            if done % max(1, total // 20) == 0 or done == total:
                print(f"\r{done}/{total} games", end="", file=sys.stderr, flush=True)

        res = run_tournament(lineup, games=args.games, seed=args.seed, rules=rules, workers=args.workers, progress=progress)
        print(file=sys.stderr)
        print(res.table())
    return 0


if __name__ == "__main__":
    sys.exit(main())
