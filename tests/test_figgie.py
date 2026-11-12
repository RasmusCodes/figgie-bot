"""Unit tests:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from figgie.engine import CONFIGS, Bot, Game, GameInfo, Market, Quote, QuoteEvent, Rules, Trade  # noqa: E402
from figgie.model import (  # noqa: E402
    Beliefs,
    SmartMoneyModel,
    goal_probs,
    posterior,
    smart_money_likelihood,
    value_cards,
)
from figgie.patterns import LEARNER_FEATURES, ReadingLearner, ResaleLearner, ResaleTracker  # noqa: E402
from figgie.shark import SharkBot  # noqa: E402
from figgie.tournament import make_bot  # noqa: E402

# CONFIGS[0]: spades has 12 cards, clubs 8, hearts and diamonds 10 -> goal is clubs.
FIXED_HANDS = [[3, 2, 3, 2], [3, 2, 2, 3], [3, 2, 2, 3], [3, 2, 3, 2]]


def lineup():
    return [make_bot(s) for s in ("shark", "hand", "counter", "noise")]


class StaticBook:
    """A frozen order book for driving a bot's act() by hand; every order is refused."""

    def __init__(self, tick, bids, hand=(3, 2, 3, 2), cash=300, me=0):
        self.tick, self._bids, self.hand, self.cash, self.me = tick, list(bids), tuple(hand), cash, me

    def best_bid(self, s):
        return self._bids[s]

    def best_offer(self, s):
        return None

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


class EngineTests(unittest.TestCase):
    def test_settlement_is_zero_sum_and_conserves_cards(self):
        for seed in range(15):
            res = Game(lineup(), seed=seed).run()
            self.assertAlmostEqual(sum(res.pnl), 0.0, places=9)
            for s in range(4):
                self.assertEqual(sum(h[s] for h in res.final_hands), res.config.counts[s])

    def test_two_three_and_five_players(self):
        lineups = {
            2: ("shark", "counter"),
            3: ("shark", "counter", "oracle"),
            5: ("shark", "hand", "counter", "noise", "oracle"),
        }
        for n, names in lineups.items():
            rules = Rules(n_players=n, ticks=60)
            self.assertEqual((rules.hand_size, rules.kitty), {2: (20, 0), 3: (13, 1), 5: (8, 0)}[n])
            for seed in range(4):
                g = Game([make_bot(s) for s in names], rules=rules, seed=seed)
                res = g.run()
                self.assertAlmostEqual(sum(res.pnl), 0.0, places=9, msg=f"{n} players")
                for s in range(4):  # every card is in a hand or (three players) face down
                    self.assertEqual(sum(h[s] for h in res.final_hands) + g.kitty[s], res.config.counts[s])
        with self.assertRaises(ValueError):
            Rules(n_players=6)

    def test_step_api_replays_run_exactly(self):
        a = Game(lineup(), seed=42).run()
        g = Game(lineup(), seed=42)
        g.begin()
        while g.step():
            pass
        b = g.finish()
        self.assertEqual(a.pnl, b.pnl)
        self.assertEqual(a.trades, b.trades)

    def test_order_rules(self):
        g = Game([Bot() for _ in range(4)], config=CONFIGS[0], hands=FIXED_HANDS, seed=1)
        g.begin()
        self.assertTrue(g.order(0, "bid", 2, 5))
        self.assertFalse(g.order(1, "bid", 2, 5), "a new bid must beat the resting bid")
        self.assertTrue(g.order(1, "bid", 2, 6))
        self.assertTrue(g.order(2, "offer", 3, 9))
        self.assertFalse(g.order(3, "offer", 3, 9), "a new offer must undercut the resting offer")
        t = g.order(3, "sell", 2)
        self.assertIsInstance(t, Trade)
        self.assertEqual((t.buyer, t.seller, t.price), (1, 3, 6))
        self.assertTrue(all(q is None for q in g.bids + g.offers), "every quote clears after a trade")
        self.assertTrue(g.order(2, "offer", 3, 9))
        t = g.order(0, "bid", 3, 12)
        self.assertEqual((t.buyer, t.seller, t.price), (0, 2, 9), "a crossing bid trades at the resting price")
        self.assertFalse(g.order(0, "bid", 1, 10_000), "cannot bid more than your cash")

    def test_cannot_offer_a_suit_you_do_not_hold(self):
        hands = [[5, 2, 3, 0], [3, 2, 2, 3], [2, 2, 2, 4], [2, 2, 3, 3]]
        g = Game([Bot() for _ in range(4)], config=CONFIGS[0], hands=hands, seed=1)
        g.begin()
        self.assertFalse(g.order(0, "offer", 3, 5))
        self.assertTrue(g.order(1, "bid", 3, 4))
        self.assertFalse(g.order(0, "sell", 3))

    def test_trading_closes_after_the_last_tick(self):
        g = Game([Bot() for _ in range(4)], rules=Rules(ticks=3), config=CONFIGS[0], hands=FIXED_HANDS, seed=1)
        g.begin()
        while g.step():
            pass
        self.assertFalse(g.order(0, "bid", 2, 5))


