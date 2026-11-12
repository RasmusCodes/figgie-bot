"""Baseline opponents and shared quoting helpers."""
from __future__ import annotations

import math
import random
from typing import Optional

from .engine import NUM_SUITS, Bot, GameInfo, Market, QuoteEvent, Trade
from .model import Beliefs


def work_bid(m: Market, suit: int, limit: int, opening: Optional[int] = None, step: Optional[int] = None) -> None:
    """Try to hold the best bid in ``suit`` without ever paying more than ``limit``.

    Pennies a competitor's bid; on an empty book opens at ``opening`` (default:
    the limit); if we already hold the best bid, steps it up by ``step`` per
    turn toward the limit (``None``: leave it).  Never crosses the offer:
    taking liquidity is a separate decision.
    """
    me = m.me
    cur = m.best_bid(suit)
    off = m.best_offer(suit)
    cap = limit if off is None else min(limit, off.price - 1)
    if cur is not None and cur.player == me:
        if cur.price > cap:
            m.cancel_bid(suit)
            cur = None
        else:
            if step and cur.price < cap:
                m.bid(suit, min(cap, cur.price + step))
            return
    if cap < 1:
        return
    if cur is None:
        target = cap if opening is None else max(1, min(cap, opening))
    else:
        target = min(cap, cur.price + 1)
    if cur is None or target > cur.price:
        m.bid(suit, target)


def work_offer(m: Market, suit: int, limit: int, opening: Optional[int] = None, step: Optional[int] = None) -> None:
    """Mirror image of :func:`work_bid` for the offer side."""
    me = m.me
    if m.hand[suit] <= 0:
        return
    cur = m.best_offer(suit)
    bid = m.best_bid(suit)
    floor_ = max(1, limit) if bid is None else max(1, limit, bid.price + 1)
    if cur is not None and cur.player == me:
        if cur.price < floor_:
            m.cancel_offer(suit)
            cur = None
        else:
            if step and cur.price > floor_:
                m.offer(suit, max(floor_, cur.price - step))
            return
    if cur is None:
        target = floor_ if opening is None else max(floor_, opening)
    else:
        target = max(floor_, cur.price - 1)
    if cur is None or target < cur.price:
        m.offer(suit, target)


