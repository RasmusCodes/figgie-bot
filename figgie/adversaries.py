"""Simulator-only adversaries: opponents built to exploit the shark's habits.

They see the deck through the simulator's oracle hook, so they exist only for
stress tests (``python -m figgie.arena ... --tables adversarial``).  None of
this can leak into the shark: it never receives the oracle hook.

What each one attacks:

* ``spoofer``  flashes and cancels big bids on a dead suit (fake smart money).
* ``bait``     a ring that fakes the cheap-resale pattern with wash trades.
* ``bait2``    the same ring aimed at the learned resale: $3 dumps, $6 rebids, and
               the first resales of each round allowed to work, to earn trust.
* ``pump``     a ring that wash-trades a dead suit at a high price among itself, so
               the tape shows every member paying up for it (fake smart money and
               fake consensus that real trades back), and sells it to whoever bites.
* ``sniper``   never quotes; takes other players' quotes only once they have stopped
               moving (a quote walking toward its limit is predictable).
* ``penny``    front-runs: outbids every bid on the goal by $1 and undercuts every
               offer on a dead suit by $1, so a patient quoter never fills.
* ``quiet``    withholds information: buys the goal only by lifting offers, never
               shows a bid, never offers the goal.
* ``holdout``  prices the bonus fight: asks a fortune for goal cards once someone is
               accumulating them, and bids $1 for dead cards near the bell.
* ``adapt``    learns, over a session at one table, the prices outsiders pay for dead
               cards and sell goal cards at, and quotes just inside them.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .bots import OracleBot, work_bid, work_offer
from .engine import NUM_SUITS, Market, Trade


class SpooferBot(OracleBot):
    """Knows the goal and tries to fool anyone who reads bids.

    Every ``every`` ticks it flashes a bid of ``spoof_price`` on a suit it
    knows is dead (the decoy) and cancels it on its next turn.  The rest of the
    time it trades like an oracle that is sure of the goal, so it sells the
    decoy into anyone who believed the spoof and bid it up.  The spoof is not
    free: anyone who sells into the flashed bid before it is cancelled sticks
    the spoofer with a dead card at a high price.  ``every=0`` never spoofs,
    which gives the same bot without the trick for comparison.
    """

    name = "spoofer"

    def __init__(self, spoof_price: int = 20, every: int = 4, min_price: int = 12, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 0.95)
        super().__init__(**kw)
        self.spoof_price = spoof_price
        self.every = every
        self.min_price = min_price
        self.decoy: Optional[int] = None
        self._spoof_up = False

    def on_oracle(self, config) -> None:
        super().on_oracle(config)
        self.decoy = self.rng.choice([s for s in range(NUM_SUITS) if s != config.goal])

    def act(self, m: Market) -> None:
        if self._spoof_up:
            cur = m.best_bid(self.decoy)
            if cur is not None and cur.player == self.me:
                m.cancel_bid(self.decoy)
            self._spoof_up = False
        if self.every > 0 and self.decoy is not None and m.tick % self.every == 0:
            cur = m.best_bid(self.decoy)
            price = self.spoof_price if cur is None else max(self.spoof_price, cur.price + 1)
            off = m.best_offer(self.decoy)
            if off is not None and off.price <= price:
                price = off.price - 1  # never cross: the point is to be seen, not to buy
            if price >= self.min_price and price <= m.cash and (cur is None or price > cur.price):
                if m.bid(self.decoy, price):
                    self._spoof_up = True
                    return
        super().act(m)


class BaitBot(OracleBot):
    """One of a ring of colluders that know the goal and bait the shark's
    cheap-resale habit (see figgie.patterns).

    Every seat whose bot name starts with "bait" is in the ring.  It fakes the
    pattern with wash trades: one member offers a dead card for ``dump_price``,
    another buys it and then bids ``bait_price`` for the suit, and a third sells
    into that bid.  The ring loses nothing to itself, and the shark sees cheap
    cards bid straight back up.  It washes only suits in which no outsider has
    bought a card, and never bids for a suit an outsider holds, so the cheap
    cards an outsider buys never resell.  Dead cards are offered at
    ``dump_price`` to anyone and sold into any outsider's bid; the goal suit
    they buy and bid up to ``goal_value``.  ``bait_price=0`` turns the washing
    off, leaving plain dumpers.  ``honey`` > 0 lets the first that many cheap
    buys by outsiders in a round resell (a ring member bids for the suit anyway),
    so a bot that judges the pattern by its own resales sees it work at first.
    """

    name = "bait"

    def __init__(self, dump_price: int = 1, bait_price: int = 5, goal_value: int = 15, honey: int = 0, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 1.0)
        super().__init__(**kw)
        self.dump_price = dump_price
        self.bait_price = bait_price
        self.goal_value = goal_value
        self.honey = honey

    def on_start(self, info) -> None:
        super().on_start(info)
        # the ring: seats whose spec starts with this class's name (make_bot renames a bot to its spec)
        self.ring = {p for p, n in enumerate(info.names) if str(n).startswith(type(self).name)}
        self.outside_long = [0] * NUM_SUITS  # cards of each suit outsiders have bought, net
        self.outside_buys = 0  # cheap cards outsiders bought from the ring this round
        self._wash_bid: Optional[int] = None  # suit we bought into a wash and now bid for

    def on_trade(self, t: Trade) -> None:
        super().on_trade(t)
        if t.buyer not in self.ring:
            self.outside_long[t.suit] += 1
            if t.seller in self.ring and t.price <= self.dump_price:
                self.outside_buys += 1
        if t.seller not in self.ring:
            self.outside_long[t.suit] -= 1

    def _trusting(self) -> bool:
        """Still letting outsiders' resales work (the honeymoon)."""
        return self.outside_buys <= self.honey and self.honey > 0

    def act(self, m: Market) -> None:
        goal = self._known
        if goal is None:
            return
        ring, me, hand = self.ring, self.me, m.hand
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= self.goal_value - 2:
            if m.buy(goal, max_price=off.price):
                return
        work_bid(m, goal, min(m.cash, self.goal_value - 3), opening=5, step=1)
        for s in range(NUM_SUITS):
            if s == goal:
                continue
            bid, off = m.best_bid(s), m.best_offer(s)
            if hand[s] > 0 and bid is not None and bid.player != me and (bid.player not in ring or bid.price >= 3):
                m.sell(s, min_price=bid.price)  # an outsider's bid, or the second leg of a wash
                return
            if self._trusting() and self.outside_long[s] > 0 and self.bait_price > 0:
                # honeymoon: an outsider holds a cheap card of this suit; let it resell
                if bid is None or (bid.player != me and bid.price < self.bait_price):
                    m.bid(s, self.bait_price)
                continue
            wash = self.bait_price > 0 and self.outside_long[s] <= 0
            if not wash:
                if bid is not None and bid.player == me:
                    m.cancel_bid(s)  # an outsider holds this suit: no resale for it here
                self._wash_bid = None if self._wash_bid == s else self._wash_bid
            elif self._wash_bid == s:
                if bid is None or bid.price < self.bait_price:
                    m.bid(s, self.bait_price)
                self._wash_bid = None
            elif self._wash_bid is None and off is not None and off.player in ring and off.player != me and off.price <= self.dump_price:
                if m.buy(s, max_price=off.price):
                    self._wash_bid = s  # the first leg: bid it back up on our next turn
                    return
            if hand[s] > 0 and (off is None or off.price > self.dump_price):
                m.offer(s, self.dump_price)


