"""Generate cross-check vectors for the JavaScript port in web/figgie-shark.user.js.

Plays simulated games, snapshots the shark's view of the table at several
moments, and records what the Python model and bot compute from each snapshot
(posteriors, quote-reading likelihoods, card values, and the exact orders the
bot sends).  tests/js_harness.html recomputes everything in JavaScript and
compares.

    python tests/make_js_vectors.py      # writes tests/js_vectors.json
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from figgie.engine import NUM_SUITS, Game, GameInfo, Quote, QuoteEvent, Rules  # noqa: E402
from figgie.model import (  # noqa: E402
    posterior,
    quote_likelihood,
    smart_money_likelihood,
    smart_money_votes_likelihood,
    value_cards,
)
from figgie.patterns import ReadingLearner, ResaleLearner  # noqa: E402
from figgie.shark import SharkBot  # noqa: E402
from figgie.tournament import REGISTRY, _parse_value, make_bot  # noqa: E402


class RecordingMarket:
    """Minimal market with the engine's order semantics that records every order."""

    def __init__(self, me, tick, book, hand, cash):
        self.me = me
        self.tick = tick
        self.bids = [None if b is None else Quote(*b) for b, _ in book]
        self.offers = [None if o is None else Quote(*o) for _, o in book]
        self._hand = list(hand)
        self.cash = cash
        self.ops = []

    @property
    def hand(self):
        return tuple(self._hand)

    def best_bid(self, s):
        return self.bids[s]

    def best_offer(self, s):
        return self.offers[s]

    def _clear(self):
        self.bids = [None] * NUM_SUITS
        self.offers = [None] * NUM_SUITS

    def bid(self, s, price):
        self.ops.append(["bid", s, price])
        off = self.offers[s]
        if off is not None and price >= off.price:
            if off.player == self.me:
                return False
            self._clear()
            return True
        cur = self.bids[s]
        if cur is not None and price <= cur.price:
            return False
        self.bids[s] = Quote(price, self.me)
        return True

    def offer(self, s, price):
        self.ops.append(["offer", s, price])
        bid = self.bids[s]
        if bid is not None and price <= bid.price:
            if bid.player == self.me:
                return False
            self._clear()
            return True
        cur = self.offers[s]
        if cur is not None and price >= cur.price:
            return False
        self.offers[s] = Quote(price, self.me)
        return True

    def buy(self, s, max_price=None):
        self.ops.append(["buy", s, max_price])
        off = self.offers[s]
        if off is None or off.player == self.me or (max_price is not None and off.price > max_price):
            return False
        self._clear()
        return True

    def sell(self, s, min_price=None):
        self.ops.append(["sell", s, min_price])
        bid = self.bids[s]
        if bid is None or bid.player == self.me or (min_price is not None and bid.price < min_price):
            return False
        self._clear()
        return True

    def cancel_bid(self, s):
        self.ops.append(["cancel_bid", s])
        if self.bids[s] is not None and self.bids[s].player == self.me:
            self.bids[s] = None
            return True
        return False

    def cancel_offer(self, s):
        self.ops.append(["cancel_offer", s])
        if self.offers[s] is not None and self.offers[s].player == self.me:
            self.offers[s] = None
            return True
        return False


