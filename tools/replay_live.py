"""Replay logged live rounds through the Python bot, offline.

    python tools/replay_live.py              # check the replay against the live bot
    python tools/replay_live.py --trace 9    # second-by-second beliefs of round 9

data/live_logs_v9.json holds every quote and trade the v9 bot saw at figgie.com.
This feeds them, in order, to a fresh SharkBot with the live settings: quotes
and trades as events, and once per second of the round a turn on a market that
shows the logged book but refuses every order.  The bot's beliefs then evolve
as they did live, so it can be asked what it believed at any moment, and how
a changed model would have read the same round.  (Only beliefs replay
faithfully: the bot's own quotes and trades are whatever happened live, not
what a changed bot would have done.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from figgie.engine import GameInfo, Quote, QuoteEvent, Rules, Trade  # noqa: E402
from figgie.shark import SharkBot  # noqa: E402

SUITS = ["spades", "clubs", "hearts", "diamonds"]
SYM = "♠♣♥♦"
# What the v9 and v9.1 rounds ran with, in today's terms (LIVE_PARAMS plus the defaults v11 changed);
# later logs carry their own
LIVE = {"smart_consensus": 0.8, "sticky_halflife": 60.0, "adverse_offer": 1.0}


def parse_log(text: str) -> List[dict]:
    out = []
    for item in text.split(";"):
        k, at, s, p, who, pg, took = item.split(",")
        e = {"k": k, "at": float(at), "s": int(s), "p": int(p)}
        if k == "t":
            b, sl = who.split(">")
            e["b"], e["sl"] = int(b), int(sl)
            if pg:
                e["pg"] = [float(x) for x in pg.split("/")]
                e["took"] = took.startswith("T")
                e["resale"] = "R" in took  # v10 on: the trade bought or sold resale stock
        else:
            e["w"] = int(who)
        out.append(e)
    return out


class LoggedBook:
    """The logged order book at one moment; refuses every order."""

    def __init__(self, me: int, tick: int, book: Dict[tuple, Quote], hand, cash: int = 300) -> None:
        self.me, self.tick, self._book, self.hand, self.cash = me, tick, book, tuple(hand), cash

    def best_bid(self, s: int) -> Optional[Quote]:
        return self._book.get((s, True))

    def best_offer(self, s: int) -> Optional[Quote]:
        return self._book.get((s, False))

    def bid(self, s, price):
        return False

    offer = bid

    def buy(self, s, max_price=None):
        return False

    def sell(self, s, min_price=None):
        return False

    def cancel_bid(self, s):
        return False

    cancel_offer = cancel_bid


def replay(rnd: dict, params: Optional[dict] = None, every_second=None):
    """Feed one logged round to a fresh bot; call ``every_second(bot, tick)``
    after each one-second turn.  Returns the bot and, for each of its own
    trades, (logged P(goal), replayed P(goal) just before it)."""
    me = rnd["me"]
    bot = SharkBot(**{**rnd.get("live_params", LIVE), **(params or {})})
    bot.on_start(GameInfo(me, tuple(rnd["dealt"]), Rules(n_players=4), ("x",) * 4, 0))
    if bot.resale is not None and rnd.get("resale_seed"):
        bot.resale.seed(*rnd["resale_seed"])  # what the live bot carried over from earlier rounds
    book: Dict[tuple, Quote] = {}
    hand = list(rnd["dealt"])
    checks = []
    tick = -1
    for e in parse_log(rnd["log"]):
        t = min(239, max(0, int(240 - e["at"])))
        while tick < t:  # a turn at every second boundary we pass
            tick += 1
            bot.act(LoggedBook(me, tick, dict(book), hand))
            if every_second is not None:
                every_second(bot, tick)
        if e["k"] == "t":
            if "pg" in e:
                checks.append((e, bot.valuation(tick).p_goal[:]))
            bot.on_trade(Trade(tick, e["s"], e["p"], e["b"], e["sl"], -1))
            book.clear()  # every trade clears the book
            if e["b"] == me:
                hand[e["s"]] += 1
            elif e["sl"] == me:
                hand[e["s"]] -= 1
        elif e["k"] in ("xb", "xo"):  # a quote withdrawn without a trade (logged from v10 on)
            key = (e["s"], e["k"] == "xb")
            if key in book and book[key].player == e["w"]:
                del book[key]
        else:
            is_bid = e["k"] == "b"
            book[(e["s"], is_bid)] = Quote(e["p"], e["w"])
            if e["w"] != me:
                bot.on_quote(QuoteEvent(tick, e["s"], is_bid, e["p"], e["w"]))
    return bot, checks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trace", type=int, help="print one round's beliefs second by second (1-10)")
    ap.add_argument("--log", default="live_logs_v9.json", help="log file in data/ (default: live_logs_v9.json)")
    args = ap.parse_args()
    rounds = json.loads((ROOT / "data" / args.log).read_text(encoding="utf-8"))["rounds"]
    if args.trace:
        rnd = rounds[args.trace - 1]
        g = SUITS.index(rnd["goal"])
        print(f"round {args.trace}: goal {SYM[g]}, dealt {rnd['dealt']}")

        def show(bot, tick):
            if tick % 5 == 0:
                pg = bot.valuation(tick).p_goal
                print(f"  {tick:3d}s  " + "  ".join(f"{SYM[s]} {pg[s]:.2f}" for s in range(4)))

        replay(rnd, every_second=show)
        return
    worst = 0.0
    n = 0
    for i, rnd in enumerate(rounds, 1):
        _, checks = replay(rnd)
        for e, pg in checks:
            worst = max(worst, max(abs(a - b) for a, b in zip(e["pg"], pg)))
            n += 1
    print(f"{len(rounds)} rounds, {n} of the bot's own trades: largest gap between the live and the replayed P(goal) {worst:.3f}")


if __name__ == "__main__":
    main()
