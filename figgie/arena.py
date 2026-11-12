"""Seeded evaluation arena: shark variants against a population of tables, paired, with
separate training, validation and holdout seeds.

    python -m figgie.arena sharklive "sharklive:take_edge=2" --tables all --split val

A session is ``rounds`` rounds at one table: the same opponents in the same seats and the
same bot objects throughout, so whatever learns (our resale learner, the adaptive and
colluding opponents) carries from round to round, as at a real table.  Every variant plays
every session on the same deals and seats, so the differences between variants are paired.

Seeds come from three disjoint ranges.  Tune on ``train``, choose between candidates on
``val``, and report the final choice once on ``holdout``; a table's seeds depend only on its
name and the split, so adding tables never changes the others' deals, and every number can
be reproduced from the command line that printed it.

The score of a variant is ``0.5 * mean + 0.5 * cvar``: the average over tables of its paired
gain, and the average over the worst quarter of tables.  A change that wins big at one table
and loses at several does not score well.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import zlib
from multiprocessing import Pool
from typing import Dict, List, Optional, Sequence, Tuple

from .engine import Game, Rules
from .tournament import make_bot

# Opponents per table (our seat is added and the seats shuffled per session).
TABLES: Dict[str, List[str]] = {
    # the benchmark bots
    "mixed": ["hand", "counter", "noise"],
    "counters": ["counter", "counter", "counter"],
    "oracles": ["oracle", "oracle", "oracle"],
    "fickle": ["fickle", "fickle", "fickle"],
    # strong, realistic opponents: earlier and current sharks, partly informed
    "strong-mix": ["oshark", "oracle", "counter"],
    "osharks": ["oshark", "oshark", "oshark"],
    "selfplay": ["sharklive", "sharklive", "sharklive"],
    "self-mix": ["sharklive", "oshark", "fickle"],
    # adversaries (figgie.adversaries)
    "spoofed": ["spoofer", "oracle", "counter"],
    "baited": ["bait", "bait", "bait"],
    "bait2": ["bait2", "bait2", "bait2"],
    "bait-pair": ["bait", "bait", "fickle"],
    "pumped": ["pump", "pump", "pump"],
    "pump-pair": ["pump", "pump", "fickle"],
    "snipers": ["sniper", "sniper", "counter"],
    "pennies": ["penny", "oracle", "counter"],
    "quiet": ["quiet", "quiet", "fickle"],
    "holdout": ["holdout", "oracle", "counter"],
    "adaptive": ["adapt", "adapt", "fickle"],
    # other table sizes
    "five": ["hand", "counter", "noise", "oracle"],
    "trio": ["counter", "oracle"],
}
GROUPS: Dict[str, List[str]] = {
    "benchmark": ["mixed", "counters", "oracles", "fickle"],
    "strong": ["strong-mix", "osharks", "selfplay", "self-mix"],
    "adversarial": ["spoofed", "baited", "bait2", "bait-pair", "pumped", "pump-pair", "snipers", "pennies", "quiet", "holdout", "adaptive"],
    "sizes": ["five", "trio"],
}
GROUPS["all"] = [t for g in ("benchmark", "strong", "adversarial", "sizes") for t in GROUPS[g]]
SPLITS = {"train": 1, "val": 2, "holdout": 3}


def table_seed(split: str, table: str, i: int) -> int:
    """The seed of session ``i`` of ``table`` in ``split``: disjoint ranges per split, and
    independent of which other tables are evaluated."""
    return SPLITS[split] * 10**12 + (zlib.crc32(table.encode()) % 10**6) * 10**5 + i


def play_session(job: tuple) -> List[Tuple[float, float, int, int]]:
    """One variant, one session.  Per round: (P&L, share of the bonus won, goal cards held
    at the bell, other cards held at the bell) for our seat."""
    spec, lineup, seed, rounds = job
    seats = list(lineup) + ["ME"]
    random.Random(seed).shuffle(seats)
    me = seats.index("ME")
    bots = [make_bot(spec) if s == "ME" else make_bot(s) for s in seats]
    bots[me].name = "shark"  # the opponents see a shark, whichever variant it is
    rules = Rules(n_players=len(seats))
    out = []
    for r in range(rounds):
        res = Game(bots, rules=rules, seed=seed * 1000 + r).run()
        g = res.config.goal
        bonus = 1.0 / len(res.bonus_winners) if me in res.bonus_winners else 0.0
        hand = res.final_hands[me]
        out.append((res.pnl[me], bonus, hand[g], sum(hand) - hand[g]))
    return out


def evaluate(
    variants: Sequence[str],
    tables: Sequence[str],
    split: str = "train",
    sessions: int = 16,
    rounds: int = 5,
    workers: Optional[int] = None,
    first: int = 0,
) -> Dict[str, Dict[str, List[list]]]:
    """``results[table][variant]`` = per-session lists of per-round stats (see play_session),
    for sessions ``first`` .. ``first + sessions - 1`` of each table."""
    for v in variants:
        make_bot(v)  # fail fast on typos
    jobs, keys = [], []
    for t in tables:
        for i in range(first, first + sessions):
            seed = table_seed(split, t, i)
            for v in variants:
                jobs.append((v, TABLES[t], seed, rounds))
                keys.append((t, v))
    out: Dict[str, Dict[str, List[list]]] = {t: {v: [] for v in variants} for t in tables}
    if workers == 1:
        res = [play_session(j) for j in jobs]
    else:
        with Pool(workers) as pool:
            res = pool.map(play_session, jobs, chunksize=1)
    for (t, v), r in zip(keys, res):
        out[t][v].append(r)
    return out


def mean_ci(xs: Sequence[float]) -> Tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return m, float("nan")
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def per_session(sessions: List[list], k: int = 0) -> List[float]:
    """Each session's mean, per round, of stat ``k`` (0: P&L)."""
    return [sum(r[k] for r in s) / len(s) for s in sessions]


