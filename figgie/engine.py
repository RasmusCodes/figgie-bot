"""Figgie game engine.

Implements Jane Street's Figgie in discrete time:

* 40-card deck in four suits: one suit has 12 cards, one has 8 and two have 10.
  All 12 (12-card suit, 8-card suit) assignments are equally likely.
* The *goal suit* is the suit of the same colour as the 12-card suit
  (spades <-> clubs, hearts <-> diamonds), so it has either 8 or 10 cards.
* Four players get 10 cards each (five players: 8 each).  Everyone antes so
  the pot is $200 ($50 each with four players, $40 each with five).  The
  official game is for four or five; this engine also deals two players 20
  cards each ($100 antes) and three players 13 each, with the 40th card left
  face down for nobody ($66 antes, a $198 pot).
* Trading: any player may bid for or offer a single card of any suit.  Each
  suit has at most one resting bid and one resting offer; a new bid must be
  higher than the resting bid (a new offer lower than the resting offer).
  Hitting a bid / lifting an offer trades one card at the resting price, and
  **after every trade all resting bids and offers are cleared**.  You can only
  sell cards you hold and only bid up to the cash you have.
* When time is up every goal-suit card held pays $10 from the pot and the
  rest of the pot ($100 or $120, plus $10 for a goal card nobody was dealt)
  goes to whoever holds the most goal-suit cards (split evenly on ties).

Time is modelled as ``Rules.ticks`` rounds.  Every round each bot gets one
turn, in a freshly shuffled order, during which it may read the market and
send up to ``Rules.max_ops_per_turn`` orders through its :class:`Market`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, NamedTuple, Optional, Sequence, Tuple, Union

SUITS = ("spades", "clubs", "hearts", "diamonds")
SUIT_CHARS = "SCHD"
NUM_SUITS = 4
PARTNER = (1, 0, 3, 2)  # same-colour suit: spades<->clubs, hearts<->diamonds
DECK_SIZE = 40
POT = 200
GOAL_PAYOUT = 10


class DeckConfig(NamedTuple):
    """One of the 12 equally likely decks."""

    twelve: int  # suit with 12 cards
    eight: int  # suit with 8 cards
    counts: Tuple[int, int, int, int]
    goal: int  # same colour as the 12-card suit
    bonus: int  # pot left for the majority holder(s) after paying $10 per goal card

    def describe(self) -> str:
        return (
            f"goal {SUITS[self.goal]} ({self.counts[self.goal]} cards, bonus ${self.bonus}); "
            f"12-card suit {SUITS[self.twelve]}, 8-card suit {SUITS[self.eight]}"
        )


def _make_config(twelve: int, eight: int) -> DeckConfig:
    counts = tuple(12 if s == twelve else 8 if s == eight else 10 for s in range(NUM_SUITS))
    goal = PARTNER[twelve]
    return DeckConfig(twelve, eight, counts, goal, POT - GOAL_PAYOUT * counts[goal])


CONFIGS: Tuple[DeckConfig, ...] = tuple(
    _make_config(t, e) for t in range(NUM_SUITS) for e in range(NUM_SUITS) if e != t
)


@dataclass(frozen=True)
class Rules:
    n_players: int = 4
    ticks: int = 240  # length of the trading period (think: 4 minutes at 1 tick/second)
    starting_cash: int = 350
    clear_on_trade: bool = True  # official rule: any trade wipes every resting order
    max_ops_per_turn: int = 20

    def __post_init__(self) -> None:
        if not 2 <= self.n_players <= 5:
            raise ValueError("this engine deals 2 to 5 players (the official game: 4 or 5)")
        if self.ticks < 1:
            raise ValueError("ticks must be positive")

    @property
    def hand_size(self) -> int:
        return DECK_SIZE // self.n_players

    @property
    def kitty(self) -> int:
        """Cards dealt to nobody (three players: one)."""
        return DECK_SIZE - self.hand_size * self.n_players

    @property
    def ante(self) -> int:
        return POT // self.n_players

    @property
    def pot(self) -> int:
        return self.ante * self.n_players


class Quote(NamedTuple):
    price: int
    player: int


class Trade(NamedTuple):
    tick: int
    suit: int
    price: int
    buyer: int
    seller: int
    aggressor: int  # the player who crossed the spread


class QuoteEvent(NamedTuple):
    tick: int
    suit: int
    is_bid: bool
    price: int
    player: int


class GameInfo(NamedTuple):
    player: int  # your seat
    hand: Tuple[int, ...]  # your cards per suit (S, C, H, D)
    rules: Rules
    names: Tuple[str, ...]  # bot name per seat
    seed: int  # private seed for the bot's own randomness


@dataclass
class GameResult:
    seed: int
    config: DeckConfig
    names: Tuple[str, ...]
    initial_hands: List[Tuple[int, ...]]
    final_hands: List[Tuple[int, ...]]
    trades: List[Trade]
    goal_counts: List[int]
    bonus_winners: List[int]
    pnl: List[float]  # final wealth minus starting cash; sums to zero


class Bot:
    """Base class for Figgie bots.  Override whichever hooks you need.

    ``on_quote`` and ``on_trade`` are broadcast to every bot as soon as the
    event happens, possibly while another bot (or this one) is mid-turn, so
    keep them cheap: update bookkeeping and do the thinking in ``act``.
    """

    name = "bot"

    def on_start(self, info: GameInfo) -> None:
        pass

    def act(self, market: "Market") -> None:
        pass

    def on_quote(self, event: QuoteEvent) -> None:
        pass

    def on_trade(self, trade: Trade) -> None:
        pass

    def on_end(self, result: GameResult) -> None:
        pass


OrderResult = Union[Trade, bool]


class Market:
    """A bot's handle on the exchange, valid only during that bot's turn.

    Order methods return the :class:`Trade` if the order traded, ``True`` if it
    was accepted and is now resting (or was cancelled), ``False`` if rejected.
    """

    __slots__ = ("_game", "me", "_ops", "_live")

    def __init__(self, game: "Game", player: int) -> None:
        self._game = game
        self.me = player
        self._ops = 0
        self._live = True

    # ----- state ---------------------------------------------------------------
    @property
    def tick(self) -> int:
        return self._game.tick

    @property
    def ticks_left(self) -> int:
        return self._game.rules.ticks - self._game.tick

    @property
    def rules(self) -> Rules:
        return self._game.rules

    @property
    def hand(self) -> Tuple[int, ...]:
        return tuple(self._game.hands[self.me])

    @property
    def cash(self) -> int:
        return self._game.cash[self.me]

    @property
    def ops_left(self) -> int:
        return self._game.rules.max_ops_per_turn - self._ops

    def best_bid(self, suit: int) -> Optional[Quote]:
        return self._game.bids[suit]

    def best_offer(self, suit: int) -> Optional[Quote]:
        return self._game.offers[suit]

    def card_counts(self) -> Tuple[int, ...]:
        """Number of cards each player holds (public: it follows from the trades)."""
        return tuple(sum(h) for h in self._game.hands)

    @property
    def trades(self) -> Tuple[Trade, ...]:
        return tuple(self._game.trades)

    # ----- orders --------------------------------------------------------------
    def bid(self, suit: int, price: int) -> OrderResult:
        """Bid for one card.  Trades immediately if it reaches the resting offer."""
        return self._send(self._game._bid, suit, price)

    def offer(self, suit: int, price: int) -> OrderResult:
        """Offer one card.  Trades immediately if it reaches the resting bid."""
        return self._send(self._game._offer, suit, price)

    def buy(self, suit: int, max_price: Optional[int] = None) -> OrderResult:
        """Lift the resting offer (only if it is at most ``max_price``)."""
        return self._send(self._game._buy, suit, max_price)

    def sell(self, suit: int, min_price: Optional[int] = None) -> OrderResult:
        """Hit the resting bid (only if it is at least ``min_price``)."""
        return self._send(self._game._sell, suit, min_price)

    def cancel_bid(self, suit: int) -> OrderResult:
        return self._send(self._game._cancel, suit, True)

    def cancel_offer(self, suit: int) -> OrderResult:
        return self._send(self._game._cancel, suit, False)

    def _send(self, fn, *args) -> OrderResult:
        if not self._live:
            raise RuntimeError("Market handle used outside of the bot's own turn")
        if self._ops >= self._game.rules.max_ops_per_turn:
            return False
        self._ops += 1
        return fn(self.me, *args)


def _is_int(x) -> bool:
    return type(x) is int  # excludes bool and floats


class Game:
    """One round of Figgie.  ``Game(bots, seed=...).run()`` returns a :class:`GameResult`."""

    def __init__(
        self,
        bots: Sequence[Bot],
        rules: Optional[Rules] = None,
        seed: Optional[int] = None,
        config: Optional[DeckConfig] = None,
        hands: Optional[Sequence[Sequence[int]]] = None,
        observers: Sequence[object] = (),
    ) -> None:
        self.rules = rules or Rules()
        n = self.rules.n_players
        if len(bots) != n:
            raise ValueError(f"need exactly {n} bots, got {len(bots)}")
        self.bots = list(bots)
        self.seed = random.randrange(2**63) if seed is None else seed
        self.rng = random.Random(self.seed)
        self.config = config if config is not None else self.rng.choice(CONFIGS)
        H = self.rules.hand_size
        self.kitty = [0] * NUM_SUITS  # cards dealt to nobody (three players: one)
        if hands is None:
            deck = [s for s in range(NUM_SUITS) for _ in range(self.config.counts[s])]
            self.rng.shuffle(deck)
            self.hands = [[0] * NUM_SUITS for _ in range(n)]
            for i, s in enumerate(deck):
                if i < H * n:
                    self.hands[i // H][s] += 1
                else:
                    self.kitty[s] += 1
        else:
            self.hands = [list(h) for h in hands]
            if len(self.hands) != n or any(sum(h) != H or len(h) != NUM_SUITS for h in self.hands):
                raise ValueError("bad hands")
            self.kitty = [self.config.counts[s] - sum(h[s] for h in self.hands) for s in range(NUM_SUITS)]
            if min(self.kitty) < 0 or sum(self.kitty) != self.rules.kitty:
                raise ValueError("hands do not match the deck configuration")
        self.initial_hands = [tuple(h) for h in self.hands]
        self.cash = [self.rules.starting_cash - self.rules.ante] * n
        self.bids: List[Optional[Quote]] = [None] * NUM_SUITS
        self.offers: List[Optional[Quote]] = [None] * NUM_SUITS
        self.trades: List[Trade] = []
        self.tick = 0
        self.names = tuple(getattr(b, "name", type(b).__name__) for b in self.bots)
        self.observers = list(observers)
        self._order = list(range(n))
        self._began = False
        self._result: Optional[GameResult] = None

    # ----- main loop -----------------------------------------------------------
    def run(self) -> GameResult:
        """Play the whole game as fast as possible."""
        self.begin()
        while self.step():
            pass
        return self.finish()

    def begin(self) -> None:
        """Show every bot its hand and open trading."""
        if self._began:
            raise RuntimeError("a Game can only be run once")
        self._began = True
        for p, bot in enumerate(self.bots):
            bot.on_start(GameInfo(p, tuple(self.hands[p]), self.rules, self.names, self.rng.randrange(2**63)))
        for bot in self.bots:
            if getattr(bot, "oracle", False):  # simulator-only test opponents that may see the deck
                bot.on_oracle(self.config)
        self._notify("on_start", self)

    @property
    def trading_open(self) -> bool:
        return self._began and self._result is None and self.tick < self.rules.ticks

    def step(self) -> bool:
        """Play one tick (every bot gets one turn).  Returns True while trading continues."""
        if not self.trading_open:
            return False
        self.rng.shuffle(self._order)
        for p in self._order:
            market = Market(self, p)
            try:
                self.bots[p].act(market)
            finally:
                market._live = False
        self._notify("on_tick", self)
        self.tick += 1
        return self.tick < self.rules.ticks

    def finish(self) -> GameResult:
        """Close trading, pay out the pot and tell the bots."""
        if self._result is None:
            self.tick = self.rules.ticks
            self._result = self._settle()
            for bot in self.bots:
                bot.on_end(self._result)
            self._notify("on_end", self, self._result)
        return self._result

    def order(self, player: int, kind: str, suit: int, price: Optional[int] = None) -> OrderResult:
        """Send an order for ``player`` from outside the bot-turn loop (e.g. a
        human seat in the web UI).  ``kind`` is bid / offer / buy / sell /
        cancel_bid / cancel_offer; ``price`` is the limit (for buy/sell: the
        worst price you will accept, or None)."""
        if not self.trading_open:
            return False
        if kind == "bid":
            return self._bid(player, suit, price)
        if kind == "offer":
            return self._offer(player, suit, price)
        if kind == "buy":
            return self._buy(player, suit, price)
        if kind == "sell":
            return self._sell(player, suit, price)
        if kind == "cancel_bid":
            return self._cancel(player, suit, True)
        if kind == "cancel_offer":
            return self._cancel(player, suit, False)
        raise ValueError(f"unknown order kind {kind!r}")

    def _settle(self) -> GameResult:
        goal = self.config.goal
        goal_counts = [h[goal] for h in self.hands]
        top = max(goal_counts)
        winners = [p for p, c in enumerate(goal_counts) if c == top]
        # the pot left after $10 per goal card held (config.bonus when every card is dealt)
        share = (self.rules.pot - GOAL_PAYOUT * sum(goal_counts)) / len(winners)
        pnl = []
        for p in range(self.rules.n_players):
            wealth = self.cash[p] + GOAL_PAYOUT * goal_counts[p] + (share if p in winners else 0.0)
            pnl.append(wealth - self.rules.starting_cash)
        return GameResult(
            seed=self.seed,
            config=self.config,
            names=self.names,
            initial_hands=list(self.initial_hands),
            final_hands=[tuple(h) for h in self.hands],
            trades=list(self.trades),
            goal_counts=goal_counts,
            bonus_winners=winners,
            pnl=pnl,
        )

    def _notify(self, hook: str, *args) -> None:
        for obs in self.observers:
            fn = getattr(obs, hook, None)
            if fn is not None:
                fn(*args)

    # ----- order handling ------------------------------------------------------
    def _bid(self, p: int, suit: int, price: int) -> OrderResult:
        if not (_is_int(suit) and 0 <= suit < NUM_SUITS and _is_int(price) and price >= 1):
            return False
        if price > self.cash[p]:
            return False
        off = self.offers[suit]
        if off is not None and price >= off.price:
            if off.player == p:
                return False
            return self._execute(suit, off.price, buyer=p, seller=off.player, aggressor=p)
        cur = self.bids[suit]
        if cur is not None and price <= cur.price:
            return False
        self.bids[suit] = Quote(price, p)
        self._quote_event(suit, True, price, p)
        return True

    def _offer(self, p: int, suit: int, price: int) -> OrderResult:
        if not (_is_int(suit) and 0 <= suit < NUM_SUITS and _is_int(price) and price >= 1):
            return False
        if self.hands[p][suit] <= 0:
            return False
        bid = self.bids[suit]
        if bid is not None and price <= bid.price:
            if bid.player == p:
                return False
            return self._execute(suit, bid.price, buyer=bid.player, seller=p, aggressor=p)
        cur = self.offers[suit]
        if cur is not None and price >= cur.price:
            return False
        self.offers[suit] = Quote(price, p)
        self._quote_event(suit, False, price, p)
        return True

    def _buy(self, p: int, suit: int, max_price: Optional[int]) -> OrderResult:
        if not (_is_int(suit) and 0 <= suit < NUM_SUITS):
            return False
        off = self.offers[suit]
        if off is None or off.player == p:
            return False
        if max_price is not None and off.price > max_price:
            return False
        if off.price > self.cash[p]:
            return False
        return self._execute(suit, off.price, buyer=p, seller=off.player, aggressor=p)

    def _sell(self, p: int, suit: int, min_price: Optional[int]) -> OrderResult:
        if not (_is_int(suit) and 0 <= suit < NUM_SUITS):
            return False
        if self.hands[p][suit] <= 0:
            return False
        bid = self.bids[suit]
        if bid is None or bid.player == p:
            return False
        if min_price is not None and bid.price < min_price:
            return False
        return self._execute(suit, bid.price, buyer=bid.player, seller=p, aggressor=p)

    def _cancel(self, p: int, suit: int, is_bid: bool) -> OrderResult:
        if not (_is_int(suit) and 0 <= suit < NUM_SUITS):
            return False
        book = self.bids if is_bid else self.offers
        q = book[suit]
        if q is None or q.player != p:
            return False
        book[suit] = None
        return True

    def _execute(self, suit: int, price: int, buyer: int, seller: int, aggressor: int) -> OrderResult:
        if self.hands[seller][suit] <= 0 or self.cash[buyer] < price:
            return False  # unreachable while resting orders stay backed; defensive
        self.cash[buyer] -= price
        self.cash[seller] += price
        self.hands[buyer][suit] += 1
        self.hands[seller][suit] -= 1
        trade = Trade(self.tick, suit, price, buyer, seller, aggressor)
        self.trades.append(trade)
        if self.rules.clear_on_trade:
            self.bids = [None] * NUM_SUITS
            self.offers = [None] * NUM_SUITS
        else:
            if aggressor == buyer:
                self.offers[suit] = None
            else:
                self.bids[suit] = None
            if self.hands[seller][suit] == 0 and self.offers[suit] is not None and self.offers[suit].player == seller:
                self.offers[suit] = None
            for s in range(NUM_SUITS):
                b = self.bids[s]
                if b is not None and b.player == buyer and b.price > self.cash[buyer]:
                    self.bids[s] = None
        for bot in self.bots:
            bot.on_trade(trade)
        self._notify("on_trade", self, trade)
        return trade

    def _quote_event(self, suit: int, is_bid: bool, price: int, player: int) -> None:
        ev = QuoteEvent(self.tick, suit, is_bid, price, player)
        for bot in self.bots:
            bot.on_quote(ev)
        self._notify("on_quote", self, ev)