class Bait2Bot(BaitBot):
    """The bait ring tuned against the learned resale (v12): it dumps at $3 and rebids $6,
    inside the learner's $3-5 range, and lets the first two cheap buys of a round resell."""

    name = "bait2"

    def __init__(self, dump_price: int = 3, bait_price: int = 6, honey: int = 2, **kw) -> None:
        super().__init__(dump_price=dump_price, bait_price=bait_price, honey=honey, **kw)


class PumpBot(OracleBot):
    """One of a ring that fakes smart money with real trades.

    Every seat whose name starts with "pump" is in the ring, and all of them know the goal.
    They agree, without talking, on a decoy: the suit of the other colour from the goal with
    the lower index.  A member holding decoy cards keeps an offer of ``wash_price`` on it,
    and the member who has bought the fewest decoys from the ring lifts it, so after a few
    rounds of washing every member has paid ``wash_price`` for the decoy on the tape: a top
    bid, and an opponents' consensus, that real trades back.  The ring loses nothing to
    itself.  Whoever believes it pays: any outsider who lifts the wash offer pays the pump
    price, and any outsider's bid on the decoy gets sold into.  Meanwhile the ring buys the
    real goal quietly (lifting offers up to ``goal_value``, bidding no more than
    ``goal_bid``) and dumps the other dead suit.
    """

    name = "pump"

    def __init__(
        self, wash_price: int = 18, goal_value: int = 14, goal_bid: int = 4, dump_price: int = 3, wash_every: int = 6, **kw
    ) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 1.0)
        super().__init__(**kw)
        self.wash_price = wash_price
        self.goal_value = goal_value
        self.goal_bid = goal_bid
        self.dump_price = dump_price
        self.wash_every = wash_every
        self.decoy: Optional[int] = None

    def on_start(self, info) -> None:
        super().on_start(info)
        self.ring = {p for p, n in enumerate(info.names) if str(n).startswith(type(self).name)}
        self.wash_buys: Dict[int, int] = {p: 0 for p in self.ring}

    def on_oracle(self, config) -> None:
        super().on_oracle(config)
        if self._known is not None:
            g = self._known
            self.decoy = min(s for s in range(NUM_SUITS) if s not in (g, (g ^ 1)))  # other colour

    def on_trade(self, t: Trade) -> None:
        super().on_trade(t)
        if t.suit == self.decoy and t.buyer in self.ring and t.seller in self.ring:
            self.wash_buys[t.buyer] += 1

    def act(self, m: Market) -> None:
        goal, decoy = self._known, self.decoy
        if goal is None or decoy is None:
            return
        me, hand, ring = self.me, m.hand, self.ring
        # sell the decoy to anyone outside the ring who bids for it
        bid = m.best_bid(decoy)
        if bid is not None and bid.player not in ring and hand[decoy] > 0 and bid.price >= self.dump_price:
            if m.sell(decoy, min_price=bid.price):
                return
        # wash: the ring member with the fewest wash buys lifts a member's decoy offer
        off = m.best_offer(decoy)
        if off is not None and off.player in ring and off.player != me and off.price <= m.cash and m.tick % self.wash_every == 0:
            if self.wash_buys[me] <= min(self.wash_buys.values()):
                if m.buy(decoy, max_price=off.price):
                    return
        if hand[decoy] > 0 and (off is None or (off.player != me and off.price > self.wash_price)):
            m.offer(decoy, self.wash_price)
        # the goal: accumulate without advertising it
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= self.goal_value:
            if m.buy(goal, max_price=off.price):
                return
        work_bid(m, goal, min(m.cash, self.goal_bid))
        # the other dead suit: dump it
        for s in range(NUM_SUITS):
            if s in (goal, decoy) or hand[s] <= 0:
                continue
            b = m.best_bid(s)
            if b is not None and b.player != me and b.price >= 2:
                if m.sell(s, min_price=b.price):
                    return
            work_offer(m, s, self.dump_price)


