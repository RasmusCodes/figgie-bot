"""Paired sessions: bots that learn as they play, compared on equal terms.

    python tools/sessions.py "shark:resale_cheap=2,resale_bid=true" \
        "shark:resale_cheap=2,resale_bid=true,resale_learn=true" --sessions 40 --rounds 10

A session is ROUNDS rounds in a row at one table: the same opponents in the same seats, and the
same bot object in ours, so whatever a variant learns carries from round to round (figgie.com
tables run like that).  Every variant plays every session on the same deals, and the table
prints each variant's P&L per round paired against the first one, with a 95% interval over
sessions, overall and split into the first three rounds (still learning) and the rest.
`figgie.compare` plays every game with fresh bots instead, which suits bots that don't learn.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from figgie.compare import FIELDS  # noqa: E402
from figgie.engine import Game, Rules  # noqa: E402
from figgie.tournament import make_bot  # noqa: E402

DEFAULT = "mixed,counters,oracles,strong-mix,osharks,spoofed,unspoofed,fickle,baited,bait-pair"


def play_session(job):
    """One variant, one session: the per-round P&L of our seat."""
    spec, field, seed, rounds = job
    seats = list(field) + ["ME"]
    random.Random(seed).shuffle(seats)
    me = seats.index("ME")
    bots = [make_bot(spec) if s == "ME" else make_bot(s) for s in seats]
    bots[me].name = "shark"  # the opponents see a shark, whichever variant it is
    rules = Rules(n_players=len(seats))
    return [Game(bots, rules=rules, seed=seed * 1000 + r).run().pnl[me] for r in range(rounds)]


def ci(xs):
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1))
    return m, 1.96 * sd / math.sqrt(len(xs))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("variants", nargs="+", help='bot specs; the first is the reference, e.g. "shark:resale_cheap=2"')
    ap.add_argument("--sessions", type=int, default=40)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--fields", default=DEFAULT, help=f"subset of: {', '.join(FIELDS)}")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    fields = args.fields.split(",")
    for spec in args.variants:
        make_bot(spec)  # fail fast on typos
    jobs = []
    for j, f in enumerate(fields):
        for i in range(args.sessions):
            seed = args.seed * 1_000_003 + 7919 * i + 104729 * j
            jobs += [(v, FIELDS[f], seed, args.rounds) for v in args.variants]
    with Pool(args.workers) as pool:
        res = pool.map(play_session, jobs, chunksize=1)
    out = iter(res)
    table = {f: [{v: next(out) for v in args.variants} for _ in range(args.sessions)] for f in fields}
    ref = args.variants[0]
    print(f"{args.sessions} sessions x {args.rounds} rounds per table; $ per round, paired against {ref}")
    tot = {v: [] for v in args.variants[1:]}
    for f in fields:
        base = [x for s in table[f] for x in s[ref]]
        line = f"  {f:<11} {sum(base) / len(base):+7.2f}"
        for v in args.variants[1:]:
            d = [[a - b for a, b in zip(s[v], s[ref])] for s in table[f]]
            m, c = ci([sum(x) / len(x) for x in d])
            m1, c1 = ci([sum(x[:3]) / 3 for x in d])
            m2, c2 = ci([sum(x[3:]) / max(1, len(x) - 3) for x in d]) if args.rounds > 3 else (0.0, 0.0)
            tot[v].append(m)
            line += f"   {m:+6.2f} ±{c:4.2f} (rounds 1-3 {m1:+6.2f}, later {m2:+6.2f})"
        print(line)
    for i, v in enumerate(args.variants[1:], 1):
        print(f"  variant {i} = {v}: average {sum(tot[v]) / len(tot[v]):+.2f} per round over {len(fields)} tables")


if __name__ == "__main__":
    main()