class ModelTests(unittest.TestCase):
    def test_posterior_rules_out_impossible_decks(self):
        post = posterior((9, 1, 0, 0), [], 10, 3)
        self.assertAlmostEqual(sum(post), 1.0)
        for c, p in zip(CONFIGS, post):
            if c.counts[0] < 9:
                self.assertEqual(p, 0.0)

    def test_eleven_proven_cards_pin_down_the_twelve_card_suit(self):
        # I hold 5 spades and the tape proves two players held 3 more each: 11 spades exist,
        # so spades is the 12-card suit and clubs must be the goal.
        pg = goal_probs(posterior((5, 2, 2, 1), [[3, 0, 0, 0], [3, 0, 0, 0], [0, 0, 0, 0]], 10, 3))
        self.assertAlmostEqual(pg[1], 1.0)

    def test_long_suit_points_at_its_partner(self):
        pg = goal_probs(posterior((1, 6, 1, 2), [], 10, 3))
        self.assertEqual(max(range(4), key=pg.__getitem__), 0)  # 6 clubs -> spades is the favourite

    def test_a_big_bid_marks_the_goal_suit(self):
        b = Beliefs(0, 4, (3, 2, 3, 2), 10)
        b.smart = SmartMoneyModel()
        before = b.p_goal()[2]
        b.observe_quote(QuoteEvent(5, 2, True, 15, 1))  # someone bids $15 for hearts
        after = b.p_goal()[2]
        self.assertGreater(after, 0.6)
        self.assertGreater(after, before + 0.3)
        b.observe_quote(QuoteEvent(6, 0, False, 1, 2))  # someone dumps spades at $1
        self.assertLess(b.p_goal()[0], 0.1)

    def test_consolidation_prices_the_sixth_goal_card(self):
        # Hearts is surely the goal (10 cards).  We hold 5; the others hold 3, 1 and 1.  Read at
        # face value 5 already wins, but if the strays end up with one rival, 5 only ties.
        ci = next(i for i, c in enumerate(CONFIGS) if c.twelve == 3 and c.eight == 0)
        post = [1.0 if i == ci else 0.0 for i in range(12)]
        mins = [[0, 0, 2, 0], [0, 0, 2, 0], [0, 0, 3, 0]]
        nets = [[0, 0, 1, 0], [0, 0, -1, 0], [0, 0, -2, 0]]
        sixth = {c: value_cards(post, (2, 2, 3, 3), (2, 2, 5, 1), mins, nets, 10, 40.0, c).buy[2] for c in (0.0, 0.5, 1.0)}
        self.assertLess(sixth[0.0], 12)  # little more than the $10 payout
        self.assertAlmostEqual(sixth[1.0], 60, delta=0.5)  # $10 + half the $100 bonus: a tie becomes a win
        self.assertAlmostEqual(sixth[0.5], (sixth[0.0] + sixth[1.0]) / 2, delta=0.01)

    def test_consensus_needs_every_opponent(self):
        m = SmartMoneyModel(weight=1.0, bid_mid=17, bid_up=0.8, bid_down=0.3, cap=10, bid_none=4, consensus_slope=0.8)

        def p_hearts(by_bot):
            top = [max(b[s] for b in by_bot) for s in range(4)]
            lik = smart_money_likelihood(top, [None] * 4, m, by_bot)
            return goal_probs(posterior((3, 2, 3, 2), [], 10, len(by_bot), lik))[2]

        everyone = [[4, 4, 9, 4], [4, 4, 9, 4], [4, 4, 9, 4]]
        one_bot = [[4, 4, 9, 4], [4, 4, 4, 4], [4, 4, 4, 4]]
        self.assertGreater(p_hearts(everyone), p_hearts(one_bot) + 0.3)  # same top bid, very different news
        heads_up = [[4, 4, 9, 4]]
        no_consensus = SmartMoneyModel(weight=1.0, bid_mid=17, bid_up=0.8, bid_down=0.3, cap=10, bid_none=4)
        self.assertEqual(
            smart_money_likelihood([4, 4, 9, 4], [None] * 4, m, heads_up),
            smart_money_likelihood([4, 4, 9, 4], [None] * 4, no_consensus, heads_up),
        )  # one opponent: nothing to agree with

    def test_colour_reading_splits_bid_evidence_within_a_colour(self):
        from figgie.model import colour_blend

        x = [3.0, 0.0, -1.0, 1.0]  # spades strongly bid, clubs (its same-colour partner) not at all
        self.assertEqual(colour_blend(x, 0.0), x)
        self.assertEqual(colour_blend(x, 1.0), [1.5, 1.5, 0.0, 0.0])  # only the colours differ
        half = colour_blend(x, 0.5)
        self.assertAlmostEqual(half[0], 2.25)
        self.assertAlmostEqual(half[1], 0.75)
        # through the likelihood: at full mix a big spade bid no longer favours spades over clubs
        m = SmartMoneyModel(weight=1.0, bid_mid=17.0, bid_up=0.8, bid_down=0.3, cap=10.0, bid_none=4.0)
        lik = smart_money_likelihood([20, None, None, None], [None] * 4, m, (), 1.0)
        by_goal = {c.goal: v for c, v in zip(CONFIGS, lik)}
        self.assertAlmostEqual(by_goal[0], by_goal[1])
        self.assertGreater(by_goal[0], by_goal[2])

    def test_undealt_card_counts_toward_the_bonus(self):
        # Three players, 13 cards each, one card dealt to nobody; hearts surely the goal (10 cards).
        # We hold 6, so nobody can catch us: we get $10 a heart plus the pot left after $10 per held
        # heart, i.e. $198 - $100 + $10 if the undealt card is a heart (4 of the 27 unseen cards are).
        ci = next(i for i, c in enumerate(CONFIGS) if c.twelve == 3 and c.eight == 0)
        post = [1.0 if i == ci else 0.0 for i in range(12)]
        hand = (3, 2, 6, 2)
        v = value_cards(post, hand, hand, [[0] * 4] * 2, [[0] * 4] * 2, 13, None, 0.0, 0.0, 1, 198)
        self.assertAlmostEqual(v.expected, 60 + 98 + 10 * 4 / 27, places=9)
        # Two players: the whole deck is dealt and the bonus is the usual $100.
        hand2 = (6, 4, 6, 4)
        v2 = value_cards(post, hand2, hand2, [[0] * 4], [[0] * 4], 20, None, 0.0, 0.0, 0, 200)
        self.assertAlmostEqual(v2.expected, 60 + 100, places=9)
        # With nothing proven about the other hands, P(goal) from a 3-player hand is a proper distribution.
        self.assertAlmostEqual(sum(goal_probs(posterior(hand, [[0, 0, 4, 0]], 13, 2, None, 1))), 1.0)

    def test_consolidation_waits_until_half_the_suit(self):
        # Hearts surely the goal (10 cards), nothing known about the other hands, mid-round.
        ci = next(i for i, c in enumerate(CONFIGS) if c.twelve == 3 and c.eight == 0)
        post = [1.0 if i == ci else 0.0 for i in range(12)]
        none = [[0, 0, 0, 0]] * 3

        def hearts(hand, c, at):
            v = value_cards(post, hand, hand, none, none, 10, 10.0, c, at)
            return v.sell[2], v.buy[2]

        three, five = (3, 2, 3, 2), (1, 2, 5, 2)
        self.assertEqual(hearts(three, 0.5, 0.5), hearts(three, 0.0, 0.0))  # 3 of 10: priced as without it
        self.assertLess(hearts(three, 0.5, 0.0)[0], hearts(three, 0.0, 0.0)[0] - 10)  # ungated, the 3rd looks cheap
        self.assertEqual(hearts(five, 0.5, 0.5), hearts(five, 0.5, 0.0))  # 5 of 10: the premium applies
        self.assertGreater(hearts(five, 0.5, 0.5)[1], hearts(five, 0.0, 0.0)[1] + 20)  # a 6th is worth chasing