class NoiseBot(Bot):
    """Uninformed liquidity: random quotes, now and then crosses the spread."""

    name = "noise"

    def __init__(self, activity: float = 0.25, max_price: int = 15, cross_prob: float = 0.1) -> None:
        self.activity = activity
        self.max_price = max_price
        self.cross_prob = cross_prob

    def on_start(self, info: GameInfo) -> None:
        self.rng = random.Random(info.seed)

    def act(self, m: Market) -> None:
        rng = self.rng
        if rng.random() > self.activity:
            return
        s = rng.randrange(NUM_SUITS)
        r = rng.random()
        if r < self.cross_prob:
            if rng.random() < 0.5:
                off = m.best_offer(s)
                if off is not None and off.price <= rng.randint(1, self.max_price):
                    m.buy(s, off.price)
            else:
                bid = m.best_bid(s)
                if bid is not None and bid.price >= rng.randint(1, self.max_price):
                    m.sell(s, bid.price)
        elif r < 0.5 + self.cross_prob / 2:
            m.bid(s, rng.randint(1, max(1, self.max_price // 2)))
        else:
            m.offer(s, rng.randint(2, self.max_price))


class HandBot(Bot):
    """A sensible-but-naive human: reads only its own hand.

    Values each suit at ``P(goal) * card_value`` (card_value ~ $10 payout plus
    a rough share of the bonus) and makes a market ``spread`` wide around it,
    taking anything mispriced by at least ``edge``.  Ignores the tape and its
    own position in the bonus race.
    """

    name = "hand"
    use_tape = False

    def __init__(self, card_value: Optional[float] = None, spread: Optional[int] = None, edge: int = 1) -> None:
        self._card_value = card_value
        self._spread = spread
        self.edge = edge

    def on_start(self, info: GameInfo) -> None:
        self.rng = random.Random(info.seed)
        self.card_value = self._card_value if self._card_value is not None else self.rng.uniform(15.0, 25.0)
        self.spread = self._spread if self._spread is not None else self.rng.choice((2, 3, 4))
        self.me = info.player
        self.beliefs = Beliefs(info.player, info.rules.n_players, info.hand, info.rules.hand_size)
        self._p_goal = self.beliefs.p_goal()

    def on_trade(self, t: Trade) -> None:
        if self.use_tape:
            self.beliefs.observe_trade(t)

    def on_quote(self, ev: QuoteEvent) -> None:
        if self.use_tape and not ev.is_bid:
            self.beliefs.observe_offer(ev.player, ev.suit)

    def current_p_goal(self):
        return self.beliefs.p_goal() if self.use_tape else self._p_goal

    def act(self, m: Market) -> None:
        p_goal = self.current_p_goal()
        vals = [q * self.card_value for q in p_goal]
        hand = m.hand
        suits = list(range(NUM_SUITS))
        self.rng.shuffle(suits)
        for s in suits:
            off = m.best_offer(s)
            if off is not None and off.player != self.me and off.price <= vals[s] - self.edge:
                if m.buy(s, off.price):
                    return
            bid = m.best_bid(s)
            if bid is not None and bid.player != self.me and hand[s] > 0 and bid.price >= vals[s] + self.edge:
                if m.sell(s, bid.price):
                    return
        half = self.spread / 2
        for s in suits:
            work_bid(m, s, min(m.cash, math.floor(vals[s] - half)))
            work_offer(m, s, math.ceil(vals[s] + half))


class CounterBot(HandBot):
    """HandBot that also counts cards: updates P(goal) from what the tape
    proves about other hands (same exact inference the shark uses), but still
    values cards naively."""

    name = "counter"
    use_tape = True


class OracleBot(CounterBot):
    """Simulator-only stand-in for strong opponents such as figgie.com's bots.

    With probability ``accuracy`` it is told the goal suit at the deal and
    trades like a CounterBot that is ``confidence`` sure of it: it bids the
    goal suit into the teens and dumps the other suits for a few dollars,
    which is the pattern recorded from figgie.com's own bots.  Otherwise it
    is a plain CounterBot.
    """

    name = "oracle"
    oracle = True  # the engine tells it the deck (simulator only)

    def __init__(self, accuracy: float = 0.6, confidence: float = 0.85, **kw) -> None:
        super().__init__(**kw)
        self.accuracy = accuracy
        self.confidence = confidence
        self._known: Optional[int] = None

    def on_oracle(self, config) -> None:
        self._known = config.goal if self.rng.random() < self.accuracy else None

    def current_p_goal(self):
        base = self.beliefs.p_goal()
        if self._known is None:
            return base
        c = self.confidence
        return [c * (1.0 if s == self._known else 0.0) + (1.0 - c) * base[s] for s in range(NUM_SUITS)]


class FickleBot(OracleBot):
    """An OracleBot whose value for each suit drifts: a mean-reverting random walk
    with standard deviation ``mood_sd`` dollars and time constant ``mood_tau``
    ticks is added to every suit's value.

    It stands in for a habit of figgie.com's bots: the same dead suit trades for
    $1-2 one moment and draws $4-7 bids the next.  A table of these lets the
    simulator test the shark's cheap-resale exploit (see figgie.patterns).
    """

    name = "fickle"

    def __init__(self, mood_sd: float = 2.5, mood_tau: float = 30.0, **kw) -> None:
        super().__init__(**kw)
        self.mood_sd = mood_sd
        self.mood_tau = mood_tau

    def on_start(self, info: GameInfo) -> None:
        super().on_start(info)
        self.mood = [self.rng.gauss(0.0, self.mood_sd) for _ in range(NUM_SUITS)]
        self._mood_tick = 0

    def act(self, m: Market) -> None:
        if m.tick != self._mood_tick:
            a = math.exp(-1.0 / self.mood_tau)
            noise = self.mood_sd * math.sqrt(1.0 - a * a)
            self.mood = [x * a + self.rng.gauss(0.0, noise) for x in self.mood]
            self._mood_tick = m.tick
        super().act(m)

    def current_p_goal(self):
        # HandBot values a suit at P(goal) * card_value; shift that by the mood
        base = super().current_p_goal()
        return [max(0.0, p + x / self.card_value) for p, x in zip(base, self.mood)]
