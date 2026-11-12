"""The value of information: what knowing the goal earlier would be worth to the shark.

    python tools/info_value.py --tables mixed,oracles,fickle,osharks,selfplay --sessions 16

For each reveal time T (ticks into the round) an "informed" copy of the bot is told the goal
at T (every deck with that goal gets ``strength`` times the weight from then on) and plays the
same deals and seats as the plain bot.  The paired difference is the most any way of learning
the goal by time T could add, including trades made only to learn something; the drop from
T=0 to later T is what earlier information is worth.  Simulator only: the informed bot sees
the deck through the oracle hook, which the real bot never has.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from figgie.arena import GROUPS, TABLES, evaluate, mean_ci, per_session  # noqa: E402
from figgie.engine import CONFIGS  # noqa: E402
from figgie.shark import SHARK_LIVE, SharkBot  # noqa: E402
from figgie.tournament import REGISTRY  # noqa: E402


class InformedShark(SharkBot):
    """The live bot, told the goal ``reveal`` ticks into the round."""

    oracle = True

    def __init__(self, reveal: int = 0, strength: float = 1000.0, **params) -> None:
        super().__init__(**{**SHARK_LIVE, **params})
        self.reveal = reveal
        self.strength = strength

    def on_oracle(self, config) -> None:
        self._goal = config.goal

    def act(self, m) -> None:
        if m.tick == self.reveal or (m.tick > self.reveal and self.beliefs.prior is None):
            self.beliefs.prior = [self.strength if c.goal == self._goal else 1.0 for c in CONFIGS]
            self.beliefs._mins_state += 1
            self._dirty = True
        super().act(m)


REGISTRY["informed"] = InformedShark  # registered at import, so the arena's worker processes see it


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tables", default="mixed,oracles,fickle,osharks,selfplay")
    ap.add_argument("--reveal", default="0,30,60,120,180")
    ap.add_argument("--sessions", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--split", default="train")
    args = ap.parse_args()
    tables = [t for part in args.tables.split(",") for t in GROUPS.get(part, [part])]
    reveals = [int(x) for x in args.reveal.split(",")]
    variants = ["sharklive"] + [f"informed:reveal={t}" for t in reveals]
    res = evaluate(variants, tables, args.split, args.sessions, args.rounds, first=200)
    print(f"$ per round gained by being told the goal at tick T (paired, {args.sessions} sessions x {args.rounds} rounds)")
    print(f"{'table':<12}{'bot $/rd':>9}" + "".join(f"{'T=' + str(t):>15}" for t in reveals))
    for t in tables:
        base = per_session(res[t]["sharklive"])
        line = f"{t:<12}{sum(base) / len(base):>+9.2f}"
        for v in variants[1:]:
            m, c = mean_ci([a - b for a, b in zip(per_session(res[t][v]), base)])
            line += f"{m:>+9.2f} ±{c:4.1f}"
        print(line)


if __name__ == "__main__":
    main()
