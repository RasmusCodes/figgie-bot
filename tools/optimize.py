"""Search SharkParams for settings that do better across many kinds of table, without fitting
any one of them.

    python tools/optimize.py --base sharklive --candidates 32

Random search around a base with successive halving, on the arena (figgie.arena):

1. ``--candidates`` settings, each changing a few of the tunable parameters (SPACE) from the
   base, are scored on the training seeds at the training tables, paired against the base;
2. the best half are scored again on more training sessions (new seeds), and so on, so luck in
   one batch of deals does not carry a candidate through;
3. the finalists are scored on the validation seeds at every table, including ``--unseen``
   tables the search never played (opponent types it could not have fitted), and the best of
   them by validation score is the pick;
4. the pick alone is scored once on the holdout seeds.

The score is figgie.arena's: half the average paired gain over tables, half the average over
the worst quarter of tables, so a change has to help broadly.  Only parameters that shape how
the bot quotes, takes and holds are searched; the smart-money reading, which was fitted to
figgie.com's logged rounds, is left alone.  Everything is seeded: the same command prints the
same numbers, and ``--log`` keeps every candidate and score.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from figgie.arena import GROUPS, evaluate, paired, score  # noqa: E402
from figgie.shark import SharkParams  # noqa: E402

# name: (low, high, integer?) - the range a candidate may draw from
SPACE = {
    "take_edge": (0.0, 3.0, False),
    "take_frac": (0.05, 0.4, False),
    "quote_edge": (0.0, 3.0, False),
    "quote_frac": (0.05, 0.4, False),
    "adverse": (0.0, 0.35, False),
    "max_pay": (25.0, 70.0, False),
    "open_frac": (0.1, 0.7, False),
    "open_markup": (1.0, 6.0, False),
    "step_every": (1, 6, True),
    "hold_goal": (10.0, 40.0, False),
    "hold_dead": (0.0, 10.0, False),
    "sticky_halflife": (10.0, 60.0, False),
    "buy_halflife": (0.0, 20.0, False),
    "alpha_start": (1.5, 6.0, False),
    "alpha_end": (20.0, 60.0, False),
    "churn_guard": (0.3, 1.0, False),
    "churn_p": (0.05, 0.3, False),
    "fill_lr_offer": (1.0, 5.0, False),
}
UNSEEN = "selfplay,pennies,adaptive,five,quiet"


def parse_spec(spec: str):
    name, _, args = spec.partition(":")
    params = {}
    for part in filter(None, args.split(",")):
        k, _, v = part.partition("=")
        params[k] = v
    return name, params


def make_spec(name: str, params: dict) -> str:
    return name + (":" + ",".join(f"{k}={v}" for k, v in params.items()) if params else "")


def fmt(k: str, x) -> str:
    return str(int(x)) if SPACE[k][2] else f"{x:.3g}"


def sample(rng: random.Random, base: dict, k: int) -> dict:
    """The base with ``k`` parameters redrawn: half the time anywhere in their range, half the
    time within a fifth of the range of the base value (local refinement)."""
    defaults = SharkParams()
    out = dict(base)
    for key in rng.sample(sorted(SPACE), k):
        lo, hi, is_int = SPACE[key]
        cur = float(base.get(key, getattr(defaults, key)))
        if rng.random() < 0.5:
            x = rng.uniform(lo, hi)
        else:
            x = min(hi, max(lo, cur + rng.uniform(-0.2, 0.2) * (hi - lo)))
        out[key] = fmt(key, round(x) if is_int else x)
    return out


def run(variants, tables, split, sessions, rounds, first, workers):
    res = evaluate(variants, tables, split, sessions, rounds, workers, first)
    ref = variants[0]
    return {v: paired(res, ref, v) for v in variants[1:]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="sharklive")
    ap.add_argument("--candidates", type=int, default=32)
    ap.add_argument("--change", type=int, default=3, help="parameters each candidate redraws")
    ap.add_argument("--stages", default="4,8,16", help="training sessions per table at each halving stage")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--finalists", type=int, default=3)
    ap.add_argument("--val-sessions", type=int, default=16)
    ap.add_argument("--unseen", default=UNSEEN, help="tables held out of the search (scored on val and holdout only)")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # progress shows up even when redirected to a file
    unseen = [t for t in args.unseen.split(",") if t]
    train_tables = [t for t in GROUPS["all"] if t not in unseen]
    all_tables = GROUPS["all"]
    rng = random.Random(args.seed)
    name, base_params = parse_spec(args.base)
    base = args.base
    cands = []
    seen = set()
    while len(cands) < args.candidates:
        p = sample(rng, base_params, args.change)
        spec = make_spec(name, p)
        if spec not in seen and spec != base:
            seen.add(spec)
            cands.append(spec)
    log = {"argv": sys.argv, "base": base, "train_tables": train_tables, "unseen": unseen, "stages": []}
    first = 0
    alive = cands
    t0 = time.time()
    for st, sessions in enumerate(int(x) for x in args.stages.split(",")):
        diffs = run([base] + alive, train_tables, "train", sessions, args.rounds, first, args.workers)
        first += sessions  # each stage on fresh deals
        scored = sorted(((score(diffs[v])[0], v) for v in alive), reverse=True)
        log["stages"].append({"sessions": sessions, "scores": [[s, v] for s, v in scored]})
        print(f"stage {st + 1}: {len(alive)} candidates x {sessions} sessions ({time.time() - t0:.0f}s); best:")
        for s, v in scored[:5]:
            print(f"   {s:+6.2f}  {v}")
        keep = max(args.finalists, len(alive) // 2)
        alive = [v for _, v in scored[:keep]]
    alive = alive[: args.finalists]
    diffs = run([base] + alive, all_tables, "val", args.val_sessions, args.rounds, 0, args.workers)
    val = sorted(((score(diffs[v]), v) for v in alive), reverse=True)
    log["val"] = [[list(s), v, {t: list(d) for t, d in diffs[v].items()}] for s, v in val]
    print(f"validation, {args.val_sessions} sessions at all {len(all_tables)} tables ({time.time() - t0:.0f}s):")
    for (s, mean, cvar), v in val:
        un = sum(diffs[v][t][0] for t in unseen) / max(1, len(unseen))
        print(f"   score {s:+6.2f} (mean {mean:+.2f}, worst quarter {cvar:+.2f}, unseen tables {un:+.2f})  {v}")
    pick = val[0][1]
    diffs = run([base, pick], all_tables, "holdout", args.val_sessions, args.rounds, 0, args.workers)[pick]
    s, mean, cvar = score(diffs)
    un = sum(diffs[t][0] for t in unseen) / max(1, len(unseen))
    log["holdout"] = {"pick": pick, "score": [s, mean, cvar], "tables": {t: list(d) for t, d in diffs.items()}}
    print(f"holdout ({time.time() - t0:.0f}s): {pick}")
    print(f"   score {s:+.2f} (mean {mean:+.2f}, worst quarter {cvar:+.2f}, unseen tables {un:+.2f})")
    for t, (m, c) in diffs.items():
        print(f"     {t:<12}{m:+7.2f} ±{c:5.2f}")
    if args.log:
        Path(args.log).write_text(json.dumps(log, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
