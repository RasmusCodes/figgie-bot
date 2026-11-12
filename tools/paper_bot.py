"""Counterfactual replay: what would a changed bot have taken from the logged live books?

    python tools/paper_bot.py resale_cheap=2               # vs the settings each round was played with
    python tools/paper_bot.py hold_dead=3 --log live_logs_v91.json
    python tools/paper_bot.py --quotes sticky_halflife=30  # let its resting quotes fill too

Like replay_live.py, but the bot's turns run on a book that lets it hit the logged
bids and lift the logged offers of the other players (its resting quotes never fill).
Those paper trades feed back into the bot, so its hand and beliefs follow them. The
live trades of our own seat stay in (they happened), except a live sale of a card
already sold on paper, which is struck out along with its proceeds.

Each round is scored against what really happened: paper sales - paper purchases -
struck-out live proceeds + $10 x the change in goal cards held at the bell (the bonus
is only flagged).  Every take the bot tries fills, which the live bot's don't, so even
the unchanged bot scores below zero; read a variant by its difference from the
unchanged bot on the same rounds, which is what this prints.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from figgie.engine import GameInfo, Quote, QuoteEvent, Rules, Trade  # noqa: E402
from figgie.shark import SharkBot  # noqa: E402
from figgie.tournament import _parse_value  # noqa: E402
from replay_live import LIVE, SUITS, parse_log  # noqa: E402


class PaperBook:
    """The logged book at one moment, on which the bot's takes fill against the logged quotes.

    With ``mine`` (a dict (suit, is_bid) -> price that persists between turns) the bot's own
    quotes rest in the book too, under the engine's rules, and paper_round fills them when a
    logged order would have crossed them.  Without it they are refused."""

    def __init__(self, me, tick, book: Dict[tuple, Quote], hand, cash, sink, mine: Optional[dict] = None):
        self.me, self.tick, self._book, self._hand, self.cash, self.sink = me, tick, book, hand, cash, sink
        self.mine = mine

    @property
    def hand(self):
        return tuple(self._hand)

    def best_bid(self, s) -> Optional[Quote]:
        q = self._book.get((s, True))
        if self.mine is not None and (s, True) in self.mine and (q is None or self.mine[(s, True)] > q.price):
            return Quote(self.mine[(s, True)], self.me)
        return q

    def best_offer(self, s) -> Optional[Quote]:
        q = self._book.get((s, False))
        if self.mine is not None and (s, False) in self.mine and (q is None or self.mine[(s, False)] < q.price):
            return Quote(self.mine[(s, False)], self.me)
        return q

    def bid(self, s, price):
        if self.mine is None:
            return False
        off = self.best_offer(s)
        if off is not None and price >= off.price:
            return False if off.player == self.me else self.buy(s, max_price=off.price)
        cur = self.best_bid(s)
        if price > self.cash or (cur is not None and price <= cur.price):
            return False
        self.mine[(s, True)] = price
        return True

    def offer(self, s, price):
        if self.mine is None or self._hand[s] <= 0:
            return False
        bid = self.best_bid(s)
        if bid is not None and price <= bid.price:
            return False if bid.player == self.me else self.sell(s, min_price=bid.price)
        cur = self.best_offer(s)
        if cur is not None and price >= cur.price:
            return False
        self.mine[(s, False)] = price
        return True

    def cancel_bid(self, s):
        return self.mine is not None and self.mine.pop((s, True), None) is not None

    def cancel_offer(self, s):
        return self.mine is not None and self.mine.pop((s, False), None) is not None

    def sell(self, s, min_price=None):
        q = self._book.get((s, True))
        if q is None or q.player == self.me or self._hand[s] <= 0 or (min_price is not None and q.price < min_price):
            return False
        self.sink.append(Trade(self.tick, s, q.price, q.player, self.me, self.me))
        return self.sink[-1]

    def buy(self, s, max_price=None):
        q = self._book.get((s, False))
        if q is None or q.player == self.me or q.price > self.cash or (max_price is not None and q.price > max_price):
            return False
        self.sink.append(Trade(self.tick, s, q.price, self.me, q.player, self.me))
        return self.sink[-1]


def paper_round(rnd: dict, params: dict, quotes: bool = False, seed: Optional[list] = None, keep: Optional[dict] = None):
    """Replay one round with ``params`` on top of its live settings.  Returns the score
    against what happened, the paper trades, and the change in goal cards held.

    With ``quotes`` the bot's resting bids and offers stand in the logged book in place of the
    live bot's, and fill whenever another player's logged order would have crossed them: a bid
    at or above our offer, an offer at or below our bid, or a trade between others at a price
    that our quote beat (whoever paid that price would have taken ours).  Every trade clears
    the book, as at figgie.com.

    The resale record the bot starts with is ``seed`` if given (an empty list: none), else the
    one logged with the round; ``keep``, if given, receives the bot's record at the end
    (``keep["memory"]``) to carry into the next round."""
    me = rnd["me"]
    goal = SUITS.index(rnd["goal"])
    bot = SharkBot(**{**rnd.get("live_params", LIVE), **params})
    bot.on_start(GameInfo(me, tuple(rnd["dealt"]), Rules(n_players=4), ("x",) * 4, 0))
    resale_seed = seed if seed is not None else rnd.get("resale_seed")
    if bot.resale is not None and resale_seed:
        bot.resale.seed(*resale_seed)
    book: Dict[tuple, Quote] = {}
    mine: Optional[dict] = {} if quotes else None
    hand = list(rnd["dealt"])
    live_hand = list(rnd["dealt"])
    cash = 150
    delta = 0
    paper = []
    tick = -1

    def apply(t: Trade):
        nonlocal cash, delta
        if t.seller == me:
            hand[t.suit] -= 1
            cash += t.price
            delta += t.price
        else:
            hand[t.suit] += 1
            cash -= t.price
            delta -= t.price
        paper.append(t)
        book.pop((t.suit, t.seller == me), None)  # the quote it traded with is gone
        if mine is not None:
            mine.clear()
        bot.on_trade(t)

    def fill(s: int, sell: bool, other: int) -> bool:
        """Fill our resting offer (sell) or bid in suit s against player ``other``."""
        key = (s, not sell)
        if mine is None or key not in mine or (sell and hand[s] <= 0):
            return False
        q = mine[key]
        apply(Trade(tick, s, q, other, me, other) if sell else Trade(tick, s, q, me, other, other))
        return True

    for e in parse_log(rnd["log"]):
        t = min(239, max(0, int(240 - e["at"])))
        while tick < t:
            tick += 1
            sink: list = []
            bot.act(PaperBook(me, tick, book, hand, cash, sink, mine))
            for tr in sink:
                apply(tr)
        if e["k"] == "t":
            s, p = e["s"], e["p"]
            if e["sl"] == me:
                live_hand[s] -= 1
                if hand[s] <= 0:
                    delta -= p  # this live sale could not have happened: the card was sold on paper
                    book.clear()
                    if mine is not None:
                        mine.clear()
                    continue
                hand[s] -= 1
                cash += p
            elif e["b"] == me:
                live_hand[s] += 1
                hand[s] += 1
                cash -= p
            elif mine is not None:
                # a trade between others: whoever paid p would have taken our cheaper offer,
                # whoever accepted p would have sold into our higher bid
                if (s, False) in mine and mine[(s, False)] <= p:
                    fill(s, True, e["b"])
                elif (s, True) in mine and mine[(s, True)] >= p:
                    fill(s, False, e["sl"])
            bot.on_trade(Trade(tick, s, p, e["b"], e["sl"], -1))
            book.clear()
            if mine is not None:
                mine.clear()
        elif e["k"] in ("xb", "xo"):
            if mine is not None and e["w"] == me:
                continue  # the live bot's quotes are replaced by the paper bot's
            key = (e["s"], e["k"] == "xb")
            if key in book and book[key].player == e["w"]:
                del book[key]
        else:
            s, p, is_bid = e["s"], e["p"], e["k"] == "b"
            if mine is not None and e["w"] == me:
                continue
            if mine is not None and is_bid and (s, False) in mine and mine[(s, False)] <= p:
                fill(s, True, e["w"])  # their bid crossed our resting offer
                continue
            if mine is not None and not is_bid and (s, True) in mine and mine[(s, True)] >= p:
                fill(s, False, e["w"])  # their offer crossed our resting bid
                continue
            book[(s, is_bid)] = Quote(p, e["w"])
            if e["w"] != me:
                bot.on_quote(QuoteEvent(tick, s, is_bid, p, e["w"]))
    dgoal = hand[goal] - live_hand[goal]
    if keep is not None and bot.resale is not None:
        keep["memory"] = bot.resale.memory()
    return delta + 10 * dgoal, paper, dgoal


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("params", nargs="*", help="SharkParams overrides, e.g. resale_cheap=2")
    ap.add_argument("--log", action="append", help="log file(s) in data/ (default: all live_logs_*.json)")
    ap.add_argument("--quotes", action="store_true", help="let the bot's resting quotes fill too (see paper_round)")
    ap.add_argument("--base", default="", help="settings for both bots on top of each round's live ones, e.g. resale_cheap=2,resale_bid=true")
    ap.add_argument("--carry", action="store_true", help="each bot carries its own resale record from round to round (from a cold start) instead of the logged one")
    args = ap.parse_args()
    params = {}
    for a in args.params:
        k, _, v = a.partition("=")
        params[k] = _parse_value(v)
    base_params = {}
    for a in filter(None, args.base.split(",")):
        k, _, v = a.partition("=")
        base_params[k] = _parse_value(v)
    params = {**base_params, **params}
    files = args.log or sorted(p.name for p in (ROOT / "data").glob("live_logs_*.json"))
    total = 0.0
    n = 0
    flagged: list = []
    mem_base = mem_var = None
    for f in files:
        rounds = json.loads((ROOT / "data" / f).read_text(encoding="utf-8"))["rounds"]
        for i, rnd in enumerate(rounds, 1):
            kb: dict = {}
            kv: dict = {}
            sb = (mem_base or []) if args.carry else None
            sv = (mem_var or []) if args.carry else None
            base, _, base_goal = paper_round(rnd, base_params, args.quotes, sb, kb)
            score, paper, dgoal = paper_round(rnd, params, args.quotes, sv, kv)
            mem_base, mem_var = kb.get("memory"), kv.get("memory")
            d = score - base
            total += d
            n += 1
            if dgoal != base_goal:
                flagged.append(d)
            trades = " ".join(f"{'S' if t.seller == rnd['me'] else 'B'}{'SCHD'[t.suit]}{t.price}@{t.tick}" for t in paper)
            flag = f"  goal cards {dgoal - base_goal:+d} (bonus not counted)" if dgoal != base_goal else ""
            print(f"{f:<20} round {i:>2}: {d:+5.0f}{flag}   {trades}")
    print(
        f"{params or 'no change'}: {total:+.0f} over {n} rounds ({total / max(1, n):+.2f}/round) against the unchanged bot;"
        f" {len(flagged)} rounds end with a different number of goal cards ({sum(flagged):+.0f} of the total)"
    )


if __name__ == "__main__":
    main()
