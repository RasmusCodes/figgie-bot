"""Fit and check the bot's bid-reading ("smart money") against logged live rounds.

    python tools/fit_smart_money.py

Reads data/live_rounds.json (rounds played against figgie.com's Hard bots) and,
for each round, scores P(true goal | dealt hand, bids) under several rules:
the dealt hand alone, the v2-v6 rule, the v7 rule (fitted on the v2-v6 rounds
and so out of sample on v7), and the v7 rule plus the consensus term built from
the lowest of the per-bot top bids (logged from v7 on: in sample on v7, where
the pattern was found, and out of sample on v8 and v9).
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from figgie.engine import CONFIGS  # noqa: E402
from figgie.model import posterior  # noqa: E402

SUITS = ["spades", "clubs", "hearts", "diamonds"]
ROUNDS = json.loads((ROOT / "data" / "live_rounds.json").read_text(encoding="utf-8"))["rounds"]


def bid_llr(bid, mid, up, down, cap, weight=1.0):
    d = bid - mid
    return weight * max(-cap, min(cap, (up if d > 0 else down) * d))


def score(rounds, llr):
    """Total log-likelihood of the true goal, and how often it is the favourite."""
    ll, hits = 0.0, 0
    for r in rounds:
        prior = posterior(r["dealt"], [], 10, 3)
        lr = [math.exp(llr(r, s)) for s in range(4)]
        w = [p * lr[c.goal] for p, c in zip(prior, CONFIGS)]
        total = sum(w)
        pg = [0.0] * 4
        for wi, c in zip(w, CONFIGS):
            pg[c.goal] += wi / total
        goal = SUITS.index(r["goal"])
        ll += math.log(max(pg[goal], 1e-12))
        hits += max(range(4), key=pg.__getitem__) == goal
    return ll, hits


def v6_rule(r, s):
    return bid_llr(r["top_bids"][s], 8, 0.45, 0.08, 3.0, 1.6)


def v7_rule(r, s):
    return bid_llr(r["top_bids"][s], 17, 0.8, 0.3, 10.0)


def lowest_top_bid(r, s, none=4):
    """The lowest of the other players' own top bids on suit s; a player who never bid it
    counts as bidding ``none`` (the bot's smart_bid_none)."""
    return min(none if b[s] is None else b[s] for b in r["top_bids_by_bot"])


def consensus(slope, mid, cap):
    def f(r, s):
        return v7_rule(r, s) + min(cap, slope * max(0.0, lowest_top_bid(r, s) - mid))

    return f


def main() -> None:
    early = [r for r in ROUNDS if r["version"] in ("v2", "v3", "v4", "v5", "v6")]
    v7 = [r for r in ROUNDS if r["version"] == "v7"]

    print(f"{len(ROUNDS)} logged rounds; {len(early)} from v2-v6 were used to fit the v7 rule")
    print("\nOut of sample: the v7 rounds, scored by rules fitted before they were played")
    for name, rule in [("dealt hand only", lambda r, s: 0.0), ("v2-v6 rule", v6_rule), ("v7 rule", v7_rule)]:
        ll, hits = score(v7, rule)
        print(f"  {name:28s} log-lik {ll:7.2f}   goal named {hits}/{len(v7)}")

    print("\nRefit of the v7 rule on all rounds (mid, up, down, cap):")
    grid = itertools.product(range(12, 21), [0.4, 0.6, 0.8, 1.0], [0.15, 0.3, 0.45], [6, 10])
    ll, g = max(((score(ROUNDS, lambda r, s, g=g: bid_llr(r["top_bids"][s], *g))[0], g) for g in grid))
    print(f"  best {g}  log-lik {ll:.2f} over {len(ROUNDS)} rounds")

    # The consensus term was designed on the v7 rounds and first used live in v8.
    for ver, label in (
        ("v7", "in sample (where the pattern was found)"),
        ("v8", "out of sample"),
        ("v9", "out of sample"),
        ("v9.1", "out of sample"),
        ("v10", "out of sample"),
        ("v11", "out of sample"),
        ("v12", "out of sample"),
    ):
        rounds = [r for r in ROUNDS if r["version"] == ver and "top_bids_by_bot" in r]
        if not rounds:
            continue
        print(f"\nConsensus (lowest per-bot top bid), {ver} rounds - {label}:")
        goal_lows = [lowest_top_bid(r, SUITS.index(r["goal"])) for r in rounds]
        dead_lows = [lowest_top_bid(r, s) for r in rounds for s in range(4) if s != SUITS.index(r["goal"])]
        print(f"  goal suit:  {sorted(goal_lows)}")
        print(f"  dead suits: {sorted(dead_lows)}")
        for name, rule in [("v7 rule", v7_rule), ("v7 rule + consensus (v8)", consensus(0.8, 5, 4))]:
            ll, hits = score(rounds, rule)
            print(f"  {name:28s} log-lik {ll:7.2f}   goal named {hits}/{len(rounds)}")


if __name__ == "__main__":
    main()