class SharkTests(unittest.TestCase):
    def test_flash_bids_do_not_move_beliefs(self):
        def fresh():
            b = SharkBot(smart_confirm=2)
            b.on_start(GameInfo(0, (3, 2, 3, 2), Rules(n_players=4), ("a", "b", "c", "d"), 0))
            return b

        spoof = QuoteEvent(0, 0, True, 25, 1)  # player 1 bids $25 for spades ...
        standing = [Quote(25, 1), None, None, None]
        empty = [None] * 4

        bot = fresh()
        before = bot.beliefs.p_goal()[0]
        bot.on_quote(spoof)
        bot.act(StaticBook(0, standing))  # ... we see it on one turn ...
        bot.act(StaticBook(1, empty))  # ... and it is gone, with no trade: pulled
        self.assertEqual(bot.beliefs.p_goal()[0], before)
        self.assertEqual(bot._pending, {})

        bot = fresh()
        bot.on_quote(spoof)
        bot.act(StaticBook(0, standing))
        bot.act(StaticBook(1, standing))  # it rests through two of our turns: real
        self.assertGreater(bot.beliefs.p_goal()[0], before + 0.2)

        bot = fresh()
        bot.on_quote(spoof)
        bot.act(StaticBook(0, standing))
        bot.on_trade(Trade(0, 1, 5, 2, 3, 2))  # a trade elsewhere clears the book after we saw it
        self.assertGreater(bot.beliefs.p_goal()[0], before + 0.2)

    def test_churn_guard_refuses_to_dump_below_cost(self):
        g = Game(
            [SharkBot(read_weight=0, smart_weight=0, hold_goal=0, hold_dead=0), Bot(), Bot(), Bot()],
            config=CONFIGS[0],
            hands=FIXED_HANDS,
            seed=3,
        )
        g.begin()
        shark = g.bots[0]
        # Pretend the shark paid $12 for each of its 3 hearts.
        shark.cost[2], shark.bought[2] = 36.0, 3
        v = shark.valuation(0)
        self.assertGreaterEqual(v.p_goal[2], shark.params.churn_p)
        self.assertAlmostEqual(shark.sell_floor(2, v), 0.6 * 12)
        g.order(1, "bid", 2, 3)  # a $3 bid for hearts is below the guard
        shark.act(Market(g, 0))
        self.assertEqual(g.hands[0][2], 3, "the shark must not dump hearts at $3 after paying $12")

    def test_hold_floor_waits_early_and_fades_by_the_bell(self):
        def setup(**params):
            g = Game([SharkBot(read_weight=0, smart_weight=0, **params), Bot(), Bot(), Bot()], config=CONFIGS[0], hands=FIXED_HANDS, seed=3)
            g.begin()
            return g, g.bots[0], g.bots[0].valuation(0)

        _, shark, v = setup(hold_goal=16, hold_dead=3)
        self.assertAlmostEqual(shark.hold_floor(2, v, shark.ticks), v.sell[2])  # no premium left at the bell
        self.assertGreater(shark.hold_floor(2, v, 0), v.sell[2] + 1)  # a real premium at the open
        # The cheapest bid the old logic would hit at the open ...
        g, _, v = setup(hold_goal=0, hold_dead=0)
        price = math.ceil(v.sell_to[2][0] * 1.2 + 1.0)
        g.order(1, "bid", 2, price)
        g.bots[0].act(Market(g, 0))
        self.assertEqual(g.hands[0][2], 2, "without the hold floor it sells a heart")
        # ... is refused once waiting is priced in.
        g, _, _ = setup(hold_goal=16, hold_dead=3)
        g.order(1, "bid", 2, price)
        g.bots[0].act(Market(g, 0))
        self.assertEqual(g.hands[0][2], 3, "with the hold floor it keeps the heart")

    def test_early_offers_price_in_who_lifts_them(self):
        class Offers(StaticBook):  # records the offer the bot opens with on each suit
            def __init__(self, tick):
                super().__init__(tick, [None] * 4)
                self.asks = {}

            def offer(self, s, price):
                self.asks[s] = price
                return False

        def asks(tick, **params):
            bot = SharkBot(**params)
            bot.on_start(GameInfo(0, (3, 2, 3, 2), Rules(n_players=4), ("a", "b", "c", "d"), 0))
            book = Offers(tick)
            bot.act(book)
            return book.asks

        plain, wary = asks(0, fill_lr_offer=1.0), asks(0, fill_lr_offer=3.0, fill_tau=20.0)
        self.assertEqual(set(plain), {0, 1, 2, 3})
        self.assertTrue(all(wary[s] >= plain[s] for s in plain))
        self.assertGreater(sum(wary.values()), sum(plain.values()) + 8)  # a real premium at the open
        # ... gone by late in the round, when a lift no longer says the buyer knows more
        self.assertEqual(asks(200, fill_lr_offer=1.0), asks(200, fill_lr_offer=3.0, fill_tau=20.0))

    def test_long_shot_holdings_are_offered_near_their_value_late(self):
        # Six clubs at about 8%, late in the round, a minute and a quarter after clubs looked 30%
        # likely: if clubs were the goal, six would win the bonus, so each club is worth a lot
        # in that case, and v10's offer leaned toward that value all the way to the bell.
        from figgie.shark import SHARK_V10

        class Offers(StaticBook):
            def __init__(self, tick, hand):
                super().__init__(tick, [None] * 4, hand=hand)
                self.asks = {}

            def offer(self, s, price):
                self.asks[s] = price
                return False

        def asks(**params):
            hand = (0, 6, 2, 2)
            bot = SharkBot(read_weight=0, **params)
            bot.on_start(GameInfo(0, hand, Rules(n_players=4), ("a", "b", "c", "d"), 0))
            early = list(bot.valuation(0).p_goal)
            early[1] = 0.3
            bot.p_sticky = bot.p_avg = bot._p_tick = None
            bot._track(150, early)
            book = Offers(225, hand)
            bot.act(book)
            self.assertLess(bot.valuation(225).p_goal[1], 0.1)
            return book.asks

        old, new = asks(**SHARK_V10), asks()
        self.assertLessEqual(new[1], old[1] - 5)  # the clubs: v10 opened at $18, v11 at $11
        self.assertTrue(all(new[s] <= old[s] for s in old))

    def test_sticky_protection_survives_a_brief_dip(self):
        class V:  # a stand-in valuation: only p_goal matters here
            def __init__(self, pg):
                self.p_goal = pg

        bot = SharkBot(sticky_halflife=60)
        bot.p_sticky = bot.p_avg = bot._p_tick = None
        bot._track(10, [0.1, 0.5, 0.2, 0.2])
        dip = [0.1, 0.05, 0.6, 0.25]  # thirty ticks later clubs briefly looks dead
        bot._track(40, dip)
        self.assertAlmostEqual(bot.p_hold(1, V(dip)), 0.5 * 0.5 ** (30 / 60))
        self.assertGreater(bot.p_hold(1, V(dip)), bot.params.churn_p)  # still protected
        bot._track(400, dip)  # long after, the protection has faded
        self.assertAlmostEqual(bot.p_hold(1, V(dip)), 0.05, places=3)

        off = SharkBot(sticky_halflife=0)
        off.p_sticky = off.p_avg = off._p_tick = None
        off._track(10, [0.1, 0.5, 0.2, 0.2])
        off._track(40, dip)
        self.assertEqual(off.p_hold(1, V(dip)), 0.05)  # disabled: just the current belief

    def test_v2_beats_v1_against_informed_bots(self):
        from figgie.tournament import run_tournament

        res = run_tournament(["shark", "sharkv1", "oracle", "oracle"], games=60, seed=5, workers=1)
        self.assertGreater(res.stats["shark"].mean, res.stats["sharkv1"].mean)