class SniperBot(OracleBot):
    """An informed taker that never quotes.  It lifts offers on the goal up to
    ``goal_value`` and sells dead cards into bids of ``min_dead`` or more, but only once
    the quote has stopped moving for ``patience`` ticks (a quote walking toward its limit
    is still getting better), unless the price is already too good to wait for."""

    name = "sniper"

    def __init__(self, goal_value: int = 14, min_dead: int = 2, patience: int = 4, grab_goal: int = 7, grab_dead: int = 8, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 0.95)
        super().__init__(**kw)
        self.goal_value = goal_value
        self.min_dead = min_dead
        self.patience = patience
        self.grab_goal = grab_goal
        self.grab_dead = grab_dead

    def on_start(self, info) -> None:
        super().on_start(info)
        self.seen: Dict[tuple, tuple] = {}  # (suit, is_bid) -> (price, player, tick first seen at it)

    def _stale(self, m: Market, s: int, is_bid: bool) -> bool:
        q = m.best_bid(s) if is_bid else m.best_offer(s)
        key = (s, is_bid)
        prev = self.seen.get(key)
        if q is None:
            self.seen.pop(key, None)
            return False
        if prev is None or prev[0] != q.price or prev[1] != q.player:
            self.seen[key] = (q.price, q.player, m.tick)
            return False
        return m.tick - prev[2] >= self.patience

    def act(self, m: Market) -> None:
        goal = self._known
        if goal is None:
            return super().act(m)
        me, hand = self.me, m.hand
        stale = {(s, b): self._stale(m, s, b) for s in range(NUM_SUITS) for b in (True, False)}
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= self.goal_value:
            if off.price <= self.grab_goal or stale[(goal, False)]:
                if m.buy(goal, max_price=off.price):
                    return
        best = None
        for s in range(NUM_SUITS):
            if s == goal or hand[s] <= 0:
                continue
            bid = m.best_bid(s)
            if bid is not None and bid.player != me and bid.price >= self.min_dead:
                if bid.price >= self.grab_dead or stale[(s, True)]:
                    if best is None or bid.price > best[1]:
                        best = (s, bid.price)
        if best is not None:
            m.sell(best[0], min_price=best[1])


