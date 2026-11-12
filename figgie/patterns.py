"""Patterns in the order book that the shark learns as it plays, and exploits.

:class:`ResaleTracker` watches for one that figgie.com's bots repeat in round
after round: a card dumped for a dollar or two, and soon after a bid of $4 or
more for the same suit from someone else (with at least 15 seconds to go, a
$4+ bid followed 96% of the cheap cards in the 10 rounds logged with v9, and
76% in the next 10, typically within 11-12 seconds).  Once
the pattern has shown up a few times, the shark buys cheap cards to sell into
those bids.  The tracker keeps score of the shark's own resales as well as of
the market, and its own outcomes count double: when cheap cards stop finding
buyers (or someone starts dumping cards on the shark because it buys them), the
estimated odds fall and the buying stops.  Past a set loss it stops for the
rest of the round, counting a resale card that has not sold within the window
as worthless.

:class:`ResaleLearner` (v12) learns the same kind of mistake without being told what it
looks like: for every offer another player shows, at any price up to a cap, the tape says
within seconds whether a third player would have bid enough more for it, and an online
logistic regression learns from that which offers resell, at whatever table it plays.

The JavaScript port in web/figgie-shark.user.js mirrors both classes line by line.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple


class ResaleTracker:
    def __init__(
        self,
        cheap: int = 2,
        margin: int = 2,
        window: int = 45,
        prior_hits: float = 1.0,
        prior_misses: float = 2.0,
        own_weight: float = 2.0,
        market_cap: float = 20.0,
        min_hits: int = 2,
        stop_loss: float = 6.0,
        max_net_misses: int = 2,
    ) -> None:
        self.cheap = cheap  # an offer or sale at or below this price is a cheap card
        self.margin = margin  # a resale bid must beat the cheap price by at least this ...
        self.window = window  # ... and come within this many ticks
        self.prior_hits = prior_hits  # Beta prior on "a cheap card gets bid back up"
        self.prior_misses = prior_misses
        self.own_weight = own_weight  # each of our own resale outcomes counts this many times ...
        self.market_cap = market_cap  # ... and what the market shows counts as at most this many
        self.min_hits = min_hits  # resales seen before we act on the pattern
        self.stop_loss = stop_loss  # stop for the round once our resale trades have lost this much ...
        self.max_net_misses = max_net_misses  # ... or this many more of them failed than worked
        self.open: List[list] = []  # [tick, suit, price, seller]: cheap cards awaiting a resale bid
        self.hits = 0.0
        self.misses = 0.0
        self.prices: List[int] = []  # the bids that resold a cheap card
        self.inventory: Dict[int, List[list]] = {s: [] for s in range(4)}  # our resale buys: [tick, paid, written off]
        self.own_hits = 0.0
        self.own_misses = 0.0
        self.realized = 0.0

    # ----- memory across rounds at the same table ------------------------------------
    def memory(self, keep: float = 0.5, n_prices: int = 12) -> Tuple[float, float, float, float, List[int]]:
        """What this round showed, discounted by ``keep``, to seed the next round's tracker."""
        return (
            keep * self.hits,
            keep * self.misses,
            keep * self.own_hits,
            keep * self.own_misses,
            list(self.prices[-n_prices:]),
        )

    def seed(self, hits: float, misses: float, own_hits: float, own_misses: float, prices: List[int]) -> None:
        self.hits += hits
        self.misses += misses
        self.own_hits += own_hits
        self.own_misses += own_misses
        self.prices.extend(prices)

    # ----- what the market shows ------------------------------------------------------
    def cheap_seen(self, tick: int, s: int, price: int, seller: int) -> None:
        if price <= self.cheap:
            self.open.append([tick, s, price, seller])

    def bid_seen(self, tick: int, s: int, price: int, bidder: int) -> None:
        """A real bid (one that stood, or a purchase) by ``bidder`` for suit ``s``."""
        keep = []
        for ev in self.open:
            t0, s0, p0, seller = ev
            if s0 == s and bidder != seller and price >= p0 + self.margin and tick - t0 <= self.window:
                self.hits += 1
                self.prices.append(price)
            else:
                keep.append(ev)
        self.open = keep

    def expire(self, tick: int) -> None:
        keep = []
        for ev in self.open:
            if tick - ev[0] > self.window:
                self.misses += 1
            else:
                keep.append(ev)
        self.open = keep
        for s in range(4):
            for item in self.inventory[s]:
                if not item[2] and tick - item[0] > self.window:
                    # bought to resell and still unsold: count it against the pattern, and
                    # against the stop-loss as if worthless, now
                    item[2] = True
                    self.own_misses += 1
                    self.realized -= item[1]

    # ----- our own resale trades -------------------------------------------------------
    def bought(self, tick: int, s: int, price: int) -> None:
        self.inventory[s].append([tick, price, False])

    def sold(self, s: int, price: int) -> None:
        if not self.inventory[s]:
            return
        _, paid, written_off = self.inventory[s].pop(0)
        if written_off:
            self.realized += price
            return
        self.realized += price - paid
        if price > paid:
            self.own_hits += 1
        else:
            self.own_misses += 1

    def held(self, s: int) -> int:
        return len(self.inventory[s])

    def held_total(self) -> int:
        return sum(len(self.inventory[s]) for s in range(4))

    # ----- the estimate ------------------------------------------------------------------
    def p_hit(self) -> float:
        """Estimated chance that a cheap card we buy resells: a Beta posterior in which the
        market's record counts for at most ``market_cap`` observations and each of our own
        resales for ``own_weight``, so a pattern that works for others but not for us fades."""
        seen = self.hits + self.misses
        k = min(1.0, self.market_cap / seen) if seen > 0 else 1.0
        w = self.own_weight
        hits = k * self.hits + w * self.own_hits + self.prior_hits
        return hits / (k * seen + w * (self.own_hits + self.own_misses) + self.prior_hits + self.prior_misses)

    def allowed(self, cap: int) -> int:
        """How many unsold resale cards we may hold: one, plus one per resale that has
        worked (up to ``cap``), so a pattern that fails us costs at most a card or two."""
        return min(cap, 1 + int(self.own_hits))

    def resale_price(self) -> Optional[int]:
        """A cautious resale price: the lower quartile of the resale bids seen."""
        if len(self.prices) < self.min_hits:
            return None
        ps = sorted(self.prices)
        return ps[len(ps) // 4]

    def active(self) -> bool:
        """Whether the pattern is established and has not failed us."""
        if self.realized <= -self.stop_loss or self.own_misses - self.own_hits >= self.max_net_misses:
            return False
        return self.hits + self.own_hits >= self.min_hits

    def value(self, price: int) -> Optional[float]:
        """Expected gain from buying a cheap card at ``price`` to resell it (an
        unsold card counts as worthless), or None while the pattern isn't established."""
        if price > self.cheap or not self.active():
            return None
        r = self.resale_price()
        if r is None or r < price + self.margin:
            return None
        p = self.p_hit()
        return p * (r - price) - (1.0 - p) * price

    def target(self, s: int, tick: int, patience: int) -> Optional[int]:
        """The least we take for our oldest resale card of suit ``s``: the cautious
        resale price, at least ``margin`` over what we paid, a dollar less once the
        card has waited ``patience`` ticks."""
        if not self.inventory[s]:
            return None
        t0, paid, _ = self.inventory[s][0]
        r = self.resale_price()
        target = max(paid + self.margin, r if r is not None else 0)
        if tick - t0 > patience:
            target = max(paid + 1, target - 1)
        return target


class ReadingLearner:
    """How far to trust two ways of reading the market, learned from the revealed goals.

    Two hypotheses about a table, each with a probability that the shark carries from round to
    round (and, live, from table to table at a discount):

    * **colour**: the early top bids sit on the goal's colour, not on the goal itself (at
      figgie.com the highest bid in the first minute was on the 12-card suit about as often as
      on the goal).  Against "suit": the early top bid is on the goal.  If the top bid one
      minute in is on the goal or its partner, the bell says which: on the partner has
      probability ``partner_if_colour`` under colour and ``partner_if_suit`` under suit.
    * **consensus**: the suit that every opponent has bid up is the goal, with probability
      ``right_if_reliable``, against ``right_if_not`` (a quarter: no information) when the
      opponents can fake it (a ring wash-trading a decoy at a high price makes a consensus).

    Each round is one Bayes update of each hypothesis's odds; the odds also drift back toward
    the prior by ``forget`` per round (in log-odds), further at a new table, and stay within
    ``clamp``, so a table that changes its ways can win the shark back.  The shark scales its
    colour reading and its consensus slope by these probabilities.
    """

    def __init__(
        self,
        prior_colour: float = 0.9,
        prior_consensus: float = 0.9,
        partner_if_colour: float = 0.5,
        partner_if_suit: float = 0.1,
        right_if_reliable: float = 0.9,
        right_if_not: float = 0.25,
        forget: float = 0.1,
        table_forget: float = 0.5,
        clamp: float = 0.01,
    ) -> None:
        self.prior = [prior_colour, prior_consensus]
        self.partner_if_colour = partner_if_colour
        self.partner_if_suit = partner_if_suit
        self.right_if_reliable = right_if_reliable
        self.right_if_not = right_if_not
        self.forget = forget
        self.table_forget = table_forget
        self.clamp = clamp
        self.logit = [self._lo(p) for p in self.prior]
        self.table: Optional[List[str]] = None
        self.rounds = 0
        self.seen = [0, 0]  # rounds that told us something about colour / consensus

    @staticmethod
    def _lo(p: float) -> float:
        return math.log(p / (1.0 - p))

    def p_colour(self) -> float:
        return _sigmoid(self.logit[0])

    def p_consensus(self) -> float:
        return _sigmoid(self.logit[1])

    def _drift(self, w: float) -> None:
        """Move each log-odds the fraction ``w`` of the way back to its prior's."""
        for i in range(2):
            p0 = self._lo(self.prior[i])
            self.logit[i] += w * (p0 - self.logit[i])

    def start_round(self, table: Optional[List[str]] = None) -> None:
        if table is not None and self.table is not None and list(table) != self.table:
            self._drift(self.table_forget)
        if table is not None:
            self.table = list(table)

    def end_round(self, goal: int, early_top: Optional[int], consensus: Optional[int]) -> None:
        """The bell: ``early_top`` is the suit with the highest bid a minute in (None: no bids,
        or a tie), ``consensus`` the suit every opponent had bid up most (None: none)."""
        self._drift(self.forget)
        lim = self._lo(1.0 - self.clamp)
        if early_top is not None and early_top in (goal, goal ^ 1):
            partner = early_top != goal
            a = self.partner_if_colour if partner else 1.0 - self.partner_if_colour
            b = self.partner_if_suit if partner else 1.0 - self.partner_if_suit
            self.logit[0] = max(-lim, min(lim, self.logit[0] + math.log(a / b)))
            self.seen[0] += 1
        if consensus is not None:
            right = consensus == goal
            a = self.right_if_reliable if right else 1.0 - self.right_if_reliable
            b = self.right_if_not if right else 1.0 - self.right_if_not
            self.logit[1] = max(-lim, min(lim, self.logit[1] + math.log(a / b)))
            self.seen[1] += 1
        self.rounds += 1

    def state(self) -> dict:
        return {"logit": list(self.logit), "table": None if self.table is None else list(self.table), "rounds": self.rounds, "seen": list(self.seen)}

    def load(self, st: dict) -> None:
        self.logit = list(st["logit"])
        self.table = None if st["table"] is None else list(st["table"])
        self.rounds = st["rounds"]
        self.seen = list(st["seen"])


def _sigmoid(z: float) -> float:
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


LEARNER_FEATURES = ("bias", "price", "cheap", "vs_trades", "demand", "depth", "p_goal", "time", "streak", "held")
_V12_D = 9  # models saved by v12 have no "held" weight: _upgrade inserts it


class ResaleLearner(ResaleTracker):
    """Which offers get bid back up, learned online from the tape (v12).

    Every offer another player shows at up to ``max_price`` (and every sale between two others
    at such a price) is an opportunity: had we bought it, would a third player (not the seller,
    not us) have bid or paid at least ``margin`` more for the suit within ``window`` ticks?  The
    tape answers within seconds, so the model learns from the first minute of the first round,
    from everyone's offers, not just from trades we make.

    The model is a Bayesian logistic regression on generic features (LEARNER_FEATURES: the
    price, whether it is $2 or less, the price against the last trades in the suit, the best bid
    from others in the last 30 ticks, how many others bid at least price + margin in the last
    60, our P(goal) for the suit, the time, and how often the seller has offered the suit in the
    last 20 ticks), plus a learned offset per seller.  Each observation updates it in O(d^2)
    (extended-Kalman / Laplace step).  Decisions use a lower confidence bound of the predicted
    chance, scaled by how our OWN resale buys have fared against what the model predicted for
    them (a calibration ratio, so a market pattern that does not work for us, or a ring that
    baits us, shuts it down), and the ResaleTracker's caps and kill switch stay in force.

    The learner is meant to outlive a round: :meth:`start_round` keeps the model, lets it move
    a little again (``forget``), and fades what our own resales showed (``cal_decay`` per round,
    ``table_decay`` more when the opponents change).  New opponents also wipe the per-seller
    offsets, which are keyed by seat.

    Two defences against opponents who poison the tape (v13, both on with ``robust``):

    * ``confirmed``: a bid answers a question only once it has proved real (it stood, or a trade
      cleared it after we saw it: the shark's smart_confirm rule, which feeds :meth:`bid_seen`),
      or as a trade.  A flashed and pulled bid no longer makes cheap cards look resellable.
    * ``held``: the "held" feature says whether we were long the suit.  The market's answers come
      mostly while we are flat, but a resale card is always bought into a long position, and a
      ring that bids a suit back up only while no outsider holds it (figgie.adversaries.BaitBot)
      shows its hand there.  Decisions are scored as of after the buy (held = 1), and our own
      resale buys are labelled with it, so the model learns from the first failures whether
      other players' bids depend on our position.  At a table where they don't, its weight
      stays near zero.
    """

    def __init__(
        self,
        max_price: int = 5,
        margin: int = 2,
        window: int = 45,
        min_left: int = 15,
        stop_loss: float = 6.0,
        max_net_misses: int = 2,
        prior_bias: float = -1.0,
        prior_var: float = 1.0,
        seller_var: float = 0.5,
        market_weight: float = 0.5,
        forget: float = 0.05,
        z_lcb: float = 1.0,
        cal_prior: float = 2.0,
        cal_decay: float = 0.7,
        table_decay: float = 0.5,
        robust: bool = False,
    ) -> None:
        super().__init__(cheap=max_price, margin=margin, window=window, stop_loss=stop_loss, max_net_misses=max_net_misses)
        self.robust = robust  # v13: labels from proven bids only, and the "held" feature
        self.prior_var = prior_var
        self.max_price = max_price
        self.min_left = min_left
        self.seller_var = seller_var
        self.market_weight = market_weight
        self.forget = forget
        self.z_lcb = z_lcb
        self.cal_prior = cal_prior
        self.cal_decay = cal_decay
        self.table_decay = table_decay
        d = len(LEARNER_FEATURES)
        self.mu: List[float] = [prior_bias] + [0.0] * (d - 1)
        self.S: List[List[float]] = [[prior_var if i == j else 0.0 for j in range(d)] for i in range(d)]
        self.sellers: Dict[int, int] = {}  # player -> index of their offset in mu / S
        self.cal_hits = 0.0  # our own resale buys that a third player bid back up ...
        self.cal_pred = 0.0  # ... against the chances the model gave them
        self.table: Optional[List[str]] = None
        self.n_obs = 0
        self.ctx_pg = [0.25] * 4  # our P(goal) per suit, refreshed by the bot every turn
        self.me, self.ticks = -1, 240
        self._clear_round()

    def _clear_round(self) -> None:
        self.opps: List[list] = []  # [tick, suit, price, features, seller], each awaiting a resale bid
        self.bids: List[list] = []  # [tick, suit, price, bidder] of others, in time order
        self.trades: List[List[int]] = [[] for _ in range(4)]  # prices per suit
        self.offers_by: Dict[str, List[int]] = {}  # "seller|suit" -> ticks of their offers
        self.inventory = {s: [] for s in range(4)}
        self.own_open: List[list] = []  # [tick, suit, price, seller, features, prediction]
        self.realized = 0.0
        self.hits = 0.0
        self.misses = 0.0
        self.net = [0, 0, 0, 0]  # our cards bought minus sold this round, per suit

    # ----- rounds and tables -----------------------------------------------------------
    def start_round(self, me: int, ticks: int, table: Optional[List[str]] = None) -> None:
        if table is not None and self.table is not None and list(table) != self.table:
            self.cal_hits *= self.table_decay
            self.cal_pred *= self.table_decay
            self._forget_sellers()
        if table is not None:
            self.table = list(table)
        self.me, self.ticks = me, ticks
        self._clear_round()
        self.own_hits *= 0.5  # the caps ramp (allowed) and the kill switch, as ResaleTracker.seed
        self.own_misses *= 0.5
        self.cal_hits *= self.cal_decay
        self.cal_pred *= self.cal_decay
        for i in range(len(self.S)):
            self.S[i][i] += self.forget
        del self.prices[:-50]

    def _forget_sellers(self) -> None:
        """New opponents: the per-seller offsets are keyed by seat, and the seats now hold other
        players, so drop them.  For a Gaussian posterior that is exact marginalisation (drop their
        rows and columns), which leaves the shared weights as learned."""
        d = len(LEARNER_FEATURES)
        self.mu = self.mu[:d]
        self.S = [row[:d] for row in self.S[:d]]
        self.sellers = {}

    # ----- the model -------------------------------------------------------------------
    def _vec(self, x: List[float], seller: Optional[int], grow: bool) -> Tuple[List[int], List[float]]:
        idx = list(range(len(x)))
        vals = list(x)
        if seller is not None:
            k = self.sellers.get(seller)
            if k is None and grow:
                k = len(self.mu)
                self.sellers[seller] = k
                self.mu.append(0.0)
                for row in self.S:
                    row.append(0.0)
                self.S.append([0.0] * k + [self.seller_var])
            if k is not None:
                idx.append(k)
                vals.append(1.0)
        return idx, vals

    def _z_var(self, idx: List[int], vals: List[float]) -> Tuple[float, float]:
        z = 0.0
        for i, v in zip(idx, vals):
            z += self.mu[i] * v
        var = 0.0
        for i, vi in zip(idx, vals):
            row = self.S[i]
            acc = 0.0
            for j, vj in zip(idx, vals):
                acc += row[j] * vj
            var += acc * vi
        return z, var

    def _update(self, x: List[float], seller: Optional[int], y: float, wt: float) -> None:
        idx, vals = self._vec(x, seller, True)
        z, var = self._z_var(idx, vals)
        p = _sigmoid(z)
        h = wt * p * (1.0 - p)
        g = wt * (y - p)
        n = len(self.mu)
        sx = []
        for i in range(n):
            row = self.S[i]
            acc = 0.0
            for j, vj in zip(idx, vals):
                acc += row[j] * vj
            sx.append(acc)
        denom = 1.0 + h * var
        for i in range(n):
            if sx[i] == 0.0:
                continue
            f = sx[i] * h / denom
            row = self.S[i]
            for j in range(n):
                if sx[j] != 0.0:
                    row[j] -= f * sx[j]
        for i in range(n):
            row = self.S[i]
            acc = 0.0
            for j, vj in zip(idx, vals):
                acc += row[j] * vj
            self.mu[i] += acc * g
        self.n_obs += 1

    def p_resale(self, x: List[float], seller: Optional[int], lcb: bool = True) -> float:
        """Chance that a card bought at this opportunity is bid back up: a lower confidence
        bound (``lcb``) or the posterior mean."""
        idx, vals = self._vec(x, seller, False)
        z, var = self._z_var(idx, vals)
        if lcb:
            return _sigmoid(z - self.z_lcb * math.sqrt(max(var, 0.0)))
        return _sigmoid(z / math.sqrt(1.0 + math.pi * var / 8.0))

    def calibration(self) -> float:
        """How our own resale buys have fared against the model's predictions for them."""
        return min(1.2, (self.cal_prior + self.cal_hits) / (self.cal_prior + self.cal_pred))

    def features(self, tick: int, s: int, price: int, seller: Optional[int], held: Optional[bool] = None) -> List[float]:
        """The opportunity's features; ``held`` (default: whether we are long ``s`` now) is the
        position the answer depends on, True for a buy we are deciding on or have made."""
        if held is None:
            held = self.net[s] > 0
        tr = self.trades[s][-3:]
        ref = sorted(tr)[len(tr) // 2] if tr else price
        demand = 0
        depth: List[int] = []
        for t, s2, p, who in reversed(self.bids):
            if tick - t > 60:
                break
            if s2 != s or who == seller:
                continue
            if tick - t <= 30 and p > demand:
                demand = p
            if p >= price + self.margin and who not in depth:
                depth.append(who)
        streak = 0
        for t in self.offers_by.get(f"{seller}|{s}", []):
            if tick - t <= 20:
                streak += 1
        return [
            1.0,
            price / 5.0,
            1.0 if price <= 2 else 0.0,
            (price - ref) / 5.0,
            demand / 5.0,
            len(depth) / 2.0,
            self.ctx_pg[s],
            tick / max(1, self.ticks),
            min(3, streak) / 3.0,
            1.0 if self.robust and held else 0.0,
        ]

    # ----- what the market shows (fed by the bot) -----------------------------------------
    def cheap_seen(self, tick: int, s: int, price: int, seller: int) -> None:
        pass  # the learner is fed by quote_seen / trade_seen instead

    def bid_seen(self, tick: int, s: int, price: int, bidder: int) -> None:
        """A bid that proved real (robust): only these, and trades, answer the questions."""
        if not self.robust or bidder == self.me:
            return
        self.bids.append([tick, s, price, bidder])
        self._resolve(tick, s, price, bidder)

    def quote_seen(self, tick: int, s: int, is_bid: bool, price: int, player: int) -> None:
        if player == self.me:
            return
        if is_bid:
            if not self.robust:
                self.bids.append([tick, s, price, player])
                self._resolve(tick, s, price, player)
            return
        self.offers_by.setdefault(f"{player}|{s}", []).append(tick)
        if price <= self.max_price and self.ticks - tick >= self.min_left:
            # every offer is its own question (a seller pennying down asks it again, cheaper)
            self.opps.append([tick, s, price, self.features(tick, s, price, player), player])

    def trade_seen(self, tick: int, s: int, price: int, buyer: int, seller: int) -> None:
        if buyer == self.me:
            self.net[s] += 1
        elif seller == self.me:
            self.net[s] -= 1
        self.trades[s].append(price)
        if buyer != self.me:
            self.bids.append([tick, s, price, buyer])  # paying a price is bidding it
            self._resolve(tick, s, price, buyer)
        if seller != self.me and buyer != self.me and price <= self.max_price and self.ticks - tick >= self.min_left:
            # a cheap sale between two others is an opportunity too, unless it was an offer we
            # already count (the seller's own, at this price)
            for o in self.opps:
                if o[4] == seller and o[1] == s and o[2] == price:
                    break
            else:
                self.opps.append([tick, s, price, self.features(tick, s, price, seller), seller])

    def _resolve(self, tick: int, s: int, price: int, bidder: int) -> None:
        keep = []
        for o in self.opps:
            t0, s0, p0, x, seller = o
            if s0 == s and bidder != seller and price >= p0 + self.margin and tick - t0 <= self.window:
                self._update(x, seller, 1.0, self.market_weight)
                self.hits += 1
                self.prices.append(price)
            else:
                keep.append(o)
        self.opps = keep
        mine = []
        for item in self.own_open:
            t0, s0, p0, seller, x, pred = item
            if s0 == s and bidder != seller and price >= p0 + self.margin and tick - t0 <= self.window:
                self.cal_hits += 1.0
                self.cal_pred += pred
            else:
                mine.append(item)
        self.own_open = mine

    def expire(self, tick: int) -> None:
        keep = []
        for o in self.opps:
            if tick - o[0] > self.window:
                self._update(o[3], o[4], 0.0, self.market_weight)
                self.misses += 1
            else:
                keep.append(o)
        self.opps = keep
        mine = []
        for item in self.own_open:
            if tick - item[0] > self.window:
                self.cal_pred += item[5]  # never bid back up: a miss for our record
            else:
                mine.append(item)
        self.own_open = mine
        for s in range(4):
            for item in self.inventory[s]:
                if not item[2] and tick - item[0] > self.window:
                    item[2] = True
                    self.own_misses += 1
                    self.realized -= item[1]

    # ----- our own resale buys ------------------------------------------------------------
    def bought_from(self, tick: int, s: int, price: int, seller: Optional[int]) -> None:
        self.bought(tick, s, price)
        x = self.features(tick, s, price, seller, held=True)
        self.own_open.append([tick, s, price, seller, x, self.p_resale(x, seller, lcb=False)])

    # ----- decisions ------------------------------------------------------------------------
    def active(self) -> bool:
        return not (self.realized <= -self.stop_loss or self.own_misses - self.own_hits >= self.max_net_misses)

    def value_at(self, tick: int, s: int, price: int, seller: Optional[int], hold_value: float = 0.0) -> Optional[float]:
        """Expected gain from buying a card of ``s`` at ``price`` (from ``seller``, if known) to
        resell it; an unsold card is worth what it is to us anyway (``hold_value``, at most the
        price).  None when it may not buy."""
        if price > self.max_price or not self.active():
            return None
        r = self.resale_price()
        exit_px = max(price + self.margin, r if r is not None else 0)
        x = self.features(tick, s, price, seller, held=True)  # as it will be once we hold the card
        p = min(1.0, self.p_resale(x, seller) * self.calibration())
        salvage = min(max(0.0, hold_value), float(price))
        return p * (exit_px - price) + (1.0 - p) * (salvage - price)

    def p_hit(self) -> float:
        """For the panel: the model's (mean) chance for a $1 card nobody has bid on yet, bought."""
        x = [1.0, 0.2, 1.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 1.0 if self.robust else 0.0]
        return self.p_resale(x, None, lcb=False) * self.calibration()

    # ----- carrying the model ---------------------------------------------------------------
    def state(self) -> dict:
        """Everything, JSON-friendly (the JS port loads the same dict)."""
        return {
            "d": len(LEARNER_FEATURES),
            "mu": list(self.mu),
            "S": [list(r) for r in self.S],
            "sellers": [[p, k] for p, k in self.sellers.items()],
            "cal": [self.cal_hits, self.cal_pred],
            "table": None if self.table is None else list(self.table),
            "n_obs": self.n_obs,
            "ctx_pg": list(self.ctx_pg),
            "me": self.me,
            "ticks": self.ticks,
            "opps": [[o[0], o[1], o[2], list(o[3]), o[4]] for o in self.opps],
            "bids": [list(b) for b in self.bids],
            "trades": [list(t) for t in self.trades],
            "offers_by": [[k, list(v)] for k, v in self.offers_by.items()],
            "inventory": [[list(it) for it in self.inventory[s]] for s in range(4)],
            "own_open": [[it[0], it[1], it[2], it[3], list(it[4]), it[5]] for it in self.own_open],
            "counts": [self.hits, self.misses, self.own_hits, self.own_misses, self.realized],
            "prices": list(self.prices),
            "net": list(self.net),
        }

    def _upgrade(self, m: dict) -> Tuple[List[float], List[List[float]], Dict[int, int]]:
        """``mu``, ``S`` and ``sellers`` of a saved model in today's layout.  A v12 model (no
        "held" weight) gets one inserted after its shared weights, at the prior (mean 0,
        variance ``prior_var``, uncorrelated), and its seller offsets move up one place."""
        mu = list(m["mu"])
        S = [list(r) for r in m["S"]]
        sellers = {p: k for p, k in m["sellers"]}
        d_old, d = m.get("d", _V12_D), len(LEARNER_FEATURES)
        if d_old < d:
            ins = d - d_old
            n = len(mu) + ins
            pos = list(range(d_old)) + list(range(d, n))  # where each old index goes
            S2 = [[0.0] * n for _ in range(n)]
            for a, ia in enumerate(pos):
                for b, ib in enumerate(pos):
                    S2[ia][ib] = S[a][b]
            for i in range(d_old, d):
                S2[i][i] = self.prior_var
            mu = mu[:d_old] + [0.0] * ins + mu[d_old:]
            S = S2
            sellers = {p: (k + ins if k >= d_old else k) for p, k in sellers.items()}
        return mu, S, sellers

    @staticmethod
    def _pad(x: List[float]) -> List[float]:
        """An opportunity's features as saved by v12 (no "held"): not held."""
        return list(x) + [0.0] * (len(LEARNER_FEATURES) - len(x))

    def load(self, st: dict) -> None:
        self.mu, self.S, self.sellers = self._upgrade(st)
        self.cal_hits, self.cal_pred = st["cal"]
        self.table = None if st["table"] is None else list(st["table"])
        self.n_obs = st["n_obs"]
        self.ctx_pg = list(st["ctx_pg"])
        self.me, self.ticks = st["me"], st["ticks"]
        self.opps = [[o[0], o[1], o[2], self._pad(o[3]), o[4]] for o in st["opps"]]
        self.bids = [list(b) for b in st["bids"]]
        self.trades = [list(t) for t in st["trades"]]
        self.offers_by = {k: list(v) for k, v in st["offers_by"]}
        self.inventory = {s: [list(it) for it in st["inventory"][s]] for s in range(4)}
        self.own_open = [[it[0], it[1], it[2], it[3], self._pad(it[4]), it[5]] for it in st["own_open"]]
        self.hits, self.misses, self.own_hits, self.own_misses, self.realized = st["counts"]
        self.prices = list(st["prices"])
        self.net = list(st.get("net", [0, 0, 0, 0]))

    def memory(self, keep: float = 0.5, n_prices: int = 12):
        """The model to carry into a new bot's next round (the live adapter and the replay tools
        pass it to :meth:`seed`), already aged by one round as :meth:`start_round` would."""
        return [
            {
                "d": len(LEARNER_FEATURES),
                "mu": list(self.mu),
                "S": [[x + (self.forget if i == j else 0.0) for j, x in enumerate(r)] for i, r in enumerate(self.S)],
                "sellers": [[p, k] for p, k in self.sellers.items()],
                "cal": [self.cal_hits * self.cal_decay, self.cal_pred * self.cal_decay],
                "own": [self.own_hits * 0.5, self.own_misses * 0.5],
                "table": None if self.table is None else list(self.table),
                "n_obs": self.n_obs,
                "prices": list(self.prices[-50:]),
            }
        ]

    def round_start_model(self) -> dict:
        """The model exactly as this round started (call right after :meth:`start_round`): what
        the live adapter logs as the round's resale_seed, so replays start where the live bot did."""
        return {
            "exact": True,
            "d": len(LEARNER_FEATURES),
            "mu": list(self.mu),
            "S": [list(r) for r in self.S],
            "sellers": [[p, k] for p, k in self.sellers.items()],
            "cal": [self.cal_hits, self.cal_pred],
            "own": [self.own_hits, self.own_misses],
            "table": None if self.table is None else list(self.table),
            "n_obs": self.n_obs,
            "prices": list(self.prices),
        }

    def seed(self, *args) -> None:
        """Take over a model carried from an earlier round, after :meth:`start_round`: one handed
        over by :meth:`memory` (aged, and faded further if the opponents changed) or one logged by
        :meth:`round_start_model` (as is).  A ResaleTracker record only lends its resale prices."""
        if len(args) == 1 and isinstance(args[0], dict):
            m = args[0]
            self.mu, self.S, self.sellers = self._upgrade(m)
            self.cal_hits, self.cal_pred = m["cal"]
            self.own_hits, self.own_misses = m["own"]
            if not m.get("exact") and m["table"] is not None and self.table is not None and list(m["table"]) != self.table:
                self.cal_hits *= self.table_decay
                self.cal_pred *= self.table_decay
                self._forget_sellers()
            if m.get("exact"):
                self.table = None if m["table"] is None else list(m["table"])
            self.n_obs = m["n_obs"]
            self.prices = list(m["prices"])
        elif len(args) == 5:
            self.prices.extend(args[4])