class ResaleTests(unittest.TestCase):
    def test_tracker_learns_the_pattern_from_the_market(self):
        r = ResaleTracker(cheap=2, margin=2, window=45, min_hits=2)
        self.assertIsNone(r.value(1))  # nothing seen yet
        r.cheap_seen(10, 1, 1, seller=2)
        r.bid_seen(12, 1, 5, bidder=2)  # the seller bidding its own suit back up is no resale
        r.bid_seen(14, 2, 6, bidder=3)  # another suit
        r.bid_seen(15, 1, 2, bidder=3)  # not $2 above the cheap price
        self.assertEqual(r.hits, 0)
        r.bid_seen(20, 1, 5, bidder=3)  # resold
        r.cheap_seen(30, 0, 2, seller=1)
        r.bid_seen(40, 0, 4, bidder=2)
        r.cheap_seen(50, 3, 1, seller=1)
        r.expire(96)  # nobody bid diamonds back up within 45 ticks
        self.assertEqual((r.hits, r.misses, r.prices), (2, 1, [5, 4]))
        self.assertTrue(r.active())
        self.assertEqual(r.resale_price(), 4)  # cautious: the lower quartile
        p = r.p_hit()
        self.assertAlmostEqual(p, (2 + 1) / (3 + 3))
        self.assertAlmostEqual(r.value(1), p * 3 - (1 - p) * 1)
        self.assertIsNone(r.value(3))  # not a cheap price

    def test_kill_switch_and_ramp(self):
        r = ResaleTracker(window=45, stop_loss=6.0)
        r.seed(30.0, 2.0, 0.0, 0.0, [5] * 8)  # the market resells nearly everything
        self.assertTrue(r.active())
        self.assertEqual(r.allowed(4), 1)  # one card at a time until resales work for us
        r.bought(100, 1, 2)
        r.sold(1, 5)
        self.assertEqual((r.own_hits, r.realized), (1, 3))
        self.assertEqual(r.allowed(4), 2)
        # ... then two cards that never resell: written off after the window, and that is enough
        r.bought(110, 2, 2)
        r.bought(112, 3, 1)
        r.expire(150)
        self.assertTrue(r.active())
        r.expire(160)
        self.assertEqual((r.own_misses, r.realized), (2, 0))
        self.assertTrue(r.active())  # one net failure is not yet a pattern
        r.bought(170, 0, 2)
        r.expire(216)
        self.assertEqual(r.own_misses - r.own_hits, 2)
        self.assertFalse(r.active())
        self.assertIsNone(r.value(1))
        # the market's record cannot outvote our own: 20 observations at most
        self.assertLess(r.p_hit(), 0.8)
        # stop-loss on its own
        q = ResaleTracker(stop_loss=3.0)
        q.seed(10.0, 0.0, 5.0, 0.0, [5] * 4)
        q.bought(0, 1, 2)
        q.bought(0, 2, 2)
        q.expire(50)
        self.assertEqual(q.realized, -4)
        self.assertFalse(q.active())

    def _game(self, **params):
        # dealt five spades and five clubs, the shark holds no red card: hearts look dead to it
        hands = [[5, 5, 0, 0], [3, 1, 3, 3], [2, 1, 4, 3], [2, 1, 3, 4]]
        shark = SharkBot(read_weight=0, smart_weight=0, resale_cheap=2, **params)
        g = Game([shark, Bot(), Bot(), Bot()], config=CONFIGS[0], hands=hands, seed=3)
        g.begin()
        shark.resale.seed(5.0, 0.0, 0.0, 0.0, [5, 5, 5, 5, 5])  # the pattern, as earlier rounds showed it
        return g, shark

    def test_shark_buys_a_dumped_card_and_resells_it(self):
        g, shark = self._game()
        self.assertLess(shark.valuation(0).p_goal[2], 0.1)
        g.order(1, "offer", 2, 2)  # a heart dumped for $2
        shark.act(Market(g, 0))
        self.assertEqual(g.hands[0][2], 1, "the shark buys the cheap heart ...")
        self.assertEqual(shark.resale.held(2), 1)
        g.step()  # a tick passes
        g.order(2, "bid", 2, 5)  # ... and another player bids $5 for hearts
        shark.act(Market(g, 0))
        self.assertEqual(g.hands[0][2], 0, "... which it sells into the bid")
        self.assertEqual((shark.resale.held(2), shark.resale.own_hits, shark.resale.realized), (0, 1, 3))
        # without the pattern the same cheap heart is left alone
        g, shark = self._game()
        shark.resale = ResaleTracker()
        g.order(1, "offer", 2, 2)
        shark.act(Market(g, 0))
        self.assertEqual(g.hands[0][2], 0)

    def test_resale_bid_fills_become_resale_stock(self):
        g, shark = self._game(resale_bid=True)
        shark.act(Market(g, 0))
        stand = [s for s in range(4) if g.bids[s] is not None and g.bids[s].player == 0 and shark._resale_bids[s] > 0]
        self.assertTrue(stand, "it bids for dumped cards while the pattern is live")
        s = stand[0]
        g.order(1, "sell", s)  # someone dumps a card into that bid
        self.assertEqual(shark.resale.held(s), 1)

    def test_resale_pays_at_a_churning_table_and_is_capped_when_baited(self):
        from figgie.tournament import run_tournament

        def mean(spec, field, games):
            return run_tournament([spec] + field, games=games, seed=7, workers=1).stats[spec].mean

        field = ["fickle", "fickle", "fickle"]
        on = mean("shark:resale_cheap=2,resale_bid=true", field, 100)
        self.assertGreater(on, mean("shark", field, 100))
        ring = ["bait", "bait", "bait"]
        self.assertGreater(mean("shark:resale_cheap=2", ring, 60), mean("shark", ring, 60) - 10)