class PennyBot(OracleBot):
    """Front-runs other players' quotes.  It knows the goal: any bid on the goal by someone
    else it outbids by $1 (up to ``goal_value``), and any offer on a dead suit it holds it
    undercuts by $1 (down to $1), so a quoter who walks its price patiently is always one
    dollar behind.  It also takes goal offers up to ``goal_value`` - 2 and sells dead cards
    into bids of $2 or more."""

    name = "penny"

    def __init__(self, goal_value: int = 15, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 0.95)
        super().__init__(**kw)
        self.goal_value = goal_value

    def act(self, m: Market) -> None:
        goal = self._known
        if goal is None:
            return super().act(m)
        me, hand = self.me, m.hand
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= self.goal_value - 2:
            if m.buy(goal, max_price=off.price):
                return
        bid = m.best_bid(goal)
        if bid is None:
            m.bid(goal, min(m.cash, 3))
        elif bid.player != me and bid.price + 1 <= min(m.cash, self.goal_value - 1):
            if off is None or bid.price + 1 < off.price:
                m.bid(goal, bid.price + 1)
        for s in range(NUM_SUITS):
            if s == goal or hand[s] <= 0:
                continue
            b = m.best_bid(s)
            if b is not None and b.player != me and b.price >= 2:
                if m.sell(s, min_price=b.price):
                    return
            o = m.best_offer(s)
            if o is None:
                m.offer(s, 6)
            elif o.player != me and o.price > 1:
                m.offer(s, o.price - 1)


class QuietBot(OracleBot):
    """Withholds information.  It knows the goal but never shows a bid on any suit and
    never offers the goal: it buys goal cards only by lifting offers up to ``goal_value``,
    sells dead cards into bids of ``min_dead`` or more, and offers them at ``dead_ask``."""

    name = "quiet"

    def __init__(self, goal_value: int = 13, min_dead: int = 2, dead_ask: int = 4, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 0.95)
        super().__init__(**kw)
        self.goal_value = goal_value
        self.min_dead = min_dead
        self.dead_ask = dead_ask

    def act(self, m: Market) -> None:
        goal = self._known
        if goal is None:
            return super().act(m)
        me, hand = self.me, m.hand
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= self.goal_value:
            if m.buy(goal, max_price=off.price):
                return
        for s in range(NUM_SUITS):
            if s == goal or hand[s] <= 0:
                continue
            b = m.best_bid(s)
            if b is not None and b.player != me and b.price >= self.min_dead:
                if m.sell(s, min_price=b.price):
                    return
            work_offer(m, s, self.dead_ask, opening=self.dead_ask + 3, step=1)


