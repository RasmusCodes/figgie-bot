"""SharkBot: a Bayesian card counter that trades patiently on bonus-aware values.

Each turn it

1. refreshes its beliefs: an exact posterior over the 12 decks from its hand,
   everything the tape proves about other hands, and what the market's most
   aggressive prices say about the goal suit ("smart money": nobody bids $10+
   for a suit they think is dead, and nobody dumps a suit they believe in);
2. turns them into marginal card values that include the fight for the
   majority bonus (see :mod:`figgie.model`);
3. takes the single best mispriced resting order, but only with a real edge,
   never paying more than ``max_pay`` x P(goal) for a card, and never dumping a
   card below what it paid unless it is confident the suit is dead;
4. re-quotes every suit patiently: bids open low and climb slowly, sit well
   under value (whoever hits a resting bid probably knows the suit is dead),
   and offers on a suit that might be the goal stay expensive.

``SHARK_V1`` holds the original, much more aggressive settings for comparison.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, replace
from typing import Iterable, Optional

from .bots import work_bid, work_offer
from .engine import CONFIGS, GOAL_PAYOUT, NUM_SUITS, SUIT_CHARS, Bot, GameInfo, Market, QuoteEvent, Trade
from .model import Beliefs, QuoteModel, SmartMoneyModel, Valuation
from .patterns import ReadingLearner, ResaleLearner, ResaleTracker


@dataclass
class SharkParams:
    alpha_start: float = 3.0  # bonus-contest sharpness at the open ...
    alpha_end: float = 40.0  # ... rising geometrically to this at the close
    take_edge: float = 1.0  # cross the spread only for at least this many $ ...
    take_frac: float = 0.20  # ... plus this fraction of the card's value
    quote_edge: float = 1.0  # resting quotes sit this many $ inside value ...
    quote_frac: float = 0.20  # ... plus this fraction of it
    adverse: float = 0.15  # resting quotes give up a further fraction: fills are adversely selected
    max_pay: float = 50.0  # never pay more than max_pay * P(goal) for a card
    open_frac: float = 0.3  # first bid on an empty book at this fraction of the limit
    open_markup: float = 3.0  # first offer on an empty book this many $ above the limit
    step: int = 1  # walk resting quotes toward the limit by this much ...
    step_every: int = 3  # ... once every this many ticks
    revalue_every: int = 5  # recompute values at least this often (ticks)
    read_weight: float = 0.5  # trust in other players' quotes as signals of their hands (0 = ignore)
    read_scale: float = 20.0  # assumed $ value of a sure goal card to them
    read_tau: float = 4.0  # $ noise in their quotes
    read_eps: float = 0.3  # chance a quote carries no information
    read_every: int = 5  # re-read the other players' quotes every N ticks
    # smart money (v7): fitted to 42 live rounds against figgie.com's bots, where $10-15 bids
    # are common on dead suits and only the highest bids single out the goal
    smart_weight: float = 1.0  # trust in the market's extreme prices as goal-suit votes (0 = ignore)
    smart_bid_mid: float = 17.0  # a top bid at this price is neutral evidence
    smart_bid_up: float = 0.8  # nats per $ a top bid sits above it
    smart_offer_mid: float = 5.0  # a bottom offer at this price is neutral evidence
    smart_offer_down: float = 0.56  # nats per $ a bottom offer sits below it
    churn_guard: float = 0.6  # never sell below this fraction of what we paid ...
    churn_p: float = 0.15  # ... unless P(goal) for the suit has fallen below this
    hold_goal: float = 25.0  # option value of waiting: a card may yet prove to be the goal and fetch this ...
    hold_dead: float = 5.0  # ... or prove dead and still fetch this; both fade linearly to 0 by the bell
    smart_player_cap: float = 0.0  # >0: one smart-money vote per other player, each capped at this many nats ...
    smart_total_cap: float = 4.0  # ... with the summed votes capped at this
    # >0: never-dump protections use the highest recent P(goal), fading with this half-life (ticks).
    # v11: 30 (was 60).  A suit that looked 26% likely a minute and a half ago still held its cards
    # off $4 bids at 5%; halving the memory sold more dead cards in replays of 30 logged rounds.
    sticky_halflife: float = 30.0
    buy_halflife: float = 8.0  # >0: the pay cap uses min(P(goal), its moving average with this half-life (ticks))
    consolidate: float = 1.0  # 0-1: value the bonus as if the goal cards we lack end up with one rival
    consolidate_at: float = 0.5  # ... but only once we hold at least this share of the goal suit
    smart_bid_down: float = 0.3  # nats per $ a top bid sits below smart_bid_mid (evidence against)
    smart_cap: float = 10.0  # each smart-money signal is capped at this many nats
    smart_bid_none: Optional[float] = 4.0  # score a suit nobody has bid on as this top bid (None: no evidence)
    # >0: another player's bid counts as evidence only once it has stood in the book on this many
    # different ticks when we looked, been outbid by someone else, or been cleared by a trade after
    # we saw it.  A bid pulled sooner (a flash or spoof) is ignored, and until then we trade against
    # it on our old beliefs - so selling into a spoofed bid costs the spoofer.
    smart_confirm: int = 2
    # a pending bid cleared by a trade counts only if we had seen it standing on this many ticks
    smart_confirm_trade: int = 1
    # consensus (see SmartMoneyModel): nats per $ that the lowest of the opponents' own top bids on
    # a suit sits above smart_consensus_mid, capped at smart_consensus_cap
    smart_consensus: float = 0.0
    smart_consensus_mid: float = 5.0
    smart_consensus_cap: float = 4.0
    # v9: early in a round, whoever lifts our offer tends to know the suit is the goal (in the
    # live record, early sales were of the goal about twice as often as the bot believed).  A
    # lift counts as evidence with this likelihood ratio at the open (1 = ignore), fading toward
    # 1 with time constant fill_tau ticks, and an offer asks at least what keeping the card is
    # worth given that someone lifted it.
    fill_lr_offer: float = 3.0
    fill_tau: float = 60.0
    # >0: early bids and offers are read as evidence about a suit's colour (split evenly between it
    # and its same-colour partner), turning suit-specific linearly over this many ticks (in 5%
    # steps).  At figgie.com the highest bid in the first minute sat on the 12-card suit at least
    # as often as on the goal; the colour was right, the suit a coin flip.
    smart_colour_fade: float = 0.0
    # v10: cheap resale (see figgie.patterns).  At figgie.com a card dumped for $1-2 is soon bid
    # back up to $4+ by another bot.  >0: once that has happened resale_min_hits times this round,
    # lift other players' offers at up to this price (and, with resale_bid, bid that much on the
    # suits where the pattern shows) to sell the cards into those bids.  Never more than
    # resale_suit_cap such cards in a suit or resale_total_cap in all, none with fewer than
    # resale_min_left ticks to go, and none once our own resales stop working or have lost
    # resale_stop dollars this round.
    resale_cheap: int = 0
    resale_margin: int = 2
    resale_window: int = 45
    resale_edge: float = 0.5
    resale_min_hits: int = 2
    resale_min_left: int = 15
    resale_suit_cap: int = 2
    resale_total_cap: int = 4
    resale_stop: float = 6.0
    resale_patience: int = 30
    resale_bid: bool = False
    # v12: learn which offers resell instead of assuming "$resale_cheap or less" (ResaleLearner in
    # figgie.patterns): any offer up to resale_learn_max, judged by an online model of whether a
    # third player bids it back up, calibrated by our own resales.  Needs resale_cheap > 0 (the
    # caps, kill switch and resting bids above still apply; resting resale bids go up to
    # resale_cheap).  The learner stays with the bot from round to round.
    resale_learn: bool = False
    resale_learn_max: int = 5
    # v13: harden the learner against a poisoned tape (ResaleLearner robust): only bids that
    # proved real answer its questions, and it learns whether others' bids depend on our holding
    # the suit (the bait rings' trick), judging a buy as of after it.
    resale_robust: bool = False
    # Up to v10, offers on a suit that might be the goal leaned toward what the card would be
    # worth if it is, by adverse_offer x adverse x (value if goal - value).  The lean never fades,
    # so a big holding of a long shot, whose cards are worth a lot only if it is the goal, kept
    # its offer high to the bell (v10: 5 diamonds at 5% offered at $14 into $4 bids).  The risk
    # it prices, an informed lifter, has been priced by fill_lr_offer since v9, fading as the
    # market speaks, so v11 drops it (0).
    adverse_offer: float = 0.0
    # v13: learn from the revealed goals how far to trust the colour reading (smart_colour_fade)
    # and the consensus (smart_consensus) at this table (ReadingLearner in figgie.patterns),
    # scaling both by the learned probability that they work here.  The early top bid is taken
    # read_learn_at ticks into the round.
    read_learn: bool = False
    read_learn_at: int = 60
    # >0: holding at least this many cards of a suit that is the goal with P(goal) >= locked_p,
    # sell one into any bid that beats what keeping it is worth by take_edge: no take_frac margin,
    # no waiting premium (hold_floor), no churn guard.  A goal suit has 8 or 10 cards, so keeping 6
    # wins the bonus outright, and with 7 or more a spare card is worth its payout and no more.
    # (v13.3: an $11 bid for the goal with 7 held went unsold live, the margin wanting $13.)
    locked_sell: int = 0
    locked_p: float = 0.95


# The smart-money reading of v2-v6, calibrated on a single recorded round.
_SMART_V2_V6 = dict(
    smart_weight=1.6,
    smart_bid_mid=8.0,
    smart_bid_up=0.45,
    smart_bid_down=0.08,
    smart_cap=3.0,
    smart_offer_down=0.35,
    smart_bid_none=None,
    smart_confirm=0,
    fill_lr_offer=1.0,
    sticky_halflife=60.0,
    adverse_offer=1.0,
)

# The first version: fast and aggressive, no smart money, no churn guard, no waiting.
SHARK_V1 = dict(
    fill_lr_offer=1.0,
    take_frac=0.10,
    adverse=0.0,
    max_pay=1e9,
    open_frac=0.6,
    step_every=1,
    smart_weight=0.0,
    smart_confirm=0,
    churn_guard=0.0,
    hold_goal=0.0,
    hold_dead=0.0,
    sticky_halflife=0.0,
    buy_halflife=0.0,
    consolidate=0.0,
)

# The second version (smart money, patience) before it learned to wait.
SHARK_V2 = dict(_SMART_V2_V6, hold_goal=0.0, hold_dead=0.0, sticky_halflife=0.0, buy_halflife=0.0, consolidate=0.0)

# The third version (waiting premium) before its beliefs were steadied.
SHARK_V3 = dict(_SMART_V2_V6, sticky_halflife=0.0, buy_halflife=0.0, consolidate=0.0)

# The fourth version (steadied beliefs) before it expected rivals to consolidate the goal suit.
SHARK_V4 = dict(_SMART_V2_V6, consolidate=0.0, consolidate_at=0.0)

# The fifth version: expected consolidation at every holding, which made small holdings look cheap.
SHARK_V5 = dict(_SMART_V2_V6, consolidate=0.5, consolidate_at=0.0)

# The sixth version: consolidation only from half the goal suit, before the live-fitted smart money.
SHARK_V6 = dict(_SMART_V2_V6)

# The seventh and eighth versions (identical in the simulator, where the v8 consensus term is
# off): offers priced as if a lift said nothing about the buyer.
SHARK_V8 = dict(fill_lr_offer=1.0, sticky_halflife=60.0, adverse_offer=1.0)

# The ninth and tenth versions (identical in the simulator, where v10's resale and colour reading
# are off): a minute's memory of a suit's best P(goal), and offers leaning toward the goal value.
SHARK_V10 = dict(sticky_halflife=60.0, adverse_offer=1.0)

# What the userscript plays at figgie.com (LIVE_PARAMS in web/figgie-shark.user.js): the
# production bot, `sharklive` in the simulator.  v12's and v13's live settings stay as
# `sharkv12` and `sharkv13`.
SHARK_LIVE_V12 = dict(smart_consensus=0.8, smart_colour_fade=90, resale_cheap=2, resale_bid=True, resale_learn=True)
SHARK_LIVE_V13 = dict(SHARK_LIVE_V12, resale_robust=True, read_learn=True)
SHARK_LIVE = dict(SHARK_LIVE_V13, locked_sell=7)


class SharkBot(Bot):
    name = "shark"

    def __init__(self, **params) -> None:
        self.params = SharkParams(**params)
        P = self.params
        self.reading = QuoteModel(P.read_weight, P.read_scale, P.read_tau, P.read_eps)
        self.smart = SmartMoneyModel(
            weight=P.smart_weight,
            bid_mid=P.smart_bid_mid,
            bid_up=P.smart_bid_up,
            offer_mid=P.smart_offer_mid,
            offer_down=P.smart_offer_down,
            player_cap=P.smart_player_cap,
            total_cap=P.smart_total_cap,
            bid_down=P.smart_bid_down,
            cap=P.smart_cap,
            bid_none=P.smart_bid_none,
            consensus_slope=P.smart_consensus,
            consensus_mid=P.smart_consensus_mid,
            consensus_cap=P.smart_consensus_cap,
        )
        # v12 learned resale: one learner for the bot's whole life, so what it learns at a table
        # carries into the next round (a new bot can take over an old one's: assign it here)
        self.learner: Optional[ResaleLearner] = None
        # v13: what it has learned about reading this table's bids (read_learn), kept likewise
        self.reader: Optional[ReadingLearner] = None

    # ----- events --------------------------------------------------------------
    def on_start(self, info: GameInfo) -> None:
        self.me = info.player
        self.ticks = info.rules.ticks
        self.beliefs = Beliefs(info.player, info.rules.n_players, info.hand, info.rules.hand_size)
        smart = self.smart
        self._colour_scale = 1.0
        self._early_top: Optional[int] = None
        self._early_done = False
        if self.params.read_learn:
            if self.reader is None:
                self.reader = ReadingLearner()
            self.reader.start_round([name for p, name in enumerate(info.names) if p != info.player])
            self._colour_scale = self.reader.p_colour()
            smart = replace(smart, consensus_slope=smart.consensus_slope * self.reader.p_consensus())
        self.beliefs.smart = smart if smart.weight > 0.0 else None
        self.beliefs.consolidate = self.params.consolidate
        self.beliefs.consolidate_at = self.params.consolidate_at
        self.slot = self.beliefs.slot
        self.cost = [0.0] * NUM_SUITS  # average-cost book of the cards we bought and still hold
        self.bought = [0] * NUM_SUITS
        self._val: Optional[Valuation] = None
        self._val_tick = -(10**9)
        self._read_tick = -(10**9)
        self._dirty = True
        self.p_sticky: Optional[list] = None  # recent-max P(goal): protects what we hold
        self.p_avg: Optional[list] = None  # moving-average P(goal): caps what we pay
        self._p_tick: Optional[int] = None
        self._pending: dict = {}  # suit -> [QuoteEvent, turns seen]: other players' bids not yet proven
        self._clear_on_trade = info.rules.clear_on_trade
        P = self.params
        self.resale: Optional[ResaleTracker] = None
        self._resale_buy: Optional[int] = None  # suit of a resale buy we have sent, until it fills
        self._resale_bids = [0] * NUM_SUITS  # the resale bid we last quoted per suit (0: none)
        if P.resale_cheap > 0 and P.resale_learn:
            if self.learner is None:
                self.learner = ResaleLearner(
                    max_price=P.resale_learn_max,
                    margin=P.resale_margin,
                    window=P.resale_window,
                    min_left=P.resale_min_left,
                    stop_loss=P.resale_stop,
                    robust=P.resale_robust,
                )
            others = [name for p, name in enumerate(info.names) if p != info.player]
            self.learner.start_round(info.player, info.rules.ticks, others)
            self.resale = self.learner
        elif P.resale_cheap > 0:
            self.resale = ResaleTracker(
                cheap=P.resale_cheap,
                margin=P.resale_margin,
                window=P.resale_window,
                min_hits=P.resale_min_hits,
                stop_loss=P.resale_stop,
            )

    def on_trade(self, t: Trade) -> None:
        if self._pending:
            # a trade clears the book: a pending bid we saw rest through one of our turns was real
            for s in [s for s in self._pending if self._clear_on_trade or s == t.suit]:
                ev, seen, _ = self._pending.pop(s)
                if seen >= self.params.smart_confirm_trade:
                    self._accept(ev)
        self.beliefs.observe_trade(t)
        if t.buyer == self.me:
            self.cost[t.suit] += t.price
            self.bought[t.suit] += 1
        elif t.seller == self.me and self.bought[t.suit] > 0:
            self.cost[t.suit] -= self.cost[t.suit] / self.bought[t.suit]
            self.bought[t.suit] -= 1
        r = self.resale
        if r is not None and r is self.learner:
            if t.seller == self.me:
                r.sold(t.suit, t.price)
            elif t.buyer == self.me and (self._resale_buy == t.suit or 0 < t.price <= self._resale_bids[t.suit]):
                r.bought_from(t.tick, t.suit, t.price, t.seller)  # a resale buy, booked with its seller
                self._resale_buy = None
            r.trade_seen(t.tick, t.suit, t.price, t.buyer, t.seller)
        elif r is not None:
            if t.buyer != self.me:
                r.bid_seen(t.tick, t.suit, t.price, t.buyer)  # a purchase is as real as a bid gets
                if t.seller != self.me:
                    r.cheap_seen(t.tick, t.suit, t.price, t.seller)
            if t.seller == self.me:
                r.sold(t.suit, t.price)
            elif t.buyer == self.me and (self._resale_buy == t.suit or 0 < t.price <= self._resale_bids[t.suit]):
                r.bought(t.tick, t.suit, t.price)  # a resale buy we sent, or a fill on a resale bid
                self._resale_buy = None
        self._dirty = True

    def on_quote(self, ev: QuoteEvent) -> None:
        if self.resale is not None and self.resale is self.learner:
            self.learner.quote_seen(ev.tick, ev.suit, ev.is_bid, ev.price, ev.player)  # every quote, as it comes
        if self.resale is not None and not ev.is_bid and ev.player != self.me:
            self.resale.cheap_seen(ev.tick, ev.suit, ev.price, ev.player)
        if self.params.smart_confirm > 0 and ev.is_bid and ev.player != self.me:
            old = self._pending.get(ev.suit)
            if old is not None and old[0].player != ev.player and old[1] >= 1:
                self._accept(old[0])  # outbid by someone else after resting: it was real
            self._pending[ev.suit] = [ev, 0, None]  # [bid, ticks seen standing, last tick seen]
            return
        self._accept(ev)

    def _accept(self, ev: QuoteEvent) -> None:
        if self.resale is not None and ev.is_bid and ev.player != self.me:
            self.resale.bid_seen(ev.tick, ev.suit, ev.price, ev.player)  # only bids that proved real
        if self.beliefs.observe_quote(ev):
            self._dirty = True

    def _check_pending(self, m: Market) -> None:
        """Count each tick a pending bid is still standing (once per tick, however
        often we act); drop the ones withdrawn."""
        for s in list(self._pending):
            entry = self._pending[s]
            ev = entry[0]
            cur = m.best_bid(s)
            if cur is not None and cur.player == ev.player and cur.price == ev.price:
                if entry[2] != m.tick:
                    entry[1] += 1
                    entry[2] = m.tick
                    if entry[1] >= self.params.smart_confirm:
                        del self._pending[s]
                        self._accept(ev)
            else:
                del self._pending[s]  # gone without a trade or a higher bid: pulled, so ignore it

    # ----- valuation -----------------------------------------------------------
    def alpha(self, tick: int) -> float:
        a0, a1 = self.params.alpha_start, self.params.alpha_end
        frac = min(1.0, tick / max(1, self.ticks - 1))
        return a0 * (a1 / a0) ** frac

    def valuation(self, tick: int) -> Valuation:
        fade = self.params.smart_colour_fade
        if fade > 0.0 and self.beliefs.smart is not None:
            mix = math.floor(max(0.0, 1.0 - tick / fade) * 20.0) / 20.0
            if self._colour_scale != 1.0:
                mix *= self._colour_scale  # read_learn: how far colour reading works at this table
            if mix != self.beliefs.smart_colour_mix:
                self.beliefs.set_smart_colour_mix(mix)
                self._dirty = True
        if self.reading.weight > 0.0 and tick - self._read_tick >= self.params.read_every:
            self.beliefs.refresh_quote_reading(self.reading)
            self._read_tick = tick
            self._dirty = True
        if self._dirty or self._val is None or tick - self._val_tick >= self.params.revalue_every:
            self._val = self.beliefs.valuation(round(self.alpha(tick), 2))
            self._val_tick = tick
            self._dirty = False
        self._track(tick, self._val.p_goal)
        return self._val

    def _track(self, tick: int, pg) -> None:
        """Keep a sticky (recent-max) and a smoothed (moving-average) copy of P(goal)."""
        P = self.params
        if self._p_tick is None:
            self.p_sticky, self.p_avg, self._p_tick = list(pg), list(pg), tick
            return
        dt = tick - self._p_tick
        if dt > 0:
            ds = 0.5 ** (dt / P.sticky_halflife) if P.sticky_halflife > 0.0 else 0.0
            da = 0.5 ** (dt / P.buy_halflife) if P.buy_halflife > 0.0 else 0.0
            self.p_sticky = [max(p, q * ds) for p, q in zip(pg, self.p_sticky)]
            self.p_avg = [p + (a - p) * da for p, a in zip(pg, self.p_avg)]
            self._p_tick = tick
        else:  # same tick: the sticky copy can only rise; the average moves once per tick
            self.p_sticky = [max(p, q) for p, q in zip(pg, self.p_sticky)] if P.sticky_halflife > 0.0 else list(pg)
            if P.buy_halflife <= 0.0:
                self.p_avg = list(pg)

    def p_hold(self, s: int, v: Valuation) -> float:
        """P(goal) for deciding what NOT to sell: the highest recent value."""
        return max(v.p_goal[s], self.p_sticky[s]) if self.p_sticky is not None else v.p_goal[s]

    def p_pay(self, s: int, v: Valuation) -> float:
        """P(goal) for capping what we pay: no more than its recent average."""
        return min(v.p_goal[s], self.p_avg[s]) if self.p_avg is not None else v.p_goal[s]

    def sell_floor(self, s: int, v: Valuation) -> float:
        """Churn guard: the least we'll take for a card of ``s`` we paid for."""
        P = self.params
        if P.churn_guard <= 0.0 or self.bought[s] == 0 or self.p_hold(s, v) < P.churn_p:
            return 0.0
        return P.churn_guard * self.cost[s] / self.bought[s]

    def hold_floor(self, s: int, v: Valuation, tick: int) -> float:
        """What a card of ``s`` is worth if we keep it until the market shows
        whether its suit is the goal: then it either pays out / sells to the
        bonus chasers, or is dumped for whatever dead cards fetch.  The
        waiting premium fades to nothing by the bell."""
        P = self.params
        if P.hold_goal <= 0.0 and P.hold_dead <= 0.0:
            return 0.0
        return self._wait_value(s, v, tick, self.p_hold(s, v))

    def _wait_value(self, s: int, v: Valuation, tick: int, p: float) -> float:
        """Value of keeping a card of ``s`` for now, if it is the goal with probability ``p``."""
        P = self.params
        pg = v.p_goal[s]
        if_goal = v.sell[s] / pg if pg > 0.02 else float(GOAL_PAYOUT)
        w = max(0.0, 1.0 - tick / max(1, self.ticks))
        return p * max(if_goal, w * P.hold_goal) + (1.0 - p) * w * P.hold_dead

    def offer_lr(self, tick: int) -> float:
        """Likelihood ratio that the suit of an offer of ours is the goal, given that
        someone lifts it: ``fill_lr_offer`` at the open, fading toward 1 with time
        constant ``fill_tau`` ticks as the market reveals what the others know."""
        P = self.params
        if P.fill_lr_offer == 1.0 or P.fill_tau <= 0.0:
            return 1.0
        return 1.0 + (P.fill_lr_offer - 1.0) * math.exp(-tick / P.fill_tau)

    # ----- trading -------------------------------------------------------------
    def on_end(self, result) -> None:
        if self.reader is not None and self.params.read_learn:
            self.reader.end_round(result.config.goal, self._early_top, self.consensus_suit())

    def consensus_suit(self) -> Optional[int]:
        """The suit every opponent has bid up the most (the highest of the lowest per-opponent
        top bids), if that lowest bid clears the consensus midpoint by $3 and no suit ties it."""
        b = self.beliefs
        if len(b.others) < 2:
            return None
        lows = [min(b.top_by[p][s] or 0 for p in b.others) for s in range(NUM_SUITS)]
        best = max(lows)
        if best < self.params.smart_consensus_mid + 3 or lows.count(best) > 1:
            return None
        return lows.index(best)

    def act(self, m: Market) -> None:
        if not self._early_done and m.tick >= self.params.read_learn_at:
            self._early_done = True
            tops = [x if x is not None else 0 for x in self.beliefs.top_bid]
            best = max(tops)
            self._early_top = tops.index(best) if best > 0 and tops.count(best) == 1 else None
        if self._pending:
            self._check_pending(m)
        if self.resale is not None:
            self.resale.expire(m.tick)
            self._resale_buy = None  # a resale buy that has not filled by now never will
        v = self.valuation(m.tick)
        if self.resale is not None and self.resale is self.learner:
            self.learner.ctx_pg = list(v.p_goal)  # what the learner's p_goal feature reads
        if self._take(m, v):
            v = self.valuation(m.tick)
        self._quote(m, v, range(NUM_SUITS))

    def resale_gain(self, m: Market, s: int, price: int) -> Optional[float]:
        """Expected gain from buying a card of ``s`` at ``price`` to resell it, if the
        resale pattern is live and there is room for another resale card."""
        r, P = self.resale, self.params
        if r is None or self.ticks - m.tick < P.resale_min_left or price > m.cash:
            return None
        if r.held(s) >= P.resale_suit_cap or r.held_total() >= r.allowed(P.resale_total_cap):
            return None
        if r is self.learner:
            # who is selling (when it's the offer we'd lift), and what the card is worth to us anyway
            off = m.best_offer(s)
            seller = off.player if off is not None and off.price == price and off.player != self.me else None
            hold = self._val.sell[s] if self._val is not None else 0.0
            g = r.value_at(m.tick, s, price, seller, hold)
        else:
            g = r.value(price)
        return g if g is not None and g >= P.resale_edge else None

    def _take(self, m: Market, v: Valuation) -> bool:
        P = self.params
        hand = m.hand
        r = self.resale
        take_frac = P.take_frac
        best = None
        for s in range(NUM_SUITS):
            off = m.best_offer(s)
            if off is not None and off.player != self.me and off.price <= m.cash:
                val = min(v.buy_from[s][self.slot[off.player]], P.max_pay * self.p_pay(s, v))
                gain = val - off.price
                if gain >= P.take_edge + take_frac * val:
                    if best is None or gain > best[0]:
                        best = (gain, True, s, off.price, False)
                elif r is not None:
                    g = self.resale_gain(m, s, off.price)
                    if g is not None and (best is None or g > best[0]):
                        best = (g, True, s, off.price, True)
            bid = m.best_bid(s)
            if bid is not None and bid.player != self.me and hand[s] > 0:
                keep = v.sell_to[s][self.slot[bid.player]]
                if P.locked_sell > 0 and hand[s] >= P.locked_sell and v.p_goal[s] >= P.locked_p:
                    # the goal's majority is ours whatever we do with one card: it is worth its
                    # payout, so any bid above that is profit
                    val, need = keep, P.take_edge
                else:
                    val = max(keep, self.sell_floor(s, v), self.hold_floor(s, v, m.tick))
                    need = P.take_edge + take_frac * val
                gain = bid.price - val
                if gain >= need:
                    if best is None or gain > best[0]:
                        best = (gain, False, s, bid.price, False)
                elif r is not None and r.held(s) > 0:
                    # a resale card: sell it into the first bid that pays the resale target,
                    # unless the card is worth more to us than that bid
                    target = r.target(s, m.tick, P.resale_patience)
                    gain = bid.price - keep
                    if bid.price >= target and gain >= P.take_edge and (best is None or gain > best[0]):
                        best = (gain, False, s, bid.price, True)
        if best is None:
            return False
        _, is_buy, s, price, resale = best
        if not is_buy:
            return bool(m.sell(s, min_price=price))
        if resale:
            self._resale_buy = s  # on_trade books the card as resale stock when the fill comes
        return bool(m.buy(s, max_price=price))

    def _quote(self, m: Market, v: Valuation, suits: Iterable[int]) -> None:
        P = self.params
        hand = m.hand
        step = P.step if P.step_every <= 1 or m.tick % P.step_every == 0 else 0
        quote_frac = P.quote_frac
        for s in suits:
            b, a = v.buy[s], v.sell[s]
            if hand[s] > 0 and b > a:
                # Locally convex (just short of a majority): the next card is worth more
                # than the last one.  Price both sides off the chord slope instead.
                b = a = 0.5 * (b + a)
            pg = v.p_goal[s]
            bid_value = min(b, P.max_pay * self.p_pay(s, v)) * (1.0 - quote_frac - P.adverse)
            bid_limit = min(m.cash, math.floor(bid_value - P.quote_edge))
            if P.resale_bid and self.resale is not None:
                # while the resale pattern is live, stand ready to buy dumped cards ourselves
                self._resale_bids[s] = 0
                for price in range(P.resale_cheap, max(bid_limit, 0), -1):
                    if self.resale_gain(m, s, price) is not None:
                        bid_limit = self._resale_bids[s] = price
                        break
            work_bid(m, s, bid_limit, opening=math.floor(bid_limit * P.open_frac), step=step)
            if hand[s] > 0:
                # Whoever lifts our offer probably knows the suit is the goal, where our
                # last card is worth a / P(goal) - so lean the offer toward that value.
                if_goal = a / pg if pg > 0.02 else 0.0
                ask_value = a * (1.0 + quote_frac) + P.adverse_offer * P.adverse * max(0.0, if_goal - a) + P.quote_edge
                hold_value = self.hold_floor(s, v, m.tick) * (1.0 + quote_frac) + P.quote_edge
                lr = self.offer_lr(m.tick)
                if lr > 1.0 and (P.hold_goal > 0.0 or P.hold_dead > 0.0):
                    # Early on, a lift says the buyer knows more than we do: ask at least what
                    # keeping the card is worth given that someone lifted it.
                    ph = self.p_hold(s, v)
                    lifted = ph * lr / (ph * lr + 1.0 - ph)
                    hold_value = max(hold_value, self._wait_value(s, v, m.tick, lifted) * (1.0 + quote_frac) + P.quote_edge)
                ask_limit = math.ceil(max(ask_value, hold_value, self.sell_floor(s, v)))
                work_offer(m, s, ask_limit, opening=ask_limit + math.ceil(P.open_markup), step=step)

    # ----- introspection -------------------------------------------------------
    def describe(self) -> str:
        pg = self.beliefs.p_goal()
        parts = [f"P(goal) " + " ".join(f"{SUIT_CHARS[s]}{pg[s]:.2f}" for s in range(NUM_SUITS))]
        if self._val is not None:
            v = self._val
            parts.append("buy " + " ".join(f"{SUIT_CHARS[s]}{v.buy[s]:.0f}" for s in range(NUM_SUITS)))
            parts.append("sell " + " ".join(f"{SUIT_CHARS[s]}{v.sell[s]:.0f}" for s in range(NUM_SUITS)))
            parts.append(f"E[payout] ${v.expected:.0f}")
        return " | ".join(parts)


def params_dict(bot: SharkBot) -> dict:
    return asdict(bot.params)


class OracleSharkBot(SharkBot):
    """Simulator-only tough opponent: the shark's own bonus-aware strategy, plus,
    with probability ``accuracy``, a strong hint of the true goal suit at the deal
    (every deck with that goal gets ``strength`` times the weight).  It bids the
    goal suit up early and competes for the bonus - the behaviour seen from
    figgie.com's Hard bots.  It plays the v4 strategy, so the benchmark stays
    fixed while the shark itself changes."""

    name = "oshark"
    oracle = True

    def __init__(self, accuracy: float = 0.5, strength: float = 25.0, **params) -> None:
        super().__init__(**{**SHARK_V4, **params})
        self.accuracy = accuracy
        self.strength = strength

    def on_start(self, info: GameInfo) -> None:
        super().on_start(info)
        self._rng = random.Random(info.seed)

    def on_oracle(self, config) -> None:
        if self._rng.random() < self.accuracy:
            self.beliefs.prior = [self.strength if c.goal == config.goal else 1.0 for c in CONFIGS]
            self.beliefs._mins_state += 1
            self._dirty = True