class ResaleLearnerTests(unittest.TestCase):
    @staticmethod
    def _market(L, start=10, end=200, step=9, resold_suits=(2,), dead_suits=(3,)):
        """Player 1 dumps cards for $1; in the resold suits player 2 bids $4 soon after."""
        for t in range(start, end, step):
            for s in resold_suits:
                L.quote_seen(t, s, False, 1, 1)
                L.quote_seen(t + 4, s, True, 4, 2)
            for s in dead_suits:
                L.quote_seen(t, s, False, 1, 1)
            L.expire(t)

    def test_learner_learns_which_offers_resell_from_the_tape(self):
        L = ResaleLearner()
        L.start_round(0, 240, ["a", "b", "c"])
        cold = L.value_at(100, 2, 1, 1)
        self.assertLess(cold, 0.5, "it does not trust a pattern it has not seen")
        self._market(L)
        self.assertGreater(L.n_obs, 30, "every dumped card is an observation, not just our own trades")
        self.assertEqual(L.hits, 22)  # every heart dumped (t = 10, 19, ..., 199) was bid back up
        self.assertGreaterEqual(L.misses, 12)
        hot = L.value_at(201, 2, 1, 1)  # hearts: bid back up every time, someone bidding right now
        dead = L.value_at(201, 3, 1, 1)  # diamonds: never bid back up
        self.assertGreater(hot, 0.5)
        self.assertLess(dead, 0.0)
        self.assertGreater(L.p_resale(L.features(201, 2, 1, 1), 1), L.p_resale(L.features(201, 3, 1, 1), 1))

    def test_learner_stops_when_its_own_resales_fail(self):
        L = ResaleLearner()
        L.start_round(0, 240, ["a", "b", "c"])
        self._market(L, end=120)
        before = L.value_at(121, 2, 1, 1)
        self.assertGreater(before, 0.5)
        x = L.features(121, 2, 1, 1)
        p_before = L.p_resale(x, 1) * L.calibration()
        # a ring: others' dumped cards get bid back up, ours never do
        for t in (121, 125, 130):
            L.bought_from(t, 2, 1, 1)
        L.expire(180)
        self.assertLess(L.calibration(), 0.6)
        self.assertLess(L.p_resale(x, 1) * L.calibration(), 0.6 * p_before, "our record scales the market's down")
        self.assertFalse(L.active(), "three unsold resale cards also trip the kill switch")
        self.assertIsNone(L.value_at(180, 2, 1, 1, 0.0))
        # next round the kill switch resets, but the record of our resales (faded) still holds it back
        L.start_round(0, 240, ["a", "b", "c"])
        self.assertTrue(L.active())
        self.assertLess(L.calibration(), 0.75)

    def test_learner_carries_over_and_restores(self):
        L = ResaleLearner()
        L.start_round(0, 240, ["a", "b", "c"])
        self._market(L)
        mem = L.memory()
        M = ResaleLearner()
        M.start_round(0, 240, ["a", "b", "c"])
        M.seed(*mem)
        L.start_round(0, 240, ["a", "b", "c"])  # the same learner, kept: must agree
        self.assertEqual((L.mu, L.S, L.cal_hits, L.cal_pred), (M.mu, M.S, M.cal_hits, M.cal_pred))
        # a full snapshot restores mid-round state exactly (used by the JS parity vectors)
        self._market(L, start=20, end=60)
        N = ResaleLearner()
        N.load(L.state())
        for X in (L, N):
            X.quote_seen(61, 2, False, 1, 1)
            X.quote_seen(63, 2, True, 4, 3)
            X.expire(110)
        self.assertEqual(L.state(), N.state())
        # new opponents: what our own resales showed counts for less
        L.cal_hits, L.cal_pred = 1.0, 4.0
        L.start_round(0, 240, ["d", "e", "f"])
        self.assertAlmostEqual(L.cal_pred, 4.0 * L.cal_decay * L.table_decay)

    def test_new_opponents_wipe_the_seller_offsets(self):
        d = len(LEARNER_FEATURES)
        L = ResaleLearner()
        L.start_round(0, 240, ["a", "b", "c"])
        self._market(L)
        self.assertEqual(set(L.sellers), {1}, "the seller who dumps has an offset")
        mem = L.memory()
        shared = list(L.mu[:d])
        L.start_round(0, 240, ["a", "b", "c"])
        self.assertEqual(len(L.mu), d + 1, "the same opponents: it stays")
        L.start_round(0, 240, ["d", "e", "f"])
        self.assertEqual((L.sellers, len(L.mu), len(L.S), len(L.S[0])), ({}, d, d, d), "seat 1 is someone else now")
        self.assertEqual(L.mu, shared, "the shared weights stay as learned")
        # the same when the model comes from an earlier page (memory -> seed) ...
        M = ResaleLearner()
        M.start_round(0, 240, ["d", "e", "f"])
        M.seed(*mem)
        self.assertEqual((M.sellers, len(M.mu), len(M.S)), ({}, d, d))
        # ... but not at the same table
        N = ResaleLearner()
        N.start_round(0, 240, ["a", "b", "c"])
        N.seed(*mem)
        self.assertEqual(set(N.sellers), {1})

    def test_robust_learner_counts_only_bids_that_proved_real(self):
        L = ResaleLearner(robust=True)
        L.start_round(0, 240, ["a", "b", "c"])
        L.quote_seen(10, 2, False, 1, 1)  # a $1 heart on offer
        L.quote_seen(12, 2, True, 6, 2)  # a $6 bid flashed: not proof of anything yet
        self.assertEqual(L.hits, 0)
        L.bid_seen(12, 2, 6, 2)  # the bid stood (the shark's smart_confirm rule calls this)
        self.assertEqual(L.hits, 1)

    def test_robust_learner_sees_bids_that_vanish_once_we_hold(self):
        # a bait ring: cheap hearts are bid back up while we are flat, never once we hold hearts
        L = ResaleLearner(robust=True)
        L.start_round(0, 240, ["a", "b", "c"])
        for t in range(10, 100, 9):
            L.quote_seen(t, 2, False, 1, 1)
            L.bid_seen(t + 4, 2, 5, 2)
            L.expire(t)
        x_flat = L.features(100, 2, 1, 1, held=False)
        x_held = L.features(100, 2, 1, 1, held=True)
        before = L.p_resale(x_held, 1, lcb=False)
        L.trade_seen(100, 2, 1, 0, 1)  # we buy a heart: now long
        for t in range(101, 200, 9):
            L.quote_seen(t, 2, False, 1, 1)  # still dumped, never bid back up
            L.expire(t + 50)
        self.assertLess(L.p_resale(x_held, 1, lcb=False), 0.5 * before, "holding the suit: the pattern breaks")
        self.assertGreater(L.p_resale(x_flat, 1, lcb=False), L.p_resale(x_held, 1, lcb=False) + 0.2)

    def test_v12_models_load_with_the_held_weight_added(self):
        old = ResaleLearner()
        old.start_round(0, 240, ["a", "b", "c"])
        self._market(old)
        st = old.memory()[0]
        d = len(LEARNER_FEATURES)
        v12 = dict(st, mu=st["mu"][: d - 1] + st["mu"][d:], S=[r[: d - 1] + r[d:] for i, r in enumerate(st["S"]) if i != d - 1])
        v12.pop("d")
        v12["sellers"] = [[p, k - 1] for p, k in st["sellers"]]
        N = ResaleLearner(robust=True)
        N.start_round(0, 240, ["a", "b", "c"])
        N.seed(v12)
        self.assertEqual((len(N.mu), N.mu[d - 1], N.S[d - 1][d - 1]), (d + 1, 0.0, 1.0))
        self.assertEqual(N.sellers, {1: d})
        self.assertEqual(N.mu[:d - 1] + N.mu[d:], v12["mu"])

    def test_shark_learns_resale_from_round_to_round(self):
        shark = SharkBot(resale_cheap=2, resale_bid=True, resale_learn=True)
        field = [make_bot("fickle") for _ in range(3)]
        seen = []
        for r in range(3):
            Game([shark] + field, seed=900 + r).run()
            self.assertIs(shark.resale, shark.learner)
            seen.append(shark.learner.n_obs)
        self.assertTrue(seen[0] > 20 and seen[2] > seen[1] > seen[0], "one learner, learning all the way")

    def test_learned_resale_pays_where_cards_churn(self):
        from figgie.tournament import run_tournament

        def mean(spec, field, games):
            return run_tournament([spec] + field, games=games, seed=7, workers=1).stats[spec].mean

        field = ["fickle", "fickle", "fickle"]
        self.assertGreater(mean("shark:resale_cheap=2,resale_bid=true,resale_learn=true", field, 100), mean("shark", field, 100))