def take_snapshot(game, seat, tick):
    """The shark in ``seat``: everything its next turn (at ``tick``) depends on."""
    bot = game.bots[seat]
    b = bot.beliefs
    return {
                "seed": game.seed,
                "tick": tick,
                "n_players": game.rules.n_players,
                "hand_size": game.rules.hand_size,
                "me": seat,
                "hand0": list(b.hand0),
                "net": [list(x) for x in b.net],
                "mins": [list(x) for x in b.mins],
                "quotes": {str(p): [[s, ib, px] for (s, ib), px in b.quotes[p].items()] for p in b.others},
                "top_bid": list(b.top_bid),
                "low_offer": list(b.low_offer),
                "top_by": {str(p): list(b.top_by[p]) for p in b.others},
                "low_by": {str(p): list(b.low_by[p]) for p in b.others},
                "cost": list(bot.cost),
                "bought": list(bot.bought),
                "p_sticky": None if bot.p_sticky is None else list(bot.p_sticky),
                "p_avg": None if bot.p_avg is None else list(bot.p_avg),
                "p_tick": bot._p_tick,
                "pending": [[s, list(ev), seen, last] for s, (ev, seen, last) in bot._pending.items()],
                "resale": None if bot.resale is None else {
                    "open": [list(e) for e in bot.resale.open],
                    "hits": bot.resale.hits,
                    "misses": bot.resale.misses,
                    "prices": list(bot.resale.prices),
                    "inventory": [[list(it) for it in bot.resale.inventory[s]] for s in range(NUM_SUITS)],
                    "own_hits": bot.resale.own_hits,
                    "own_misses": bot.resale.own_misses,
                    "realized": bot.resale.realized,
                },
                "resale_bids": list(bot._resale_bids),
                "learner": bot.learner.state() if bot.learner is not None and bot.resale is bot.learner else None,
                "book": [
                    [
                        None if game.bids[s] is None else [game.bids[s].price, game.bids[s].player],
                        None if game.offers[s] is None else [game.offers[s].price, game.offers[s].player],
                    ]
                    for s in range(NUM_SUITS)
                ],
                "hand": list(game.hands[seat]),
                "cash": game.cash[seat],
            }


class Snapshotter:
    def __init__(self, seat, ticks):
        self.seat = seat
        self.ticks = set(ticks)
        self.snaps = []

    def on_tick(self, game):
        if game.tick in self.ticks:
            self.snaps.append(take_snapshot(game, self.seat, game.tick + 1))


class ResaleProbe(SharkBot):
    """The shark, snapshotting itself before every turn; keeps the snapshots of the turns in
    which it traded resale stock (rare events that fixed-tick snapshots seldom catch)."""

    name = "probe"

    def on_start(self, info):
        super().on_start(info)
        self.snaps = []

    def act(self, m):
        snap = take_snapshot(m._game, self.me, m.tick)
        before = self.resale.held_total() if self.resale is not None else 0
        super().act(m)
        if self.resale is not None and self.resale.held_total() != before:
            self.snaps.append(snap)