class HoldoutBot(OracleBot):
    """Prices the fight for the bonus.  It knows the goal and counts, from the tape, how
    many goal cards each other player has bought.  It sells goal cards only at
    ``ask_base`` plus ``ask_step`` for each goal card the most aggressive accumulator has
    bought (it holds out against whoever needs them most), keeps buying the goal up to
    ``goal_value``, and in the last ``late`` ticks bids $1 for every dead suit, to catch
    whoever has to dump."""

    name = "holdout"

    def __init__(self, ask_base: int = 18, ask_step: int = 3, goal_value: int = 14, late: int = 45, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 0.95)
        super().__init__(**kw)
        self.ask_base = ask_base
        self.ask_step = ask_step
        self.goal_value = goal_value
        self.late = late

    def on_start(self, info) -> None:
        super().on_start(info)
        self.goal_bought: Dict[int, int] = {}

    def on_trade(self, t: Trade) -> None:
        super().on_trade(t)
        if self._known is not None and t.suit == self._known:
            self.goal_bought[t.buyer] = self.goal_bought.get(t.buyer, 0) + 1
            self.goal_bought[t.seller] = self.goal_bought.get(t.seller, 0) - 1

    def act(self, m: Market) -> None:
        goal = self._known
        if goal is None:
            return super().act(m)
        me, hand = self.me, m.hand
        rival = max([n for p, n in self.goal_bought.items() if p != me] or [0])
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= self.goal_value:
            if m.buy(goal, max_price=off.price):
                return
        work_bid(m, goal, min(m.cash, self.goal_value - 2), opening=4, step=1)
        if hand[goal] > 0:
            ask = self.ask_base + self.ask_step * max(0, rival)
            bid = m.best_bid(goal)
            if bid is not None and bid.player != me and bid.price >= ask:
                if m.sell(goal, min_price=bid.price):
                    return
            work_offer(m, goal, ask)
        late = m.ticks_left <= self.late
        for s in range(NUM_SUITS):
            if s == goal:
                continue
            b = m.best_bid(s)
            if hand[s] > 0 and b is not None and b.player != me and b.price >= 3:
                if m.sell(s, min_price=b.price):
                    return
            if late:
                work_bid(m, s, min(m.cash, 1))
            elif hand[s] > 0:
                work_offer(m, s, 5)


class AdaptBot(OracleBot):
    """Learns, over a session at one table, what outsiders pay for dead cards and what they
    sell goal cards for, and quotes just inside it.  The bot object persists from round to
    round (tools/sessions.py, figgie.arena), so the record grows.  It offers dead cards at
    the ``hi`` quantile of the prices outsiders paid for dead cards, and bids for the goal
    at the ``lo`` quantile of the prices outsiders sold goal cards at plus $1, never past
    ``goal_value``; until it has seen ``min_obs`` trades of a kind it plays like an oracle."""

    name = "adapt"

    def __init__(self, hi: float = 0.75, lo: float = 0.25, goal_value: int = 15, min_obs: int = 5, **kw) -> None:
        kw.setdefault("accuracy", 1.0)
        kw.setdefault("confidence", 0.95)
        super().__init__(**kw)
        self.hi = hi
        self.lo = lo
        self.goal_value = goal_value
        self.min_obs = min_obs
        self.dead_paid: List[int] = []  # carried across rounds
        self.goal_sold: List[int] = []

    def on_start(self, info) -> None:
        super().on_start(info)
        self.ring = {p for p, n in enumerate(info.names) if str(n).startswith(type(self).name)}

    def on_trade(self, t: Trade) -> None:
        super().on_trade(t)
        g = self._known
        if g is None:
            return
        if t.suit != g and t.buyer not in self.ring:
            self.dead_paid.append(t.price)
            del self.dead_paid[:-200]
        if t.suit == g and t.seller not in self.ring:
            self.goal_sold.append(t.price)
            del self.goal_sold[:-200]

    @staticmethod
    def _q(xs: List[int], q: float) -> int:
        ys = sorted(xs)
        return ys[min(len(ys) - 1, int(q * len(ys)))]

    def act(self, m: Market) -> None:
        goal = self._known
        if goal is None or (len(self.dead_paid) < self.min_obs and len(self.goal_sold) < self.min_obs):
            return super().act(m)
        me, hand = self.me, m.hand
        limit = self.goal_value
        if len(self.goal_sold) >= self.min_obs:
            limit = min(limit, self._q(self.goal_sold, self.lo) + 1)
        off = m.best_offer(goal)
        if off is not None and off.player != me and off.price <= limit:
            if m.buy(goal, max_price=off.price):
                return
        work_bid(m, goal, min(m.cash, limit), opening=max(1, limit - 4), step=1)
        ask = self._q(self.dead_paid, self.hi) if len(self.dead_paid) >= self.min_obs else 4
        for s in range(NUM_SUITS):
            if s == goal or hand[s] <= 0:
                continue
            b = m.best_bid(s)
            if b is not None and b.player != me and b.price >= max(2, ask - 1):
                if m.sell(s, min_price=b.price):
                    return
            work_offer(m, s, max(2, ask), opening=ask + 2, step=1)