class ArenaTests(unittest.TestCase):
    def test_seeds_are_disjoint_across_splits_and_independent_of_other_tables(self):
        from figgie.arena import TABLES, table_seed

        seeds = {sp: {table_seed(sp, t, i) for t in TABLES for i in range(50)} for sp in ("train", "val", "holdout")}
        self.assertFalse(seeds["train"] & seeds["val"] or seeds["train"] & seeds["holdout"] or seeds["val"] & seeds["holdout"])
        self.assertEqual(sum(len(s) for s in seeds.values()), 3 * 50 * len(TABLES), "no two sessions share a deal")
        self.assertEqual(table_seed("val", "mixed", 7), table_seed("val", "mixed", 7))

    def test_every_adversary_plays(self):
        from figgie.arena import TABLES

        for t in ("bait2", "pumped", "snipers", "pennies", "quiet", "holdout", "adaptive", "selfplay"):
            bots = [make_bot("sharklive")] + [make_bot(s) for s in TABLES[t]]
            res = Game(bots, rules=Rules(n_players=4, ticks=60), seed=11).run()
            self.assertAlmostEqual(sum(res.pnl), 0.0, places=6)


class ReadingLearnerTests(unittest.TestCase):
    def test_colour_reading_fades_where_early_bids_name_the_goal(self):
        R = ReadingLearner()
        seen = [R.p_colour()]
        for _ in range(8):
            R.end_round(goal=0, early_top=0, consensus=None)  # the early top bid was on the goal
            seen.append(R.p_colour())
        self.assertEqual(seen, sorted(seen, reverse=True))
        self.assertLess(seen[-1], 0.35)
        R = ReadingLearner()
        for i in range(6):
            R.end_round(goal=2, early_top=3 if i % 2 else 2, consensus=None)  # figgie.com: half on the partner
        self.assertGreater(R.p_colour(), 0.9)

    def test_a_faked_consensus_is_soon_ignored_and_a_new_table_is_given_a_chance(self):
        R = ReadingLearner()
        R.start_round(["a", "b", "c"])
        R.end_round(goal=0, early_top=None, consensus=2)
        R.end_round(goal=1, early_top=None, consensus=3)
        self.assertLess(R.p_consensus(), 0.2)
        low = R.p_consensus()
        R.start_round(["d", "e", "f"])
        self.assertGreater(R.p_consensus(), low)
        R2 = ReadingLearner()
        for g in range(4):
            R2.end_round(goal=g, early_top=None, consensus=g)
        self.assertGreater(R2.p_consensus(), 0.95)

    def test_shark_scales_its_reading_by_what_it_learned(self):
        shark = SharkBot(smart_consensus=0.8, smart_colour_fade=90, read_learn=True)
        field = [make_bot("pump") for _ in range(3)]
        for r in range(3):
            Game([shark] + field, seed=4200 + r).run()
        self.assertLess(shark.reader.p_consensus(), 0.5, "the pump ring's fake consensus names a dead suit")


if __name__ == "__main__":
    unittest.main()