def expected(snap: dict, params: dict) -> dict:
    me, H, n = snap["me"], snap["hand_size"], snap["n_players"]
    kitty, pot = max(0, 40 - H * n), (200 // n) * n  # three players: one card dealt to nobody, $198 pot
    others = [p for p in range(n) if p != me]
    mins = [snap["mins"][p] for p in others]
    nets = [snap["net"][p] for p in others]
    quotes = [{(s, bool(ib)): px for s, ib, px in snap["quotes"][str(p)]} for p in others]
    hand0 = snap["hand0"]
    hand_now = [hand0[s] + snap["net"][me][s] for s in range(NUM_SUITS)]
    bot = SharkBot(**params)  # its reading / smart-money models are what the JS port must match
    qlik = quote_likelihood(hand0, mins, quotes, H, bot.reading)
    if bot.smart.player_cap > 0:
        slik = smart_money_votes_likelihood(
            [snap["top_by"][str(p)] for p in others], [snap["low_by"][str(p)] for p in others], bot.smart
        )
    else:
        slik = smart_money_likelihood(
            snap["top_bid"], snap["low_offer"], bot.smart, [snap["top_by"][str(p)] for p in others]
        )
    post = posterior(hand0, mins, H, n - 1, [a * b for a, b in zip(qlik, slik)], kitty)
    out = {
        "post_plain": posterior(hand0, mins, H, n - 1, None, kitty),
        "quote_lik": qlik,
        "smart_lik": slik,
        "post": post,
        "values": {},
    }
    for alpha in (3.0, 12.34, None):
        v = value_cards(
            post, hand0, hand_now, mins, nets, H, alpha, bot.params.consolidate, bot.params.consolidate_at, kitty, pot
        )
        out["values"][str(alpha)] = {
            "p_goal": v.p_goal, "buy": v.buy, "sell": v.sell,
            "buy_from": v.buy_from, "sell_to": v.sell_to, "expected": v.expected,
        }
    # The bot's orders from a cold start on this snapshot.
    rules = Rules(n_players=n)
    bot.on_start(GameInfo(me, tuple(hand0), rules, tuple("x" * n), 0))
    bot.beliefs.net = copy.deepcopy(snap["net"])
    bot.beliefs.mins = copy.deepcopy(snap["mins"])
    for p in others:
        bot.beliefs.quotes[p] = dict(quotes[others.index(p)])
    bot.beliefs.top_bid = list(snap["top_bid"])
    bot.beliefs.low_offer = list(snap["low_offer"])
    bot.beliefs.top_by = {p: list(snap["top_by"][str(p)]) for p in others}
    bot.beliefs.low_by = {p: list(snap["low_by"][str(p)]) for p in others}
    bot.cost = list(snap["cost"])
    bot.bought = list(snap["bought"])
    bot.p_sticky = None if snap["p_sticky"] is None else list(snap["p_sticky"])
    bot.p_avg = None if snap["p_avg"] is None else list(snap["p_avg"])
    bot._p_tick = snap["p_tick"]
    bot._pending = {s: [QuoteEvent(*ev), seen, last] for s, ev, seen, last in snap["pending"]}
    x = snap["resale"]
    if x is not None and bot.resale is not None:
        r = bot.resale
        r.open = [list(e) for e in x["open"]]
        r.hits, r.misses, r.prices = x["hits"], x["misses"], list(x["prices"])
        r.inventory = {s: [list(it) for it in x["inventory"][s]] for s in range(NUM_SUITS)}
        r.own_hits, r.own_misses, r.realized = x["own_hits"], x["own_misses"], x["realized"]
    bot._resale_bids = list(snap["resale_bids"])
    if snap.get("learner") is not None and bot.learner is not None:
        bot.learner.load(snap["learner"])
        bot.resale = bot.learner
    bot.beliefs._mins_state += 1
    bot.beliefs._state += 1
    m = RecordingMarket(me, snap["tick"], snap["book"], snap["hand"], snap["cash"])
    bot.act(m)
    out["ops"] = [[None if x is None else x for x in op] for op in m.ops]
    if snap.get("learner") is not None and bot.learner is not None:
        # the model after the turn (expiring opportunities update it): the JS port must agree
        st = bot.learner.state()
        out["learner_after"] = {"mu": st["mu"], "S": st["S"], "cal": st["cal"], "counts": st["counts"]}
    return out


def main() -> None:
    # Optional SharkParams overrides, e.g. `python tests/make_js_vectors.py sticky_halflife=60`,
    # so non-default code paths can be checked too; the harness builds its bots with the same params.
    params = {}
    for arg in sys.argv[1:]:
        k, _, v = arg.partition("=")
        params[k] = _parse_value(v)
    spec = "shark" + (":" + ",".join(f"{k}={v}" for k, v in params.items()) if params else "")
    cases = []
    lineups = [
        [spec, "oracle", "counter", "noise"],
        [spec, "oracle", "oracle", "oracle"],
        [spec, "shark", "hand", "noise"],
        [spec, "hand", "counter", "noise", "oracle"],  # five players
        [spec, "counter"],  # two players: 20 cards each
        [spec, "oracle", "counter"],  # three players: 13 each, one card dealt to nobody
        [spec, "fickle", "fickle", "fickle"],  # dead suits churn: exercises the cheap-resale code
    ]
    for gi in range(21):
        lineup = lineups[gi % len(lineups)]
        ticks = [0, 15, 40, 90, 160, 230]
        if "fickle" in lineup:
            ticks = list(range(0, 240, 5))  # resale trades are rare events: look often
        snap = Snapshotter(0, ticks)
        Game([make_bot(s) for s in lineup], rules=Rules(n_players=len(lineup)), seed=1000 + gi, observers=[snap]).run()
        for s in snap.snaps:
            s["expected"] = expected(s, params)
            cases.append(s)
    if params.get("resale_cheap", 0) > 0:
        # turns in which the shark bought or sold resale stock, against tables where that happens
        REGISTRY["probe"] = ResaleProbe
        probe = "probe" + spec[len("shark"):]
        n_probe = 0
        for gi in range(40):
            if n_probe >= 40:
                break
            lineup = [probe, "fickle", "fickle", "fickle"] if gi % 2 == 0 else [probe, "fickle", "oracle", "counter"]
            bots = [make_bot(s) for s in lineup]
            Game(bots, rules=Rules(n_players=len(lineup)), seed=5000 + gi).run()
            for s in bots[0].snaps[:3]:
                s["expected"] = expected(s, params)
                cases.append(s)
                n_probe += 1
        print(f"{n_probe} snapshots of turns that traded resale stock")
    learner_rounds = round_start_vectors(cases, params)
    reading = reading_vectors()
    out = Path(__file__).with_name("js_vectors.json")
    out.write_text(json.dumps({"params": params, "cases": cases, "learner_rounds": learner_rounds, "reading": reading}))
    n_ops = sum(len(c["expected"]["ops"]) for c in cases)
    print(
        f"wrote {len(cases)} snapshots ({n_ops} bot orders), {len(learner_rounds)} learner round starts and"
        f" {len(reading)} bid-reading histories (params {params or 'default'}) to {out}"
    )


def reading_vectors(n: int = 20, rounds: int = 12) -> list:
    """Random histories of rounds for the ReadingLearner (tables, revealed goals, early top bids,
    consensus suits), with its log-odds after every step: the JS port must agree exactly."""
    import random

    rng = random.Random(7)
    out = []
    for _ in range(n):
        R = ReadingLearner()
        steps, after = [], []
        for _ in range(rounds):
            table = rng.choice([["a", "b", "c"], ["d", "e", "f"]])
            goal = rng.randrange(4)
            early = rng.choice([None, goal, goal ^ 1, rng.randrange(4)])
            cons = rng.choice([None, goal, rng.randrange(4)])
            R.start_round(table)
            R.end_round(goal, early, cons)
            steps.append([table, goal, early, cons])
            after.append(R.state())
        out.append({"steps": steps, "after": after})
    return out


def round_start_vectors(cases: list, params: dict, limit: int = 12) -> list:
    """The learned-resale model at a round start, which the per-turn snapshots never reach: at
    the same table (the per-seller offsets stay), at a new one (they go), and carried from
    another page (memory -> seed) to a new table.  From learner states with seller offsets."""
    P = SharkBot(**params).params

    def fresh():
        return ResaleLearner(
            max_price=P.resale_learn_max, margin=P.resale_margin, window=P.resale_window,
            min_left=P.resale_min_left, stop_loss=P.resale_stop, robust=P.resale_robust,
        )

    def pick(L):
        st = L.state()
        return {k: st[k] for k in ("mu", "S", "sellers", "cal", "counts", "table", "n_obs", "prices")}

    out = []
    for c in cases:
        st = c.get("learner")
        if st is None or not st["sellers"] or st["table"] is None or len(out) >= limit:
            continue
        me, same = c["me"], list(st["table"])
        other = [name + "-2" for name in same]
        exp = {}
        for key, table in (("same", same), ("other", other)):
            L = fresh()
            L.load(st)
            L.start_round(me, 240, table)
            exp[key] = pick(L)
        A = fresh()
        A.load(st)
        B = fresh()
        B.start_round(me, 240, other)
        B.seed(*A.memory())
        exp["seeded"] = pick(B)
        out.append({"state": st, "me": me, "same": same, "other": other, "expected": exp})
    return out


if __name__ == "__main__":
    main()
