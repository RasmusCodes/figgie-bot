"""Paper-trade the cheap-resale exploit (figgie/patterns.py) on logged live rounds.

    python tools/paper_resale.py                      # every data/live_logs_*.json
    python tools/paper_resale.py --carry --log live_logs_v91.json

Walks each logged round in time order with a ResaleTracker.  It buys another player's
offer at $2 or less when the tracker says the pattern pays and nobody else traded that
suit within a second, and sells each card into the first other player's bid at the
tracker's resale target that the logged bot did not itself sell into.  Unsold cards are
worth $10 at the bell if their suit was the goal.  It ignores that its own trades would
clear the book and change what the bots do next, so it is a rough check of the pattern,
not of the bot (tools/paper_bot.py runs the bot's own code).  --carry seeds each round
with what the earlier rounds of the same file showed, as the live adapter does.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from figgie.patterns import ResaleTracker  # noqa: E402
from replay_live import SUITS, parse_log  # noqa: E402


def paper_round(rnd: dict, cheap=2, min_left=15, edge=0.5, suit_cap=2, total_cap=4, patience=30, memory=None):
    me = rnd["me"]
    goal = SUITS.index(rnd["goal"])
    events = parse_log(rnd["log"])
    for e in events:
        e["t"] = 240 - e["at"]
    tr = ResaleTracker(cheap=cheap)
    if memory is not None:
        tr.seed(*memory)
    cash = 0
    trades = []
    for i, e in enumerate(events):
        t, s, p = e["t"], e["s"], e["p"]
        tr.expire(t)
        if e["k"] == "o" and e["w"] != me:
            tr.cheap_seen(t, s, p, e["w"])
            if p > cheap or 240 - t < min_left:
                continue
            taken = any(f["k"] == "t" and f["s"] == s for f in events[i + 1 : i + 30] if f["t"] - t <= 1.0)
            g = tr.value(p)
            if not taken and g is not None and g >= edge and tr.held(s) < suit_cap and tr.held_total() < tr.allowed(total_cap):
                tr.bought(t, s, p)
                cash -= p
                trades.append(("B", t, s, p))
        elif e["k"] == "b" and e["w"] != me:
            tr.bid_seen(t, s, p, e["w"])
            # the logged bot sold one of its own cards into this bid: not there for us
            used = any(
                f["k"] == "t" and f["sl"] == me and f["b"] == e["w"] and f["s"] == s and f["p"] == p
                for f in events[i + 1 : i + 40]
                if f["t"] - t <= 3.0
            )
            if tr.held(s) and not used and p >= tr.target(s, t, patience):
                tr.sold(s, p)
                cash += p
                trades.append(("S", t, s, p))
        elif e["k"] == "t":
            if e["b"] != me:
                tr.bid_seen(t, s, p, e["b"])
            if e["sl"] != me and e["b"] != me:
                tr.cheap_seen(t, s, p, e["sl"])
    left = tr.held_total()
    return cash + 10 * tr.held(goal), trades, left, tr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--log", action="append", help="log file(s) in data/ (default: all live_logs_*.json)")
    ap.add_argument("--carry", action="store_true", help="carry the tracker's record from round to round")
    ap.add_argument("--min-left", type=int, default=15)
    args = ap.parse_args()
    files = args.log or sorted(p.name for p in (ROOT / "data").glob("live_logs_*.json"))
    for f in files:
        rounds = json.loads((ROOT / "data" / f).read_text(encoding="utf-8"))["rounds"]
        memory = None
        total = buys = sells = left_total = 0
        for i, rnd in enumerate(rounds, 1):
            pnl, trades, left, tr = paper_round(rnd, min_left=args.min_left, memory=memory)
            if args.carry:
                memory = tr.memory()
            total += pnl
            buys += sum(1 for x in trades if x[0] == "B")
            sells += sum(1 for x in trades if x[0] == "S")
            left_total += left
            desc = " ".join(f"{x[0]}{'SCHD'[x[2]]}{x[3]}@{x[1]:.0f}" for x in trades)
            print(f"{f:<20} round {i:>2}: {pnl:+4d}  p(hit) {tr.p_hit():.2f}  {desc}")
        print(f"{f}: {total:+d} over {len(rounds)} rounds ({total / len(rounds):+.1f}/round), {buys} buys, {sells} resales, {left_total} unsold")


if __name__ == "__main__":
    main()