def paired(results: Dict[str, Dict[str, List[list]]], ref: str, v: str) -> Dict[str, Tuple[float, float]]:
    """Per table: variant minus reference, $ per round, with a 95% interval over sessions."""
    out = {}
    for t, by in results.items():
        d = [a - b for a, b in zip(per_session(by[v]), per_session(by[ref]))]
        out[t] = mean_ci(d)
    return out


def score(diffs: Dict[str, Tuple[float, float]]) -> Tuple[float, float, float]:
    """(score, mean over tables, mean over the worst quarter of tables)."""
    xs = sorted(m for m, _ in diffs.values())
    k = max(1, len(xs) // 4)
    mean = sum(xs) / len(xs)
    cvar = sum(xs[:k]) / k
    return 0.5 * mean + 0.5 * cvar, mean, cvar


def report(results: Dict[str, Dict[str, List[list]]], variants: Sequence[str]) -> str:
    ref = variants[0]
    lines = [f"{'table':<12}{'ref $/rd':>9}{'dead':>6}{'bonus':>7}" + "".join(f"{'v' + str(i):>17}" for i in range(1, len(variants)))]
    for t, by in results.items():
        base = per_session(by[ref])
        line = f"{t:<12}{sum(base) / len(base):>+9.2f}{sum(per_session(by[ref], 3)) / len(base):>6.1f}{sum(per_session(by[ref], 1)) / len(base):>7.0%}"
        for v in variants[1:]:
            m, c = mean_ci([a - b for a, b in zip(per_session(by[v]), base)])
            line += f"{m:>+10.2f} ±{c:5.2f}"
        lines.append(line)
    for i, v in enumerate(variants[1:], 1):
        s, mean, cvar = score(paired(results, ref, v))
        lines.append(f"v{i} = {v}: score {s:+.2f} (mean {mean:+.2f}, worst quarter {cvar:+.2f})")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m figgie.arena", description=__doc__.split("\n\n")[0])
    ap.add_argument("variants", nargs="+", help="bot specs; the first is the reference")
    ap.add_argument("--tables", default="all", help=f"groups ({', '.join(GROUPS)}) and/or table names, comma-separated")
    ap.add_argument("--split", default="val", choices=list(SPLITS))
    ap.add_argument("--sessions", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--first", type=int, default=0, help="index of the first session (to extend an earlier run)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--json", default=None, help="write the raw per-round results here")
    args = ap.parse_args(argv)
    tables: List[str] = []
    for part in args.tables.split(","):
        for t in GROUPS.get(part, [part]):
            if t not in TABLES:
                ap.error(f"unknown table {t!r}")
            if t not in tables:
                tables.append(t)
    t0 = time.time()
    res = evaluate(args.variants, tables, args.split, args.sessions, args.rounds, args.workers, args.first)
    print(f"{args.split}: {args.sessions} sessions x {args.rounds} rounds per table, paired against {args.variants[0]}"
          f" ({time.time() - t0:.0f}s); columns: our $/round, dead cards at the bell, bonus won; then each variant's gain")
    print(report(res, args.variants))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"argv": sys.argv, "split": args.split, "variants": args.variants, "results": res}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
