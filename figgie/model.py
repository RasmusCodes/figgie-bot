"""Bayesian card counting and card valuation for Figgie.

Everything here is exact combinatorics over the 12 possible decks.

Posterior
    P(deck | my hand, trading so far).  My own hand gives a multivariate
    hypergeometric likelihood.  Trading reveals hard lower bounds on the other
    players' *initial* holdings: nobody can sell a card they do not have, and a
    resting offer proves the offerer holds the suit.  Those bounds are scored
    suit by suit with the exact multivariate-hypergeometric probability that
    the unseen cards of the suit are spread so as to satisfy them.  (Treating
    suits independently ignores the 10-card hand-size coupling between suits,
    which barely moves the posterior but keeps it cheap.)

Valuation
    The value of my holdings is additive over suits: a card of suit ``s`` is
    worth $10 if ``s`` is the goal, plus its effect on my share of the
    majority bonus.  For every deck we enumerate how the unseen goal cards are
    split between the other players (consistent with what trading revealed),
    add the known net trades, and score my bonus share.

    The final allocation is still in flux early in the game, so the share is
    scored with a Tullock contest ``k**a / (k**a + sum(y**a))`` whose
    sharpness ``a`` grows during the game (``a = None`` is the exact
    winner-takes-all rule, ties split).  Marginal values of buying or selling
    one card (optionally from/to a specific counterparty, which also changes
    *their* count) are what the bot trades on.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from math import comb, prod
from typing import Dict, List, Optional, Sequence, Tuple

from .engine import CONFIGS, DECK_SIZE, GOAL_PAYOUT, NUM_SUITS, POT, QuoteEvent, Trade

_SUITS = range(NUM_SUITS)


def hand_likelihood(hand: Sequence[int]) -> List[float]:
    """P(my hand | deck), up to a constant, for each of the 12 decks."""
    return [float(prod(comb(c.counts[s], hand[s]) for s in _SUITS)) for c in CONFIGS]


@lru_cache(maxsize=500_000)
def suit_constraint_prob(rem: int, mins: Tuple[int, ...], hand_size: int, n_others: int, kitty: int = 0) -> float:
    """P(constrained players hold at least ``mins`` cards of a suit).

    ``rem`` cards of the suit are spread uniformly over the ``n_others *
    hand_size`` unseen slots (the other players' initial hands) plus ``kitty``
    cards nobody was dealt (three players: one).  ``mins`` is a sorted tuple of
    positive lower bounds, one per constrained player; players without a bound
    (and the undealt cards) are pooled.
    """
    k = len(mins)
    if k == 0:
        return 1.0
    if rem < sum(mins):
        return 0.0
    pool = (n_others - k) * hand_size + kitty

    def ways(i: int, left: int) -> int:
        if i == k:
            return comb(pool, left)
        return sum(comb(hand_size, x) * ways(i + 1, left - x) for x in range(mins[i], min(hand_size, left) + 1))

    return ways(0, rem) / comb(n_others * hand_size + kitty, rem)


def posterior(
    hand0: Sequence[int],
    mins: Sequence[Sequence[int]],
    hand_size: int,
    n_others: int,
    extra: Optional[Sequence[float]] = None,
    kitty: int = 0,
) -> List[float]:
    """P(deck config | my initial hand, lower bounds on others' initial holdings).

    ``extra`` optionally multiplies in further per-config likelihoods (e.g.
    from how the other players are quoting); ``kitty`` is the number of cards
    nobody was dealt."""
    w = hand_likelihood(hand0)
    if extra is not None:
        w = [a * b for a, b in zip(w, extra)]
    for i, c in enumerate(CONFIGS):
        if w[i] == 0.0:
            continue
        for s in _SUITS:
            ms = tuple(sorted(m[s] for m in mins if m[s] > 0))
            if ms:
                w[i] *= suit_constraint_prob(c.counts[s] - hand0[s], ms, hand_size, n_others, kitty)
                if w[i] == 0.0:
                    break
    total = sum(w)
    if total <= 0.0:  # cannot happen for consistent observations; fall back to the hand alone
        w = hand_likelihood(hand0)
        total = sum(w)
        if total <= 0.0:  # a hand no deck can produce (only arises in the hand-only lookup tables)
            return [1.0 / len(CONFIGS)] * len(CONFIGS)
    return [x / total for x in w]


def goal_probs(post: Sequence[float]) -> List[float]:
    """Collapse a posterior over decks into P(goal suit = s)."""
    out = [0.0] * NUM_SUITS
    for c, p in zip(CONFIGS, post):
        out[c.goal] += p
    return out


# ----------------------------------------------------------------------------
# Reading other players' quotes
# ----------------------------------------------------------------------------


@lru_cache(maxsize=None)
def compositions(total: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """Every possible hand of ``total`` cards, as per-suit counts."""
    return tuple(
        (a, b, c, total - a - b - c)
        for a in range(total + 1)
        for b in range(total + 1 - a)
        for c in range(total + 1 - a - b)
    )


@lru_cache(maxsize=None)
def naive_goal_table(hand_size: int, n_others: int) -> Tuple[Tuple[float, ...], ...]:
    """P(goal) as seen by a player holding each possible hand (hand-only view)."""
    return tuple(tuple(goal_probs(posterior(a, (), hand_size, n_others))) for a in compositions(hand_size))


@lru_cache(maxsize=64)
def _hand_weights(hand0: Tuple[int, ...], hand_size: int) -> Tuple[Tuple[float, ...], ...]:
    """For each deck: relative probability that an opponent was dealt each
    possible hand, given my hand (multivariate hypergeometric)."""
    out = []
    for c in CONFIGS:
        rem = [c.counts[s] - hand0[s] for s in _SUITS]
        if min(rem) < 0:
            out.append(tuple(0.0 for _ in compositions(hand_size)))
        else:
            out.append(tuple(float(prod(comb(rem[s], a[s]) for s in _SUITS)) for a in compositions(hand_size)))
    return tuple(out)


@dataclass(frozen=True)
class QuoteModel:
    """How much to read into other players' bids and offers.

    Each opponent is modelled as valuing suit ``s`` at ``value_scale * P(goal=s
    | their hand)`` and quoting around that: a bid at ``x`` says their value is
    probably at least ``x``, an offer at ``y`` that it is at most ``y``.  With
    probability ``eps`` a quote is noise.  Summing over every hand they could
    hold turns their latest quotes into a likelihood for each deck, which is
    tempered by ``weight`` (0 disables it) because real opponents are not this
    simple.
    """

    weight: float = 0.5
    value_scale: float = 20.0
    tau: float = 4.0
    eps: float = 0.3


@lru_cache(maxsize=64)
def _nonzero_hand_weights(hand0: Tuple[int, ...], hand_size: int) -> Tuple[Tuple[Tuple[int, float], ...], ...]:
    """:func:`_hand_weights` without the zeros: per deck, (hand index, weight) in index order."""
    return tuple(tuple((j, w) for j, w in enumerate(ws) if w > 0.0) for ws in _hand_weights(hand0, hand_size))


@lru_cache(maxsize=4096)
def _admissible(hand0: Tuple[int, ...], hand_size: int, mins_p: Tuple[int, ...]) -> Tuple[Tuple[Tuple[int, float], ...], ...]:
    """Per deck, the (hand index, weight) pairs of the hands an opponent could hold given
    the lower bounds ``mins_p`` the tape proved, in index order."""
    comps = compositions(hand_size)
    ok = [a[0] >= mins_p[0] and a[1] >= mins_p[1] and a[2] >= mins_p[2] and a[3] >= mins_p[3] for a in comps]
    return tuple(tuple((j, w) for j, w in nz if ok[j]) for nz in _nonzero_hand_weights(hand0, hand_size))


@lru_cache(maxsize=8192)
def _quote_terms(hand_size: int, n_others: int, model: QuoteModel, s: int, is_bid: bool, price: int) -> Tuple[float, ...]:
    """For every hand an opponent could hold, the likelihood factor of one of their quotes
    (suit ``s``, bid or offer, at ``price``), as :func:`quote_likelihood` defines it."""
    scale, tau, eps, keep = model.value_scale, model.tau, model.eps, 1.0 - model.eps
    out = []
    for q in naive_goal_table(hand_size, n_others):
        z = (scale * q[s] - price) / tau if is_bid else (price - scale * q[s]) / tau
        z = max(-30.0, min(30.0, z))
        out.append(eps + keep / (1.0 + math.exp(-z)))
    return tuple(out)


def quote_likelihood(
    hand0: Sequence[int],
    others_mins: Sequence[Sequence[int]],
    others_quotes: Sequence[dict],
    hand_size: int,
    model: QuoteModel,
    cache: Optional[dict] = None,
) -> List[float]:
    """Per-deck likelihood of the other players' latest quotes.

    ``others_quotes[i]`` maps ``(suit, is_bid) -> price`` for the i-th other player.
    ``cache`` (a dict the caller keeps) remembers each player's factor, so a player whose
    bounds and quotes have not changed since the last call costs nothing; the result is
    the same to the last bit either way.
    """
    out = [1.0] * len(CONFIGS)
    if model.weight <= 0.0:
        return out
    n_hands = len(compositions(hand_size))
    n_others = len(others_mins)
    h0 = tuple(hand0)
    for i, (mins_p, quotes) in enumerate(zip(others_mins, others_quotes)):
        if not quotes:
            continue
        key = None
        if cache is not None:
            key = (tuple(mins_p), tuple(quotes.items()), model)
            hit = cache.get(i)
            if hit is not None and hit[0] == key:
                f = hit[1]
                for ci in range(len(CONFIGS)):
                    out[ci] *= f[ci]
                continue
        # the likelihood of their quotes for every hand they could hold: the factors multiply
        # in quote order, starting from 1.0, exactly as a per-hand loop would
        lik = [1.0] * n_hands
        for (s, is_bid), price in quotes.items():
            lik = [l * t for l, t in zip(lik, _quote_terms(hand_size, n_others, model, s, is_bid, price))]
        f = [1.0] * len(CONFIGS)  # x * 1.0 == x: decks with no admissible hand stay as they are
        for ci, adm in enumerate(_admissible(h0, hand_size, tuple(mins_p))):
            num = den = 0.0
            for j, w in adm:
                den += w
                num += w * lik[j]
            if den > 0.0:
                f[ci] = (num / den) ** model.weight
            out[ci] *= f[ci]
        if cache is not None:
            cache[i] = (key, f)
    return out


# ----------------------------------------------------------------------------
# Smart money: the market's most aggressive prices as votes for the goal suit
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SmartMoneyModel:
    """Read the extremes of what other players will pay / accept.

    Whoever believes in a suit bids it up, and nobody who believes in a suit
    sells it cheap.  So for each suit we keep the highest price any other
    player has bid or paid for it and the lowest price any other player has
    offered or sold it at, and score "this suit is the goal" with piecewise
    linear log-likelihood ratios:

    * top bid above ``bid_mid`` adds ``bid_up`` per $ (a $15 bid is strong
      evidence); below it subtracts ``bid_down`` per $ (weak evidence against);
    * bottom offer below ``offer_mid`` subtracts ``offer_down`` per $ (people
      dump suits they know are dead); above it adds ``offer_up`` per $.

    Each signal is capped at ``cap`` nats and the total is scaled by
    ``weight`` (0 disables the model).  Calibrated on figgie.com's own bots:
    every $10+ bid in a recorded round was on the goal suit, while the dead
    suits changed hands at $1-4.
    """

    weight: float = 1.0
    bid_mid: float = 8.0
    bid_up: float = 0.45
    bid_down: float = 0.08
    offer_mid: float = 5.0
    offer_down: float = 0.35
    offer_up: float = 0.08
    cap: float = 3.0
    # player_cap > 0 switches to one vote per player: each other player's own
    # extremes are scored separately, capped at player_cap nats, and the votes
    # are summed (capped at total_cap).  One bot's spike then counts for less
    # than several bots bidding the same suit up.
    player_cap: float = 0.0
    total_cap: float = 4.0
    # A suit nobody has bid on yet is scored as if its top bid were bid_none
    # (None: no evidence either way).  Needed once bids below bid_mid count
    # against a suit, or an unbid suit would look better than a bid one.
    bid_none: Optional[float] = None
    # Consensus: the lowest of the other players' own top bids on a suit (a
    # player who hasn't bid counts as bid_none).  It is high only when *every*
    # opponent has bid the suit up, which figgie.com's bots all do for the goal
    # and rarely for anything else, and one bluffer can't fake it.  Adds
    # consensus_slope nats per $ above consensus_mid, up to consensus_cap; used
    # only with two or more opponents.
    consensus_slope: float = 0.0
    consensus_mid: float = 5.0
    consensus_cap: float = 4.0


def smart_money_log_lr(top_bid: Optional[int], low_offer: Optional[int], m: SmartMoneyModel) -> float:
    """Log-likelihood ratio that a suit is the goal, from its extreme prices."""
    x = 0.0
    if top_bid is None:
        top_bid = m.bid_none
    if top_bid is not None:
        d = top_bid - m.bid_mid
        x += max(-m.cap, min(m.cap, (m.bid_up if d > 0 else m.bid_down) * d))
    if low_offer is not None:
        d = low_offer - m.offer_mid
        x += max(-m.cap, min(m.cap, (m.offer_up if d > 0 else m.offer_down) * d))
    return x


def consensus_log_lr(top_by: Sequence[Sequence[Optional[int]]], s: int, m: SmartMoneyModel) -> float:
    """Evidence from every other player having bid suit ``s`` up (see SmartMoneyModel)."""
    if m.consensus_slope <= 0.0 or len(top_by) < 2:
        return 0.0
    none = m.bid_none if m.bid_none is not None else 0.0
    low = min(none if tops[s] is None else tops[s] for tops in top_by)
    return min(m.consensus_cap, m.consensus_slope * max(0.0, low - m.consensus_mid))


_PARTNER = (1, 0, 3, 2)  # same-colour suit


def colour_blend(x: Sequence[float], mix: float) -> List[float]:
    """Move each suit's log-evidence ``mix``/2 of the way toward its same-colour
    partner's: at ``mix`` 1 both suits of a colour get their average (evidence
    about the colour only), at 0 nothing changes."""
    if mix <= 0.0:
        return list(x)
    return [x[s] + 0.5 * mix * (x[_PARTNER[s]] - x[s]) for s in _SUITS]


def smart_money_likelihood(
    top_bid: Sequence[Optional[int]],
    low_offer: Sequence[Optional[int]],
    m: SmartMoneyModel,
    top_by: Sequence[Sequence[Optional[int]]] = (),
    colour_mix: float = 0.0,
) -> List[float]:
    """Per-deck likelihood multiplier from the smart-money signals.  ``top_by``
    holds each other player's own top bids (only the consensus term uses it);
    ``colour_mix`` (0-1) reads the top-bid / bottom-offer evidence as evidence
    about the suit's colour rather than the suit (see :func:`colour_blend`)."""
    if m.weight <= 0.0:
        return [1.0] * len(CONFIGS)
    x = colour_blend([m.weight * smart_money_log_lr(top_bid[s], low_offer[s], m) for s in _SUITS], colour_mix)
    by_goal = [math.exp(x[s] + consensus_log_lr(top_by, s, m)) for s in _SUITS]
    return [by_goal[c.goal] for c in CONFIGS]


def smart_money_votes_likelihood(
    top_by: Sequence[Sequence[Optional[int]]], low_by: Sequence[Sequence[Optional[int]]], m: SmartMoneyModel
) -> List[float]:
    """One vote per player: ``top_by[i][s]`` / ``low_by[i][s]`` are the i-th
    other player's highest bid-or-paid and lowest offer-or-sold price for suit s."""
    if m.weight <= 0.0:
        return [1.0] * len(CONFIGS)
    by_goal = []
    for s in _SUITS:
        x = 0.0
        for tops, lows in zip(top_by, low_by):
            x += max(-m.player_cap, min(m.player_cap, smart_money_log_lr(tops[s], lows[s], m)))
        by_goal.append(math.exp(m.weight * max(-m.total_cap, min(m.total_cap, x))))
    return [by_goal[c.goal] for c in CONFIGS]


@lru_cache(maxsize=200_000)
def _splits(rem: int, mins: Tuple[int, ...], hand_size: int, kitty: int = 0) -> Tuple[Tuple[Tuple[int, ...], float, int], ...]:
    """All ways ``rem`` unseen cards of a suit can sit in the other players'
    initial hands (one entry per player, seat order) respecting ``mins``, and
    among the ``kitty`` cards nobody was dealt, with normalised
    multivariate-hypergeometric weights: ``(split, probability, undealt)``."""
    n = len(mins)
    out = []

    def rec(i: int, left: int, cur: Tuple[int, ...], w: int) -> None:
        if not kitty and i == n - 1:
            if mins[i] <= left <= hand_size:
                out.append((cur + (left,), w * comb(hand_size, left), 0))
            return
        if i == n:
            if left <= kitty:
                out.append((cur, w * comb(kitty, left), left))
            return
        for x in range(mins[i], min(hand_size, left) + 1):
            rec(i + 1, left - x, cur + (x,), w * comb(hand_size, x))

    rec(0, rem, (), 1)
    total = sum(w for _, w, _ in out)
    return tuple((x, w / total, kx) for x, w, kx in out) if total else ()


@dataclass
class Valuation:
    """Marginal values (in $) of cards, from one player's point of view."""

    p_goal: List[float]  # P(suit is the goal suit)
    buy: List[float]  # value of acquiring one more card, counterparty unknown
    sell: List[float]  # value given up by parting with one card (0 if none held)
    buy_from: List[List[float]]  # [suit][other-player slot]: buy from that player
    sell_to: List[List[float]]  # [suit][other-player slot]: sell to that player
    expected: float  # expected payout of current holdings (goal cards + bonus share)


def value_cards(
    post: Sequence[float],
    hand0: Sequence[int],
    hand_now: Sequence[int],
    mins: Sequence[Sequence[int]],
    nets: Sequence[Sequence[int]],
    hand_size: int,
    alpha: Optional[float] = None,
    consolidate: float = 0.0,
    consolidate_at: float = 0.0,
    kitty: int = 0,
    pot: int = 200,
) -> Valuation:
    """Value one card of each suit.

    ``mins[i]`` / ``nets[i]`` are, for the i-th other player, lower bounds on
    their initial holding and their net cards bought (+) / sold (-) per suit.
    ``alpha`` is the bonus-contest sharpness (``None`` = exact rule).
    ``consolidate`` (0-1) blends in the outcome where every goal card we don't
    hold ends up with one rival, as aggressive bonus-chasers make happen: then
    5 of a 10-card goal suit is a tie and the 6th card is worth half the bonus.
    ``consolidate_at`` (0-1) applies that blend only once we hold at least this
    share of the goal suit (0.5: half, where it decides between a tie and a
    win); smaller holdings are valued from the current spread alone.
    ``kitty`` cards were dealt to nobody (three players: one) and ``pot`` is
    the sum of the antes; with cards left out, the bonus (the pot left after
    $10 per *held* goal card) depends on how many goal cards are among them.
    """
    n = len(mins)
    if alpha is None:

        def base_share(k: int, ys: List[int]) -> float:
            m = max(ys)
            if k > m:
                return 1.0
            if k < m:
                return 0.0
            return 1.0 / (1 + ys.count(m))

    else:
        pw = [float(v) ** alpha for v in range(64)]

        def base_share(k: int, ys: List[int]) -> float:
            a = pw[k]
            if a == 0.0:
                return 0.0
            d = a
            for v in ys:
                d += pw[v]
            return a / d

    if consolidate > 0.0:

        def blended(k: int, ys: List[int]) -> float:
            return (1.0 - consolidate) * base_share(k, ys) + consolidate * base_share(k, [sum(ys)])

    else:
        blended = base_share

    p_goal = [0.0] * NUM_SUITS
    buy = [0.0] * NUM_SUITS
    sell = [0.0] * NUM_SUITS
    buy_from = [[0.0] * n for _ in _SUITS]
    sell_to = [[0.0] * n for _ in _SUITS]
    expected = 0.0

    # Decks with the same goal and the same number of goal cards (the two where the goal has 10)
    # need the same contest sums: compute them once.  Same operations, same results.
    memo: Dict[Tuple[int, int], Optional[tuple]] = {}
    for c, pc in zip(CONFIGS, post):
        if pc < 1e-12:
            continue
        g = c.goal
        k = hand_now[g]
        key = (g, c.counts[g])
        if key in memo:
            sums = memo[key]
        else:
            sums = memo[key] = _contest_sums(c, g, k, hand0, mins, nets, hand_size, kitty, pot, n, blended, base_share, consolidate_at)
        if sums is None:
            continue
        e0, eb, es, d_bf, w_bf, d_st = sums
        bonus = 1.0 if kitty else c.bonus  # with cards left out the bonus is already in the weights
        p_goal[g] += pc
        expected += pc * (GOAL_PAYOUT * k + bonus * e0)
        buy[g] += pc * (GOAL_PAYOUT + bonus * (eb - e0))
        if k > 0:
            sell[g] += pc * (GOAL_PAYOUT + bonus * (e0 - es))
        for i in range(n):
            if w_bf[i] > 0.0:
                buy_from[g][i] += pc * (GOAL_PAYOUT + bonus * d_bf[i] / w_bf[i])
            if k > 0:
                sell_to[g][i] += pc * (GOAL_PAYOUT + bonus * d_st[i])
    return Valuation(p_goal, buy, sell, buy_from, sell_to, expected)


def _contest_sums(c, g, k, hand0, mins, nets, hand_size, kitty, pot, n, blended, base_share, consolidate_at):
    """For one deck: the expected bonus share now (e0), after buying a card (eb, and per seller
    d_bf / w_bf) and after selling one (es, and per buyer d_st), over every way the goal cards
    we can't see could be split (see value_cards).  None if no split fits."""
    share = blended if k >= consolidate_at * c.counts[g] else base_share
    splits = _splits(c.counts[g] - hand0[g], tuple(m[g] for m in mins), hand_size, kitty)
    if not splits:
        return None
    net_g = [nt[g] for nt in nets]
    e0 = eb = es = 0.0
    d_bf = [0.0] * n
    w_bf = [0.0] * n
    d_st = [0.0] * n
    for x, wp, kx in splits:
        # with cards left out, weight each split by its own bonus
        w = wp * (pot - GOAL_PAYOUT * (c.counts[g] - kx)) if kitty else wp
        ys = [x[i] + net_g[i] for i in range(n)]
        s0 = share(k, ys)
        e0 += w * s0
        held = sum(ys)
        if held > 0:  # buying one: the seller is someone holding the suit
            acc = 0.0
            for i in range(n):
                yi = ys[i]
                if yi > 0:
                    ys[i] = yi - 1
                    sb = share(k + 1, ys)
                    ys[i] = yi
                    acc += yi * sb
                    d_bf[i] += w * (sb - s0)
                    w_bf[i] += wp
            eb += w * acc / held
        else:
            eb += w * s0
        if k > 0:  # selling one: the buyer could be anyone
            acc = 0.0
            for i in range(n):
                ys[i] += 1
                ss = share(k - 1, ys)
                ys[i] -= 1
                acc += ss
                d_st[i] += w * (s0 - ss)
            es += w * acc / n
    return e0, eb, es, d_bf, w_bf, d_st


class Beliefs:
    """Everything one seat can infer from its hand and the public tape."""

    def __init__(self, me: int, n_players: int, hand: Sequence[int], hand_size: int) -> None:
        self.me = me
        self.hand_size = hand_size
        self.kitty = max(0, DECK_SIZE - hand_size * n_players)  # cards dealt to nobody (3 players: 1)
        self.pot = (POT // n_players) * n_players  # the antes (3 players: $198)
        self.hand0 = tuple(hand)
        self.others = tuple(p for p in range(n_players) if p != me)
        self.slot = {p: i for i, p in enumerate(self.others)}
        self.net = [[0] * NUM_SUITS for _ in range(n_players)]  # bought - sold, per player per suit
        self.mins = [[0] * NUM_SUITS for _ in range(n_players)]  # lower bounds on initial holdings
        # latest quote (or trade price) per other player: (suit, is_bid) -> price
        self.quotes: Dict[int, Dict[Tuple[int, bool], int]] = {p: {} for p in self.others}
        self._quote_lik: Optional[List[float]] = None
        self._quote_cache: dict = {}  # per-player quote-reading factors (see quote_likelihood)
        # smart money: most aggressive prices other players have shown, per suit
        # (pooled over players, and per player for one-vote-per-player scoring)
        self.top_bid: List[Optional[int]] = [None] * NUM_SUITS
        self.low_offer: List[Optional[int]] = [None] * NUM_SUITS
        self.top_by: Dict[int, List[Optional[int]]] = {p: [None] * NUM_SUITS for p in self.others}
        self.low_by: Dict[int, List[Optional[int]]] = {p: [None] * NUM_SUITS for p in self.others}
        self.smart: Optional[SmartMoneyModel] = None
        self.smart_colour_mix = 0.0  # 0-1: read top bids / bottom offers as colour evidence (see colour_blend)
        # optional outside knowledge: a likelihood multiplier per deck (used by simulator opponents)
        self.prior: Optional[List[float]] = None
        # how much to assume the goal cards we don't hold end up with one rival, and from what
        # share of the goal suit held on (see value_cards)
        self.consolidate = 0.0
        self.consolidate_at = 0.0
        self._state = 0  # bumps on anything that changes valuations
        self._mins_state = 0  # bumps when a lower bound rises or quote-reading is refreshed
        self._post: Optional[List[float]] = None
        self._post_key = -1
        self._val: Optional[Valuation] = None
        self._val_key: Optional[tuple] = None

    @property
    def hand(self) -> Tuple[int, ...]:
        return tuple(self.hand0[s] + self.net[self.me][s] for s in _SUITS)

    def observe_trade(self, t: Trade) -> None:
        self.net[t.buyer][t.suit] += 1
        self.net[t.seller][t.suit] -= 1
        if t.seller != self.me:
            # holding = initial + net >= 0 at all times
            self._raise_min(t.seller, t.suit, -self.net[t.seller][t.suit])
            self.quotes[t.seller][(t.suit, False)] = t.price  # accepted t.price to sell
            self._note_offer(t.suit, t.price, t.seller)
        if t.buyer != self.me:
            self.quotes[t.buyer][(t.suit, True)] = t.price  # paid t.price to buy
            self._note_bid(t.suit, t.price, t.buyer)
        self._state += 1

    def observe_quote(self, ev: QuoteEvent) -> bool:
        """Record a new bid/offer.  Returns True if it changed what we believe."""
        if ev.player == self.me:
            return False
        self.quotes[ev.player][(ev.suit, ev.is_bid)] = ev.price
        if ev.is_bid:
            return self._note_bid(ev.suit, ev.price, ev.player)
        moved = self._note_offer(ev.suit, ev.price, ev.player)
        return self.observe_offer(ev.player, ev.suit) or moved

    def _note_bid(self, s: int, price: int, p: int) -> bool:
        moved = False
        if self.top_bid[s] is None or price > self.top_bid[s]:
            self.top_bid[s] = price
            moved = True
        mine = self.top_by[p]
        if mine[s] is None or price > mine[s]:
            mine[s] = price
            moved = True
        return self._smart_moved(moved)

    def _note_offer(self, s: int, price: int, p: int) -> bool:
        moved = False
        if self.low_offer[s] is None or price < self.low_offer[s]:
            self.low_offer[s] = price
            moved = True
        mine = self.low_by[p]
        if mine[s] is None or price < mine[s]:
            mine[s] = price
            moved = True
        return self._smart_moved(moved)

    def _smart_moved(self, moved: bool) -> bool:
        if moved and self.smart is not None and self.smart.weight > 0.0:
            self._mins_state += 1
            self._state += 1
            return True
        return False

    def refresh_quote_reading(self, model: QuoteModel) -> None:
        """Re-score the other players' latest quotes (moderately expensive: call periodically)."""
        self._quote_lik = quote_likelihood(
            self.hand0,
            [self.mins[p] for p in self.others],
            [self.quotes[p] for p in self.others],
            self.hand_size,
            model,
            self._quote_cache,
        )
        self._mins_state += 1
        self._state += 1

    def observe_offer(self, player: int, suit: int) -> bool:
        """A resting offer proves the player holds the suit right now."""
        if player != self.me and self._raise_min(player, suit, 1 - self.net[player][suit]):
            self._state += 1
            return True
        return False

    def _raise_min(self, p: int, s: int, need: int) -> bool:
        if need > self.mins[p][s]:
            self.mins[p][s] = need
            self._mins_state += 1
            return True
        return False

    def known_counts(self) -> List[int]:
        """Cards per suit proven to exist: my hand plus others' proven holdings."""
        return [self.hand0[s] + sum(self.mins[p][s] for p in self.others) for s in _SUITS]

    def posterior(self) -> List[float]:
        if self._post is None or self._post_key != self._mins_state:
            extra = self._quote_lik
            if self.smart is not None and self.smart.weight > 0.0:
                if self.smart.player_cap > 0.0:
                    sm = smart_money_votes_likelihood(
                        [self.top_by[p] for p in self.others], [self.low_by[p] for p in self.others], self.smart
                    )
                else:
                    sm = smart_money_likelihood(
                        self.top_bid,
                        self.low_offer,
                        self.smart,
                        [self.top_by[p] for p in self.others],
                        self.smart_colour_mix,
                    )
                extra = sm if extra is None else [a * b for a, b in zip(extra, sm)]
            if self.prior is not None:
                extra = list(self.prior) if extra is None else [a * b for a, b in zip(extra, self.prior)]
            self._post = posterior(
                self.hand0, [self.mins[p] for p in self.others], self.hand_size, len(self.others), extra, self.kitty
            )
            self._post_key = self._mins_state
        return self._post

    def set_smart_colour_mix(self, mix: float) -> None:
        """Change how much the top-bid / bottom-offer evidence is read as colour evidence (0-1)."""
        if mix != self.smart_colour_mix:
            self.smart_colour_mix = mix
            self._mins_state += 1
            self._state += 1

    def p_goal(self) -> List[float]:
        return goal_probs(self.posterior())

    def valuation(self, alpha: Optional[float] = None) -> Valuation:
        key = (self._state, self._mins_state, alpha, self.consolidate, self.consolidate_at)
        if self._val is None or self._val_key != key:
            self._val = value_cards(
                self.posterior(),
                self.hand0,
                self.hand,
                [self.mins[p] for p in self.others],
                [self.net[p] for p in self.others],
                self.hand_size,
                alpha,
                self.consolidate,
                self.consolidate_at,
                self.kitty,
                self.pot,
            )
            self._val_key = key
        return self._val
