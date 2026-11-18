# Development history

How the bot got from losing $29 a round to figgie.com's Hard bots to beating
them, one live test at a time. Every live round was played at a private table
(no humans allowed) against three figgie.com bots on **Hard**. "P&L" includes
the ante. "Top bids" is the highest price any other player bid or paid for
each suit during the round.

Versions stay available in the simulator as `sharkv1` ... `sharkv6`,
`sharkv8` (v7 and v8 play identically there) and `sharkv10` (so do v9 and
v10); `shark` is always the current one.

| Version | Live rounds | Total | Per round | ±95% |
|---|---|---|---|---|
| v1 | 9 | −$261 | −$29.0 | ±35 |
| v2 | 7 | +$174 | +$24.9 | ±45 |
| v3 | 10 | +$423 | +$42.3 | ±35 |
| v4 | 5 | +$271 | +$54.2 | ±64 |
| v5 | 10 | +$159 | +$15.9 | ±44 |
| v6 | 10 | +$360 | +$36.0 | ±45 |
| v7 | 10 | +$475 | +$47.5 | ±45 |
| v8 | 10 | +$335 | +$33.5 | ±34 |
| v9 | 10 | +$535 | +$53.5 | ±41 |
| v9.1 | 10 | +$551 | +$55.1 | ±41 |
| v10 | 10 | +$603 | +$60.3 | ±34 |
| v11 | 10 | +$735 | +$73.5 | ±44 |
| v12 | 10 | +$799 | +$79.9 | ±34 |
| v13 | 10 | +$989 | +$98.9 | ±32 |
| v13.3 | 11 | +$810 | +$73.6 | ±37 |

---

## v1: market-making as if the opponents were naive

**v1 got slaughtered by figgie.com's Hard bots: −$261 over 9 rounds
(−$29/round).** It market-made as if its opponents were naive, so it was
adversely selected every round. The bots happily sold it the suits they knew
were dead (once it ended a round holding 10 clubs; the goal was diamonds) and
lifted its cheap offers on the real goal suit. In 5 of 9 rounds it put 30% or
less on the true goal at the bell.

A recorded round showed how readable those bots are (goal: diamonds):

| Suit | Highest bid by any bot | Bids of $10+ | Lowest offer |
|---|---|---|---|
| ♦ goal | $15 | 15 | $22 |
| ♣ | $7 | 0 | $4 |
| ♥ | $4 | 0 | $3 |
| ♠ | $4 | 0 | $2 |

## v2: smart money and patience

Every $10+ bid in that round was on the goal suit; dead suits churned at
$1-4. v2 trades on that:

* **Smart money.** The highest price anyone else bids or pays for a suit, and
  the lowest anyone sells it at, are strong votes on the goal suit (a $15 bid
  turns a coin-flip into a near-certainty). Updated on every quote, so it is
  priced in *before* the bot crosses the spread.
* **Patience.** Bids open at 30% of the limit and climb $1 every 3 seconds;
  taking an offer needs a 20% edge; it never pays more than $50 x P(goal) for
  a card, so it pays up only for a suit the market has already marked.
* **Adverse-selection pricing.** Whoever hits a resting bid probably knows the
  suit is dead, and whoever lifts an offer probably knows it is the goal, so
  resting bids sit further under value and offers on a suit that might be the
  goal stay expensive.
* **No panic-dumping.** It won't sell a card for less than 60% of what it paid
  unless it is confident (>85%) the suit is dead.

**v2 live: +$174 over 7 rounds (+$24.90/round)** against the same Hard bots
that took v1 for −$29/round:

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♠ | 4 3 0 3 | 0 1 0 0 | 55% | 11/13/11/11 | -22 |
| ♠ | 2 3 3 2 | 5 0 0 2 | 91% | 11/11/7/7 | +19 |
| ♥ | 3 3 2 2 | 0 0 0 0 | 62% | 13/8/15/16 | -17 |
| ♣ | 5 2 1 2 | 0 0 0 0 | 84% | 8/11/9/13 | -14 |
| ♣ | 4 2 1 3 | 0 4 0 0 | 99% | 11/18/8/12 | +65 |
| ♣ | 2 4 2 2 | 0 6 0 0 | 61% | 10/14/16/8 | +110 |
| ♥ | 2 1 3 4 | 0 0 5 0 | 97% | 11/10/13/11 | +33 |

The v1-to-v2 gap (~$54/round) is about 2.2 standard errors; that v2 is
profitable on its own was not yet established (±$45 at 95% over 7 rounds).

**The leak v2 still had:** it sold the goal-suit cards it was dealt before
the market revealed the goal. In three rounds it finished with no goal cards
despite naming the goal correctly by the bell, so it collected no payout and
the $50 ante decided the round. (When the bots bid $10+ on every suit, as in
the first row, the smart-money signal also cancels out.)

## v3: the option to wait

Early in a round every suit is still a 20-40% goal candidate, so a card's
sell value (P(goal) × $10) looked small and any $6-11 bid got hit - by exactly
the bots who suspected that suit. But holding the card is worth more than
that: once the market shows the goal, a goal card pays out or sells to the
bonus chasers (live they paid $11-19), and a dead card can still be dumped
for a couple of dollars. So until the bell a card is never sold for less than

    P(goal) × max(its value if goal, hold_goal × w) + (1 - P(goal)) × hold_dead × w

where `w` is the fraction of the round still to play (the premium fades to
nothing by the bell). With the defaults (`hold_goal` $25, `hold_dead` $5), a
suit that is a coin flip for the goal is no longer sold at the open for less
than about $19 (v2 would hit an $8 bid), and even a suit that looks dead is not
dumped for pennies early: its floor starts at $5 and fades to $0 by the bell.

**v3 live: +$423 over 10 rounds (+$42.30/round, 8 of 10 profitable)**, the
first version whose live profit is statistically clear (about 2.7 standard
errors above zero):

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♣ | 6 2 1 1 | 0 6 0 0 | 95% | 17/16/9/12 | +105 |
| ♣ | 4 2 2 2 | 0 0 0 0 | 98% | 14/21/18/10 | -29 |
| ♠ | 5 3 0 2 | 0 0 0 0 | 85% | 19/15/12/8 | +20 |
| ♥ | 2 3 1 4 | 0 0 5 0 | 94% | 14/9/15/14 | +64 |
| ♦ | 4 2 1 3 | 0 0 0 5 | 91% | 7/9/11/14 | +49 |
| ♥ | 1 4 2 3 | 0 0 0 0 | 96% | 14/10/18/11 | -24 |
| ♥ | 1 4 2 3 | 0 0 5 0 | 85% | 12/15/16/7 | +49 |
| ♣ | 4 3 1 2 | 6 5 0 0 | 54% | 12/13/12/9 | +12 |
| ♦ | 1 2 2 5 | 0 0 0 5 | 98% | 9/10/4/14 | +57 |
| ♦ | 1 3 4 2 | 0 0 0 5 | 40% | 10/8/15/11 | +120 |

Its gain over v2 (+$17/round) is in line with the simulator's +$5-7 but well
inside the noise.

**Remaining weakness:** when the bots bid $14-21 on several suits at once, the
"highest bid per suit" signal swings with whichever suit spiked last. That
caused all of v3's bad rounds: it overpaid early for the wrong suit ($17 for a
spade, round 6), sold the real goal mid-round while briefly rating it below
15% (rounds 2 and 3), or hedged across both suits of a colour (round 8).

## v4: steadier decisions on a jumpy signal

* **Sticky protection.** The no-dump guard and the waiting premium use the
  highest P(goal) a suit has had recently, fading with a 60-second
  half-life, instead of the instant value. A suit that looked like a 40% goal
  a minute ago is still treated as a ~20% one, so a brief dip can no longer
  unlock dumping it (replaying round 2, its $5-6 club sales are refused).
* **Smoothed pay cap.** The $50 × P(goal) cap on what it pays uses the lower
  of P(goal) and its 8-second moving average, so a fresh spike can't trigger
  an instant top-dollar purchase; it pays up once the signal has held.

Both are neutral in the simulator (within ±1/round of v3 across two sets of
deals and all five fields), because the simulated opponents bid honestly on
the goal; they target failures that only showed up live. Also tried and
rejected: giving each bot one capped vote instead of using the single highest
bid. It cost 3-4/round in the simulator, where one informed bot's big bid is
the most reliable clue there is (still available as `smart_player_cap`).

**v4 live: +$271 over 5 rounds (+$54.20/round)**, at the v3 table. The run
stopped halfway: the Claude window had been in the background for a while,
the page's timers stalled for up to 72 seconds, and figgie.com dropped the
connection and went back to its login screen (cause unknown). The
userscript has ticked from a Web Worker ever since.

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♦ | 0 1 4 5 | 0 0 6 4 | 45% | 5/12/11/10 | +94 |
| ♦ | 2 3 3 2 | 0 3 0 6 | >99% | 7/10/6/15 | +100 |
| ♣ | 3 1 2 4 | 0 0 4 0 | 65% | 5/11/10/14 | −28 |
| ♥ | 0 4 3 3 | 0 0 5 0 | 75% | 7/17/11/7 | +62 |
| ♥ | 0 1 4 5 | 0 0 5 6 | 97% | 11/11/11/6 | +43 |

## v5: why it stopped at 5 cards

With a 10-card goal suit, 5 cards can at best tie for the bonus, and 6
guarantee all of it. The bot finished on exactly 5 of a 10-card goal in five
v3 rounds and two v4 rounds (the last two rows), and all seven ended in a 5-5
split: $50 of bonus instead of $100, $350 left on the table. (With an 8-card
goal, 5 is already a majority, and the one such round paid the full $120.)

The cause was the bonus model. It scored the bonus from where the goal cards
it lacked were *now*. Holding, say, 5 hearts against 3, 1 and 1, it is the
clear leader, so a 6th heart looked worth little more than its $10 payout.
But figgie.com's bots don't leave strays lying around: one of them buys up
the other five and ties.

v5 expects that. `consolidate` (0.5 in v5) blends the bonus share computed
from the current spread with the share it gets if every goal card it lacks
ends up with a single rival. In the example above (hearts certain to be the
goal, 10 cards, the others holding 3/1/1):

| `consolidate` | 6th heart worth, late | 6th heart worth, mid-round | Selling the 5th costs, late |
|---|---|---|---|
| 0 (v4) | $10.0 | $13.8 | $26.7 |
| **0.5 (v5)** | **$35.0** | **$32.8** | **$43.3** |
| 1 | $60.0 | $51.9 | $60.0 |

At 1 the 6th card is worth its $10 plus half the $100 bonus, because it turns
a tie into a win. In the simulator (600 games per field on identical deals,
±95% about ±3-6 per cell; the `oshark` opponents stay on v4):

| `consolidate` | `hand`, `counter`, `noise` | 3 × `counter` | 3 × `oracle` | `oshark`, `oracle`, `counter` | 3 × `oshark` | average |
|---|---|---|---|---|---|---|
| 0 (v4) | +42.6 | +44.3 | +52.3 | +24.1 | −3.6 | +31.9 |
| 0.25 | +40.1 | +44.0 | +54.5 | +27.2 | −1.7 | +32.8 |
| **0.5 (v5)** | +40.6 | +43.3 | +50.3 | +25.6 | **+2.5** | +32.5 |
| 0.75 | +35.6 | +37.1 | +44.5 | +22.1 | +6.1 | +29.1 |
| 1 | +28.7 | +33.5 | +39.1 | +23.6 | +7.6 | +26.5 |

**v5 live: +$159 over 10 rounds (+$15.90/round, ±44)**, at two fresh private
tables. The first table closed after round 2, when the page left the game
screen. The second table's first round was joined late and isn't counted.

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♣ | 3 5 2 0 | 1 5 0 5 | 65% | 15/20/9/14 | +41 |
| ♥ | 1 2 4 3 | 0 0 0 6 | 83% | 10/10/18/12 | −32 |
| ♦ | 4 2 3 1 | 0 0 0 5 | 87% | 5/17/12/15 | +51 |
| ♦ | 0 2 5 3 | 0 0 0 6 | >99% | 8/9/10/20 | +108 |
| ♦ | 3 3 1 3 | 0 8 0 0 | 4% | 18/14/11/11 | −32 |
| ♣ | 2 2 4 2 | 6 1 5 0 | 88% | 11/12/10/4 | −49 |
| ♣ | 5 2 0 3 | 6 0 2 0 | 88% | 10/11/11/8 | −35 |
| ♥ | 2 3 3 2 | 0 0 6 0 | 96% | 12/7/26/5 | +116 |
| ♥ | 1 4 4 1 | 0 0 0 0 | 2% | 14/10/11/6 | +15 |
| ♦ | 3 2 3 2 | 5 0 0 0 | 72% | 16/12/8/15 | −24 |

On 10-card goals v5 finished with 6 cards twice (rows 4 and 8, the full $100
bonus each) and with 5 twice (both split). v3 and v4 never got past 5 on a
10-card goal. But six rounds ended with 0-1 goal cards (v3 and v4 combined: 4
in 15), and in all six it sold goal-suit cards it was dealt. Consolidation
plausibly contributes: it values a small holding as if a rival will collect
the rest, so 2-4 cards of a suit look nearly worthless and are cheap to pry
loose. If hearts is surely the goal and nothing is known about the other
hands, mid-round:

| | `consolidate` 0 | 0.5 |
|---|---|---|
| Giving up the 3rd heart costs | $36.3 | $23.1 |
| Giving up the 4th heart costs | $68.4 | $40.1 |
| Giving up the 5th heart costs | $26.4 | $42.3 |
| A 6th heart is worth | $11.4 | $34.8 |

## v6: consolidation only where it decides the bonus

`consolidate_at` (0.5) applies the blend only once the bot holds at least half
the goal suit, where the next card decides between a tie and a win. Smaller
holdings are priced from the current spread, exactly as in v4. With the
small-holding cost gone, the premium at the tipping point can be the full one
(`consolidate` 1.0). Same example (hearts surely the goal, mid-round):

| | v4 | v5 | **v6** |
|---|---|---|---|
| Giving up the 3rd heart costs | $36.3 | $23.1 | **$36.3** |
| Giving up the 4th heart costs | $68.4 | $40.1 | **$68.4** |
| Giving up the 5th heart costs | $26.4 | $42.3 | **$58.3** |
| A 6th heart is worth | $11.4 | $34.8 | **$58.3** |

Simulator, same 600 deals per field:

| | `hand`, `counter`, `noise` | 3 × `counter` | 3 × `oracle` | `oshark`, `oracle`, `counter` | 3 × `oshark` | average |
|---|---|---|---|---|---|---|
| v4 (`sharkv4`) | +42.6 | +44.3 | +52.3 | +24.1 | −3.6 | +31.9 |
| v5 (`sharkv5`) | +40.6 | +43.3 | +50.3 | +25.6 | +2.5 | +32.5 |
| gate, `consolidate` 0.5 | +43.0 | +47.8 | +54.7 | +28.3 | −1.6 | +34.4 |
| **v6**: gate, `consolidate` 1 | +40.5 | +47.9 | +55.2 | +29.7 | −0.6 | **+34.5** |

**v6 live: +$360 over 10 rounds (+$36.00/round, ±45)**:

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♥ | 2 3 2 3 | 3 0 5 6 | 73% | 10/15/12/11 | +12 |
| ♣ | 2 4 1 3 | 0 6 5 0 | 93% | 8/21/11/11 | +73 |
| ♠ | 3 3 2 2 | 6 0 3 0 | 99% | 16/9/12/11 | +127 |
| ♠ | 3 0 6 1 | 6 0 0 0 | 86% | 18/7/13/8 | +90 |
| ♥ | 2 4 2 2 | 6 0 3 0 | 25% | 15/15/13/13 | −42 |
| ♥ | 4 2 3 1 | 6 5 0 0 | 50% | 16/4/22/10 | −55 |
| ♠ | 1 3 2 4 | 6 6 0 0 | 91% | 13/12/17/11 | +14 |
| ♣ | 1 4 3 2 | 0 4 4 8 | 73% | 4/21/7/15 | +6 |
| ♦ | 3 2 3 2 | 3 6 0 5 | 55% | 7/17/6/14 | +22 |
| ♠ | 4 3 2 1 | 6 0 0 0 | 93% | 20/8/10/17 | +113 |

It took the whole bonus in 5 of 10 rounds, with 6 goal cards each time, and
split it in 3. Three times it paid $29-31 for the 6th card of a 10-card goal,
exactly the purchase v3 and v4 never made. Bonus collected per round: v3 $49,
v4 $64, v5 $30, **v6 $69**. Rounds ending with 0-1 goal cards fell from v5's 6
in 10 to 1 in 10. The premium's cost showed in row 7: holding 5 or more of
both black suits, it paid up to $29 for a club, which turned out to be the
12-card suit, before settling on spades.

## v7: bid reading fitted to the live record, spoof resistance, 2-5 players

**Calibrating the smart money.** By v6, 42 logged live rounds recorded the
dealt hand, the highest bid on each suit and the true goal: enough to measure
the bid signal instead of guessing it. Scoring each rule by how well it names
the goal from those numbers alone (leave-one-out for the fitted ones):

| Rule | Goal named | Log-likelihood |
|---|---|---|
| dealt hand only | 13 / 42 | −55.6 |
| v2-v6 rule (a bid counts from $8, every bid above $14.70 alike) | 24 / 42 | −40.4 |
| a suit's bid against the other suits' average | 27 / 42 | −36.9 |
| **fitted: below $17 counts weakly, above $17 strongly** | **28 / 42** | **−33.6** |

figgie.com's Hard bots bid $10-15 on dead suits all the time, so mid-range
bids say little; the old rule over-reacted to them and could not tell a $15
bid from a $22 one. The fitted rule scores a top bid at 0.3 nats per $ below
$17 and 0.8 per $ above (capped at 10), and a suit nobody has bid on like a $4
bid. It also wins in the simulator, where the hand-reading bots' $8-14 bids
had been fooling the old rule too: +$7.5 a round against `hand`/`counter`/
`noise`, +$7 against three `counter`s, level or better elsewhere.

**Spoofing.** A new simulator opponent, `spoofer`, always knows the goal and
flashes a $20+ bid on a dead suit every few seconds, cancelling it on its next
turn, then sells that suit to anyone fooled. Paired against the same table
with the spoofing switched off:

| | spoofed | honest | cost of the lies |
|---|---|---|---|
| v6 | +62.6 | +65.5 | −$3 |
| fitted signal, no defense | +52.5 | +65.5 | −$13 |
| **v7: fitted signal + `smart_confirm` 2** | +60.8 | +64.4 | −$4 |
| bids ignored entirely | +28.0 | −3.9 | (reading bids is worth ~$69 here) |

`smart_confirm` makes a bid count only once the bot has seen it standing in
two different seconds of the round, or seen it outbid or cleared by a trade.
Until then the bot trades against it on its old beliefs, so it sells dead
cards into flashed bids at the spoofer's expense. The delay costs about $1 a
round against honest opponents.

**2, 3 and 5 players.** The engine now deals two players 20 cards each ($100
antes) and three players 13 each, with the 40th card dealt to nobody ($66
antes, a $198 pot; the undealt card's $10 stays in the pot for the bonus
winner). The card counting and the bonus valuation account for that card. In
the simulator v7 makes +$51.6 heads-up against a `counter`, +$37.3 heads-up
against an `oracle`, +$64.2 with three players and +$74.6 with five.

**v7 live: +$475 over 10 rounds (+$47.50/round, ±45)**, at two private
tables. The computer went to sleep during round 6 at the first table and
figgie.com dropped the connection, so rounds 6-10 were played at a fresh
table:

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♦ | 3 1 3 3 | 0 0 6 0 | 45% | 6/11/7/11 | −23 |
| ♠ | 0 4 3 3 | 0 0 0 0 | 99% | 15/12/6/8 | +8 |
| ♦ | 2 2 4 2 | 0 0 0 7 | 98% | 4/7/7/11 | +132 |
| ♣ | 3 3 3 1 | 6 5 0 0 | 82% | 15/11/17/12 | +20 |
| ♥ | 2 2 2 4 | 0 0 6 3 | 80% | 4/17/11/7 | +121 |
| ♠ | 1 5 1 3 | 7 0 0 0 | 88% | 11/8/13/13 | +143 |
| ♠ | 4 2 3 1 | 6 6 6 0 | 100% | 22/5/14/8 | +62 |
| ♦ | 4 0 5 1 | 0 0 0 0 | 71% | 12/12/15/13 | −1 |
| ♦ | 5 0 3 2 | 0 0 0 0 | 25% | 11/9/8/10 | +8 |
| ♣ | 5 2 2 1 | 0 4 0 0 | 51% | 9/9/9/12 | +5 |

It won 8 of 10 rounds, and its worst round (−$23) is the mildest of any
10-round test (v6 −$55, v5 −$49, v3 −$29). It took the whole bonus four times,
three times with 6-7 cards of an 8-card goal it bought up for $4-11 each, and
split it once. Its two wrong reads came when the top bids said almost
nothing: $6-11 everywhere in row 1, where it drifted into hearts (the 12-card
suit), and $8-11 everywhere in row 9. Rows 2 and 8 show it making the best of
being dealt no or one goal card: it named the goal and sold the rest into the
bots' bids.

## v8: consensus (figgie.com only)

v7 also logged each bot's own top bid per suit, which showed a pattern the
pooled top bid hides: **every** Hard bot bids the goal suit up at some point,
while a dead suit usually draws a big bid from only one of them. Take the
*lowest* of the three bots' top bids on each suit: in all ten v7 rounds the
goal's was $7-10 and every dead suit's $3-6. Round 9 is typical: the highest
bid was $11 for spades (one bot), but all three bots bid $9-10 for diamonds,
the goal. One bluffer can't fake it, either.

v8 adds that as evidence: 0.8 nats per $ the lowest per-bot top bid sits above
$5, capped at 4 nats (`smart_consensus`). Fitted to the v7 rounds it would have
named the goal in 10 of 10 (in sample). In the simulator it is neutral (−$0.5 a
round): the simulated bots bid whatever their own hand suggests, so "every bot
bid it" means little there. It is therefore switched on only in the figgie.com
script. Also tried: counting a pending bid cleared by a trade only once it had
stood for two ticks (`smart_confirm_trade` 2), to close the rest of the spoofing
leak. It cost $2-6 a round everywhere, the spoofed table included, and was
dropped.

**v8 live: +$335 over 10 rounds (+$33.50/round, ±34)**, at two private tables
(the computer slept during round 6 at the first one again):

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♥ | 3 3 1 3 | 5 0 0 0 | 95% | 16/11/14/8 | −5 |
| ♠ | 3 2 3 2 | 5 5 0 0 | 100% | 13/12/6/7 | +29 |
| ♠ | 3 4 2 1 | 6 0 0 0 | 100% | 22/7/7/10 | +127 |
| ♠ | 2 2 4 2 | 0 0 0 0 | 99% | 16/9/7/14 | +16 |
| ♦ | 4 1 4 1 | 0 0 0 0 | 100% | 8/6/16/19 | +11 |
| ♥ | 3 2 3 2 | 0 5 6 0 | 100% | 10/14/20/12 | +80 |
| ♣ | 4 3 1 2 | 3 5 0 0 | 100% | 13/15/12/9 | +62 |
| ♣ | 4 1 4 1 | 0 0 0 0 | 100% | 12/16/17/5 | 0 |
| ♠ | 3 1 1 5 | 0 0 5 5 | 76% | 12/10/12/10 | −39 |
| ♣ | 3 3 1 3 | 6 6 0 0 | 100% | 10/25/11/18 | +54 |

**Out of sample, the consensus pattern held in all ten rounds** (goal $7-10,
dead suits $3-6), and the bot ended every round with the goal as its favourite,
at 97% on average (v7: 74%). The P&L did not move with it: +$33.50 a round is
inside the noise of v3-v7. Three rounds dealt it one or two goal cards (rows 4,
5 and 8), which caps what knowing the goal is worth, and its one real loss (row
9) came before the market had spoken: five diamonds made hearts look like the
goal (48% at the open), so it sold its spades at $6-12 early and bought hearts;
by the time all three bots had bid spades up it held none. What remains is the
first minute or two of each round, when the bot has to trade on its hand alone.

## v9: early offers priced for who lifts them

**Is early trading a leak?** Not on average. The runners had kept the bot's
own trades for 42 live rounds (500 trades, timestamped). Valuing each card at
$10 if it was the goal and $0 otherwise, the v7-v8 bot's buys in the first two
minutes were of the goal 48% of the time, against the 35% its hand alone
predicted, and its early sells made money. The simulator agrees that the
opening is where the edge is: sitting out the first 20 seconds costs $7-24 a
round on every table except three `oshark`s (about $0). Round 9 of v8 was a
misleading hand, not a habit. So v9 does not slow down.

**Who fills its quotes early.** It does have one leak there. Splitting the
simulator's trades by whether the bot crossed the spread or was filled on its
own quote: in the first 20 seconds, when an informed bot (`oracle`, `oshark`)
lifts its offer, the suit turns out to be the goal 30-97% of the time where
the bot had put it at 8-43%. The buyer knows something the bot doesn't, and
nobody has bid yet to tell it. The live record shows the same: early sales were of the goal 33-40%
of the time, against 15-21% on the hand alone. v9 prices each offer at what
keeping the card is worth *given that it was lifted*: a lift counts as
evidence for the goal with likelihood ratio 3 at the open, fading with a
60-second time constant (`fill_lr_offer`, `fill_tau`). Ruled out along the way:
the same discount on its bids (`fill_lr_bid`, +$0.5 to −$4 a round, mostly
losses: early buying is the edge), counting a fresh, unconfirmed bid against selling into it
(no measurable effect in the simulator), a fade tied to the bot's own
confidence instead of the clock, and fades of 20 and 90 seconds. Against an
opponent that always knows the goal, protection that lasts longer pays more,
and 60 seconds costs nothing measurable against uninformed bots.

Paired, 2,000 identical deals per table (`sharkv8` vs `shark`):

| Opponents (table size) | v8 | v9 | difference |
|---|---|---|---|
| `hand`, `counter`, `noise` (4) | +47.5 | +47.6 | +0.05 ±1.2 |
| 3 × `counter` (4) | +52.9 | +52.8 | −0.15 ±1.2 |
| 3 × `oracle` (4) | +56.4 | +57.1 | **+0.65 ±0.6** |
| `oshark`, `oracle`, `counter` (4) | +30.0 | +30.3 | +0.25 ±1.1 |
| 3 × `oshark` (4) | +0.2 | +0.6 | +0.40 ±0.7 |
| `spoofer`, `oracle`, `counter` (4) | +61.2 | +80.6 | **+19.4 ±2.3** |
| the same, but the spoofer never spoofs (4) | +65.1 | +66.0 | **+0.89 ±0.6** |
| `counter` (2) | +51.0 | +50.7 | −0.33 ±0.5 |
| `oracle` (2) | +38.2 | +38.4 | +0.18 ±0.5 |
| `counter`, `oracle` (3) | +64.9 | +65.7 | +0.74 ±0.8 |
| `hand`, `counter`, `noise`, `oracle` (5) | +75.0 | +75.1 | +0.13 ±0.9 |

The general effect is the small one against informed bots (+$0.65 and
+$0.89, outside the noise). The spoofer table's +$19 is mostly a quirk of that
opponent: selling less through early offers (0.3 cards a round in the first
minute, against 0.7), v9 still holds dead cards when the spoofer flashes its
$20 bids, and sells more of them into high bids, the flashes among them (1.9
a round in the first minute instead of 1.2, at about $16). It also sells the
goal through a lifted offer less than half as often.
v9 also logs every round in full: each quote and trade with its time, and for the
bot's own trades its P(goal) just before and whether it crossed the spread.

**v9 live: +$535 over 10 rounds (+$53.50/round, ±41)**, at two private tables
(a round in between was lost when the page left the game screen 63 seconds
in, and isn't counted):

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♠ | 2 1 4 3 | 6 0 0 0 | 100% | 22/8/16/7 | +92 |
| ♣ | 2 2 4 2 | 0 6 0 0 | 100% | 9/21/6/10 | +98 |
| ♠ | 2 3 4 1 | 6 0 0 0 | 100% | 23/13/14/10 | +103 |
| ♣ | 2 3 3 2 | 0 7 0 0 | 97% | 7/11/18/7 | +104 |
| ♥ | 3 2 3 2 | 3 0 0 5 | 99% | 16/8/16/12 | −53 |
| ♣ | 3 3 1 3 | 0 6 0 0 | 100% | 17/23/9/17 | +108 |
| ♣ | 2 3 1 4 | 6 6 0 0 | 99% | 10/10/8/7 | +65 |
| ♥ | 1 4 5 0 | 0 0 0 7 | 93% | 12/10/11/13 | −64 |
| ♥ | 1 3 4 2 | 0 0 6 6 | 96% | 5/12/11/5 | +71 |
| ♣ | 4 1 4 1 | 0 0 0 0 | 100% | 9/18/11/10 | +11 |

The best 10-round result yet, but within the noise of v3-v8 again. The goal
was its favourite at the bell in all ten rounds, and it took the whole bonus
in seven, each time with 6-7 goal cards.

**What the first full logs show.** They answer when the market speaks:
the consensus signal (every bot has bid the goal above $5) first appeared
between 127 and 188 seconds into the round, typically around 140. Before
that the bot trades on its hand and on single bids, and the early leak is on
the buying side after all. Of its 27 buys in the first minute, 4 were the goal
(15%), where it had put those suits at 40-48%. Thirteen were the 12-card suit,
the goal's same-colour partner, at $8.70 on average: the bot gets the colour
right, then buys the suit that is plentiful and that the other bots, holding
lots of it, are happy to sell. Both losing rounds trace back to the first
two and a half minutes:

* Row 5: 95 seconds before the bell it hit three fresh hearts bids at $6-7
  while it still put hearts at 6-28%. Those bids were not yet counted as
  evidence, by the spoofing rule. Twenty seconds later it was 92% sure of
  hearts.
* Row 8: dealt five hearts and no diamonds, it was 91% sure of diamonds after
  52 seconds (its hand plus one bot's diamond bid) and paid up to $28 for them.

Row 3 is the first counterexample to the consensus pattern: all three bots
bid clubs, the 12-card suit, to $11 or more, one dollar above their lowest
spade bid. The bot still finished 100% sure of spades. Out of sample, the
pattern held in 19 of the 20 v8 and v9 rounds, and the full rule (top bids
plus consensus, `tools/fit_smart_money.py`) named the goal in all 20.

Next: the first-minute buys of the 12-card suit, and selling into fresh bids
before they count. The logs in `data/live_logs_v9.json` hold every quote of
these ten rounds, so both can now be measured offline.

## After v9: the early leaks, replayed

The v9 logs made a new tool possible. `tools/replay_live.py` feeds a logged
round's quotes and trades, in order, to a fresh Python bot with the live
settings, and asks what it believed at every second. At the bot's own trades
the replay matches the live P(goal) to 0.002 at the median, and to within 0.05
for 79% of them. One round drifts further, because v9 logged new quotes but not
withdrawn ones. v0.9.1 logs those too.

* **The hand is not the problem.** Over all 72 logged rounds the dealt hand
  alone named the goal 23 times against 27 expected, and its probabilities are
  calibrated: suits it put at about 37% were the goal 33% of the time.
  figgie.com deals by the standard rules.
* **Selling into fresh bids is not a leak.** Replaying the bot's 76 sells
  into bids with each fresh bid counted as evidence would have stopped none of
  its 6 goal-card sales. In row 5 the hearts were sold while hearts honestly
  looked 6-28% likely. What changed 20 seconds later was the consensus
  completing.
* **Early bids give away the colour, not the suit.** In the first minute the
  other players' highest bid sat on the 12-card suit 40-45% of the time and on
  the goal 15-40%. Of each bot's first $5+ bid of a round, 40% went to the
  12-card suit and 27% to the goal. After 90 seconds the top bid is on the goal
  50-80% of the time. Read as smart money, those early bids cost the bot 0.7-2.2
  nats of belief in the true goal at 30-60 seconds (summed over the ten rounds)
  and pushed it toward the 12-card suit: its P(goal) for the dead suits it
  bought in the first 90 seconds was 0.43, where it would have been 0.32
  without bid reading.

Two fixes, neither adopted:

| Change | Live replay: log-likelihood of the true goal, 10-60 s | Simulator, per round |
|---|---|---|
| phase bid reading in over 90 s | +2.9 nats | −$4.8 to −$30.1 |
| read early bids as evidence about the colour, turning suit-specific over 90 s (`smart_colour_fade`) | +5.3 nats (8 of 10 rounds better) | −$3.6 to −$15.6 |

The simulator's bots bid what their own hands suggest, so their early bids do
point at the goal suit; figgie.com's apparently don't. But ten rounds, one of
which (row 8) supplies most of the live gain, are not enough to overrule a
simulator that punishes the change this hard. `smart_colour_fade` stays off in
both the Python and the JavaScript bot (parity-checked) until the next logged
rounds test it out of sample.


## v9.1: colour reading, out of sample

v9.1 is v9's trading plus logging of withdrawn quotes. It ran to test the
colour reading above on rounds it had not been fitted on.

**v9.1 live: +$551 over 10 rounds (+$55.10/round, ±41)**, all at one private
table. Over the 20 rounds of v9 and v9.1 the same trading made +$1,086
(+$54.30/round).

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | P&L |
|---|---|---|---|---|---|
| ♠ | 1 4 2 3 | 6 0 0 0 | 99% | 11/14/6/5 | +97 |
| ♠ | 2 5 1 2 | 6 0 0 0 | 91% | 11/18/12/17 | +121 |
| ♣ | 5 1 1 3 | 0 6 0 0 | 100% | 11/12/12/15 | +104 |
| ♦ | 2 1 5 2 | 0 0 0 6 | 100% | 9/6/10/17 | +105 |
| ♥ | 5 2 2 1 | 6 0 0 0 | 83% | 15/7/14/10 | −35 |
| ♠ | 4 2 1 3 | 6 3 0 0 | 100% | 14/10/10/10 | +78 |
| ♥ | 4 2 2 2 | 0 0 6 4 | 100% | 11/13/21/11 | +73 |
| ♣ | 3 2 2 3 | 4 0 0 0 | 99% | 13/16/7/11 | −18 |
| ♣ | 4 1 3 2 | 0 6 0 5 | 82% | 6/10/8/7 | +84 |
| ♥ | 2 4 1 3 | 5 4 0 2 | 31% | 15/8/13/7 | −58 |

The goal was the favourite at the bell in 9 of 10 rounds. The three losses:

* Row 5 (−$35): sold both its hearts in the first 100 seconds, at $11 and
  $13, while it put hearts at 8% and 17%; it finished 83% sure of hearts,
  holding six spades.
* Row 8 (−$18): its resting offer sold its last club at $10, 143 seconds in,
  at 51% clubs, to the bot that bid clubs to $16 six seconds later. It ended
  with four spades, the 12-card suit.
* Row 10 (−$58): bought four spades for $40 in the first 70 seconds and sold
  its only heart at $13. Hearts then led at 76-81% for 100 seconds, until 37
  seconds before the bell one bot bid $15 for spades and the bot sold it one.
  That bid alone lifted spades from 10% to 63%: before it, spades' top bid of
  $6 counted 3.3 nats against it.

The consensus held less well this time. In two rounds one bot never bid the
goal above $4 (in row 10 one bot bid nothing all round), and the top bids
plus consensus, scored at the bell by `tools/fit_smart_money.py`, named the
goal in 8 of 10 (v8 and v9: 10 of 10).

**Colour reading passed.** Replayed on the ten new rounds, reading early
bids as evidence about the colour (`smart_colour_fade=90`) raised the mean
log-probability of the true goal over seconds 10-60 in 8 of 10 rounds
(+0.8 nats summed over the rounds). On the v9 rounds it was found on, the
same measure gives +1.6, also 8 of 10. Each bot's first $5+ bid of a round went
to the goal 8 times, to the 12-card suit 9 and to the other colour 12 (v9:
8, 12, 10). Early bids don't single out the goal. In the counterfactual
replay below it adds $1.20 a round. The simulator still says no (its bots'
early bids do point at the goal), so it is on in the figgie.com settings only.

**Replays are as faithful as before.** At the bot's 149 own trades the
replayed P(goal) matches the live one to 0.002 at the median and within 0.05
for 77% (v9: 79%). Logging withdrawals didn't close the remaining gap. It
comes from timing: the live bot acts every quarter second, the replay once a
second.

## Dead cards at the bell

v9 and v9.1 finished their rounds holding 60 cards of suits that were not the
goal, 3 a round (v9.1: 33, among them 4 clubs and 2 diamonds in row 10 that the
bot put at 3% each). Many could have been sold: figgie.com's bots bid $3-5 for
dead suits all round. To price that leak, `tools/paper_bot.py` replays each logged round
through the bot's real decision code with changed settings. It may hit the
logged bids and lift the logged offers of the other players, its paper trades
feed back into its hand and beliefs, and a later live sale of a card it already
sold on paper is struck out. Fills are optimistic (it gets every take it
tries, which the live bot doesn't), so the unchanged bot already scores −$6.30
a round against what really happened, and variants are judged against that:

| Change (20 logged rounds) | vs. unchanged |
|---|---|
| sell a suit below 10% into any $4+ bid | +$0.60/round |
| ... below 20% | −$4.30/round |
| ... below 30% | −$6.40/round |
| ... below 20%, $5+ bids | −$0.20/round |
| ... below 5%, $3+ bids | +$0.30/round |
| waiting premium for dead cards $3 instead of $5 (`hold_dead`) | +$0.20/round |

None clears the noise, and dumping the uncertain suits loses. The bot's
patience sells many of those cards later and dearer, and some "dead" suits
turn out to be the goal. Row 10's clubs show why it holds them: at 7% for most
of the round, four clubs would likely have won the bonus if clubs were the
goal, so it valued the fourth at about $3.50 and wanted more than the $7 bid
it saw. Once a suit is truly dead, in the last half minute, the bids for it
are thin, $1-4. The cheap cards the *other* players dump are a different
matter.

## v10: cheap resale

**The pattern.** In the logged rounds, a card that another player offered
or sold for $1-2 was soon bid back up. With at least 15 seconds to go, a
third player bid $4+ for the same suit within the round in 96% of 166 cases
(v9) and 76% of 135 (v9.1), typically 11-12 seconds later. None of those cheap
cards was the goal. The bot never bought them: a dead card is worth less than
$1 + 20% to it.

**The exploit** (`figgie/patterns.py`, `resale_*` settings). A `ResaleTracker` learns
the pattern within the round. It counts each cheap card (an offer or sale at
$2 or less by another player) as a hit when a different player's real bid
(one that stood or traded) beats it by $2+ within 45 seconds, and as a miss
otherwise. Once two hits are in, the bot lifts cheap offers whose expected
resale gain is at least $0.50:
p(hit) × (cautious resale price − price) − (1 − p(hit)) × price. The cautious
price is the lower quartile of the resale bids seen. With `resale_bid` it also
bids $1-2 for every suit that isn't worth more to it. It sells each resale
card into the first bid that pays that cautious price, at least $2 over cost,
$1 less after 30 seconds, unless the card is worth more to it than the bid.

**Shutting it down when it doesn't work**, which is the other half:

* Its own resales count twice in p(hit), and the market's record counts as
  at most 20 observations, so a pattern that works for others but not for the
  bot fades fast.
* It holds one unsold resale card at a time, plus one per resale that has
  worked (at most two per suit and four in all), and buys none with fewer than
  15 seconds left.
* A resale card unsold after 45 seconds counts as a failure and as a total
  loss. Two more failures than successes, or $6 lost, stops it for the round.
* On figgie.com the record carries over to the next round at half weight, so
  a table where it worked starts warm and one where it failed starts wary.

**Simulator** (`shark` vs. `shark:resale_cheap=2[,resale_bid=true]`, 1,000
paired games per table). `fickle` bots are oracles whose value for each suit
drifts (a mean-reverting $2.50 random walk), which reproduces figgie.com's dead
suits trading at $1-2 one moment and $4-7 the next. `bait` bots are a ring that
knows the goal and fakes the pattern with wash trades among themselves: one
dumps a dead card for $1, another buys it and bids $5 for the suit, a third
sells into that bid, and they never bid for a suit an outsider has bought into.

| Opponents | resale | resale + bids |
|---|---|---|
| `hand`, `counter`, `noise` | +0.07 ±0.06 | +0.12 ±0.16 |
| 3 × `counter` | −0.11 ±0.11 | +0.24 ±0.44 |
| 3 × `oracle` | −0.17 ±0.24 | −0.11 ±0.47 |
| `oshark`, `oracle`, `counter` | −0.16 ±0.14 | −0.05 ±0.30 |
| 3 × `oshark` | 0.00 | 0.00 |
| `spoofer`, `oracle`, `counter` | **+8.66 ±2.30** | **+7.33 ±2.40** |
| 3 × `fickle` | **+1.33 ±0.47** | **+3.87 ±0.82** |
| 3 × `bait` | **−6.45 ±0.68** | **−7.01 ±0.73** |

Neutral where nobody churns dead cards, a gain where they do, and a bounded
loss against the ring. Before the switch was tightened (one card at a time,
the market capped at 20 observations, two net failures) the ring took $17 a
game. Most of what it still takes is indirect: once the bot buys into a suit,
the ring stops bidding for it, so the bot can no longer sell its own dead
cards of that suit into the ring's bids.

**On the logged figgie.com books** the exploit would have made, by the simple
paper trade (`tools/paper_resale.py`: buy cheap offers nobody else took within a second, sell into the
first qualifying bid nobody else had used): +$9.50 a round on the v9 rounds
and +$8.20 on v9.1 with the record carried over between rounds, +$5.90 and
+$3.90 without. By `tools/paper_bot.py` (the bot's own code, no resting bids filled) it is
+$6.60 a round, and with colour reading as well +$8.70. The live settings
are now `smart_consensus=0.8, smart_colour_fade=90, resale_cheap=2,
resale_bid=true`. The JavaScript port matches Python on 292 snapshots and all
600 orders, including 40 turns that traded resale cards.

**v10 live: +$603 over 10 rounds (+$60.30/round, ±34)**, the best 10-round
result yet, at two private tables. A round in between was lost when the page,
hidden behind other windows, stalled for up to 55 seconds at a time and dropped
to figgie.com's login screen; it isn't counted.

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | Resale | P&L |
|---|---|---|---|---|---|---|
| ♣ | 3 4 1 2 | 7 6 0 0 | 61% | 11/8/10/15 | +$8 | +83 |
| ♠ | 3 5 1 1 | 6 4 0 0 | 98% | 10/10/12/15 | +$10 | +128 |
| ♥ | 1 3 4 2 | 0 3 4 0 | 79% | 10/12/10/7 | +$0 | +10 |
| ♣ | 5 2 1 2 | 0 6 0 0 | 100% | 13/23/11/11 | +$13 | +110 |
| ♠ | 1 3 1 5 | 0 0 1 1 | 100% | 17/9/10/7 | +$2 | −4 |
| ♣ | 4 2 1 3 | 4 6 1 0 | 100% | 7/25/6/14 | +$16 | +119 |
| ♣ | 2 3 4 1 | 0 1 6 5 | 91% | 18/13/17/12 | +$14 | −33 |
| ♥ | 2 2 2 4 | 0 3 5 5 | 54% | 13/11/8/10 | +$0 | +43 |
| ♠ | 3 1 4 2 | 5 0 0 5 | 70% | 13/12/12/16 | +$2 | +58 |
| ♣ | 4 2 2 2 | 2 6 0 0 | 100% | 7/20/7/16 | +$8 | +89 |

* **Resale made +$73** (+$7.30 a round, in line with the +$4-9 the paper
  tests predicted): 43 cheap buys at $1-2, mostly in the last two minutes. 41
  were resold, 40 at a profit of $1-4 and one at cost, none at a loss, and 2
  were bought too late to resell. That one slow card was the tracker's only
  failure, so the kill switch never came close to firing.
  It traded in 8 of the 10 rounds. The other two were the quietest, with 13
  and 21 trades all round, and it found nothing to buy.
* **The goal was the favourite at the bell in all 10 rounds.** In the first
  minute 9 of the bot's 24 buys were the goal (v9: 4 of 27), 8 the 12-card suit
  and 7 the other colour. That's what colour reading should do, but ten rounds
  are too few to prove it.
* **The losses:** −$4 when the bot was dealt one goal card (it sold it for
  $17); −$33 when clubs only showed as the goal in the last 30 seconds, after
  the bot had sold its clubs and bought the hearts and diamonds one bot bid
  up to $17 and $12. It still made $14 reselling spades that round.
* **Dead cards at the bell** rose to 4.7 a round (v9: 2.7, v9.1: 3.3). Two of
  the 47 were resale cards; most came from the wrong-suit round above (11) and
  from big holdings of low-probability suits whose offers stayed high, like 5
  diamonds at 5% offered at $17 with seconds left.

## v11: letting go of long shots

v10 kept offering cards of suits it had all but given up on at prices nobody
paid. In its run 8 it held 5 diamonds at 5% and, with seconds to go, offered
them at $14 into $4 bids. That offer came from two places:

* **A lean that never faded.** Up to v10, an offer on a suit that might be
  the goal leaned toward what the card would be worth if it is, by 15% of the
  difference. With five diamonds, the fifth is worth about $60 if diamonds
  are the goal (it decides the bonus), so the lean added $8.56 to a card worth
  $2.90, all the way to the bell. The risk it prices, a lifter who knows
  better, has been priced since v9 by the early-offer rule, which fades as the
  market speaks.
* **A long memory.** To ride out brief dips, the bot holds on with the
  highest P(goal) a suit has had recently, fading with a 60-second half-life.
  Diamonds had looked 26% likely a minute and a half earlier, so 10.5% of the
  $60 still set a $7 floor against the $4 bids, on offers and on selling into
  bids alike.

`tools/paper_bot.py` now has a `--quotes` mode. The bot's own bids and
offers rest in the logged book in place of the live bot's, and fill when
another player's logged order would have crossed them: a bid at or above our
offer, or a trade between others at a price our quote beat. Replayed over
the 30 logged rounds of v9 to v10, against the settings each round ran with:

| Change | With resting quotes | Takes only |
|---|---|---|
| no lean on offers (`adverse_offer=0`) | −$0.07/round | |
| 45-second memory (`sticky_halflife=45`) | +$1.77/round | |
| 30-second memory | +$4.40/round (each 10-round set: +6.20, +4.20, +2.80) | +$2.37/round |
| 20-second memory | +$5.83/round | |
| v11: 30 seconds and no lean | +$4.23/round | |

In one round of the 30 (two at 20 seconds) the changed bot ends with a
different number of goal cards than the unchanged one, which the replay can't
price, because the bonus depends on the other hands. Leaving that round out,
v11 gains +$3.45 a round. On its own the lean hardly matters: the bot mostly
sells long shots into bids once its memory lets go. But with the memory
shortened, the lean is what still pins a late offer: in the unit test a bot
with six clubs at 8% opened at $18 under v10's settings, $14 with only the
lean off, and $11 with both changes.

In the simulator, v11 against v10 (1,000 paired games per table):

| Opponents | v11 − v10 |
|---|---|
| `hand`, `counter`, `noise` | +1.36 ±1.19 |
| 3 × `counter` | +0.42 ±1.14 |
| 3 × `oracle` | +0.35 ±0.45 |
| `oshark`, `oracle`, `counter` | +0.60 ±0.81 |
| 3 × `oshark` | +0.05 ±0.17 |
| `spoofer`, `oracle`, `counter` | −0.71 ±2.05 |
| 3 × `fickle` | **+1.18 ±0.54** |

The memory was set to 60 seconds in v4, before bids had to stand before they
counted (v7). Since then a spoofer barely moves the bot's beliefs, and halving
the memory costs nothing measurable at the spoofing table. Twenty seconds did
even better on the logged rounds. But those rounds are the ones it was chosen
on, so v11 takes the smaller step. The presets of every earlier version keep
60 seconds and the lean (`sharkv10` plays v9 and v10).

**v11 live: +$735 over 10 rounds (+$73.50/round, ±44)**, the best 10-round
result yet, though still within the noise of v9 and v10. It took three
private tables. Twice, under heavy load from other programs on the machine,
the page stalled and figgie.com dropped it to the login screen: once 68
seconds before the end of a round, which isn't counted, and once after the
sixth round. The second round below was played with the page frozen for 140
of its 240 seconds (11 stalls of up to 48 seconds). It is counted.

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | Resale | P&L |
|---|---|---|---|---|---|---|
| ♦ | 1 3 2 4 | 0 0 0 6 | 100% | 12/8/14/21 | +$27 | +132 |
| ♦ | 1 5 3 1 | 5 0 0 1 | 95% | 11/11/13/15 | +$12 | −5 |
| ♥ | 1 4 2 3 | 4 4 1 0 | 98% | 7/11/11/16 | +$20 | −28 |
| ♦ | 1 2 5 2 | 0 0 0 8 | 99% | 10/9/5/9 | +$9 | +113 |
| ♠ | 3 3 2 2 | 6 7 0 0 | 95% | 14/11/5/6 | +$14 | +94 |
| ♠ | 3 5 2 0 | 8 2 0 0 | 100% | 11/9/14/15 | +$4 | +154 |
| ♦ | 4 2 3 1 | 0 0 0 0 | 100% | 12/11/18/16 | +$24 | +23 |
| ♥ | 4 0 4 2 | 0 0 6 0 | 100% | 12/10/23/10 | +$21 | +112 |
| ♠ | 2 5 1 2 | 7 3 0 0 | 95% | 9/11/12/12 | +$2 | +148 |
| ♥ | 2 3 2 3 | 0 5 1 0 | 92% | 15/12/10/16 | +$20 | −8 |

* **Resale made +$153** (+$15.30 a round, twice v10's). There were 76 cheap
  buys at $1-2. 75 were resold, 67 at a profit of $1-13 and 8 at cost, none
  at a loss, after a median 6 seconds. One club, bought with 20 seconds left,
  was still held at the bell. The kill switch never fired: with the record
  carried from round to round, p(hit) stayed at 0.84-0.94. It traded in every
  round, most at the third table (17 and 13 resales in a round).
* **The goal was the favourite at the bell in all 10 rounds** (92-100%). The
  consensus still holds out of sample: the lowest of the three bots' top bids
  was $8-11 for the goal and $3-7 for every other suit, and with it the v8
  rule names the goal in 10 of 10 rounds (v10: 9 of 10;
  `tools/fit_smart_money.py`). In the first minute 14 of the bot's 34 buys
  were the goal, 11 the 12-card suit and 9 the other colour (v10: 9, 8 and 7
  of 24; v9: 4, 13 and 10 of 27).
* **Dead cards at the bell fell to 3.0 a round** (v10: 4.7, v9: 2.7, v9.1:
  3.3).
* **The losses** came from misleading deals and late reveals. −$28 when four
  clubs in hand pointed at spades (clubs as the 12-card suit). The bot bought
  six spades at $3-11 in the first 100 seconds, and hearts were the goal. −$5
  in the frozen round, where five clubs in hand pointed at spades the same
  way; the five spades it bought were dead at the bell, and diamonds were the
  goal. −$8 when clubs looked 55% likely until 65 seconds before the bell and
  hearts were the goal; the bot had sold a heart for $7 at that point.

**What it still gets wrong: late collapses.** In three rounds (2, 5 and 10)
the bot ended with 5-7 cards of a suit that had looked 43-85% likely until
25-65 seconds before the bell and then fell to 4-5%. The 30-second memory
still judged those suits by their recent high, multiplied by what a card is
worth if the suit is the goal: with five in hand, $62, because the fifth card
decides the bonus. In round 2 the bot valued its five spades at $18-29 a card
until the bell and offered them at $23-25 while the bots bid $3-6. In round
10 it held five clubs at $8-14 a card against $3-5 bids.

In the 40 logged rounds of v9-v11, a suit fell from 30% or more to under 15%
within the last 45 seconds 8 times, and it was never the goal. So the memory
could fade to the current P(goal) before the bell. Replayed with
`tools/paper_bot.py` on top of the v11 settings, a linear fade over the last
20-60 seconds adds $0.90-2.00 a round with resting quotes and $1.95-2.70 with
takes only. That's small. A collapse inside the window leaves most of the
premium in place until the last seconds: in round 2 the faded bot still sold
no spades. And it has a cost: in two rounds it sold goal cards into a late
dip (in one v9 round three of them, −$16 to −$21 before any bonus effect).
It isn't worth a version on its own.

Nor does widening the resale exploit pay on the 20 logged rounds that used
it (`paper_bot.py --quotes`). Buying at $3 loses $0.35 a round, holding up to
six cards $0.15, both $0.60. Only buying until 8 seconds before the bell
instead of 15 gains, $1.25 a round. Each remaining leak the logs show is
worth a dollar or two a round, far inside what ten live rounds can resolve
(±$44).

## v12: learning from the tape

Up to v11 every exploit was a rule found by studying figgie.com's bots: the
consensus term, colour reading, "$2 or less resells". From here the aim is to
stop fitting rules to one site's bots and have the bot learn its opponents'
predictable mistakes while it plays, useful from the first round and
adjusting as it goes.

**First try: learning the opponents' tells (not shipped).** A conditional-logit
model added a learned correction to the bot's generic P(goal) (card counting
and the default bid reading, without the figgie.com-only terms), from
features of what each opponent had done: their top bids, cheap offers, cards
accumulated, aggressive buys and sells, plus a term per opponent. It was
refitted at every bell from the revealed goal. Tested predict-then-learn, it
raised the bot's probability on the true goal where opponents have tells
(spoofers: 60% to 71% by rounds 4-10; bots that read bids: 3% to 10%) and
recovered about half of what the figgie.com-tuned terms add within ten
logged rounds. It lost money anyway: −$2.04 a round over 11 simulated tables
in paired 10-round sessions, and nothing measurable on the figgie.com
replay. Small shifts in P(goal), even ones that leave the average accuracy
unchanged, make the bot commit to the right suit a little less often, and the
majority bonus goes to whoever commits early. Against `hand`, `counter`,
`noise` it won the bonus in 68% of rounds instead of 72%, which was the whole
$4 a round it lost there. (Its first version also counted the bot's own
trades as features, a feedback loop: it bought what it believed, then
believed what it had bought.)

**Second try: learned resale (`resale_learn`).** The one learned exploit that
has made money live is resale, so v12 generalises it. A `ResaleLearner`
(figgie/patterns.py, mirrored in the userscript) asks of every offer another
player shows at up to $5: had the bot bought it, would a third player have
bid $2 more for the suit within 45 seconds? The tape answers within seconds,
so every offer at the table is a labelled example, not just the bot's own
trades. An online Bayesian logistic regression (one extended-Kalman step per
example) learns the answer from generic features (the price, whether it is $2
or less, the price against recent trades, recent bids from others, how many
of them bid above it, P(goal), the time, whether the seller keeps dumping),
plus an offset per seller. The bot buys when a lower confidence bound pays,
scaled by how often its own resale buys were bid back up against what the
model predicted for them. The tracker's caps and kill switch stay. The model
carries over from round to round, and in the browser across tables and
reloads; its record of its own resales fades by 30% a round and by half more
at a new table.

Three fixes on the way:

* Letting it buy up to $8 meant reselling goal cards early, before the goal
  was clear: one logged round lost $52. Capping at $5 removed that.
* At first its own resales were one observation among the market's hundreds,
  so the bait ring's fake pattern outvoted them. They now scale the
  prediction instead.
* It kept one open question per seller and suit, replaced on every re-offer,
  so a seller pennying an unwanted suit down counted as one miss at most while
  every resale counted: an optimistic bias. Every offer is now its own
  question.

Paired 10-round sessions at one table (`tools/sessions.py`, 40 sessions per
table, the same deals for both), learned minus hand-built resale, both with
`resale_cheap=2,resale_bid=true`:

| Opponents | learned − hand-built ($/round) |
|---|---|
| `hand`, `counter`, `noise` | +1.20 ±2.10 |
| 3 × `counter` | +1.22 ±2.62 |
| 3 × `oracle` | +0.22 ±1.77 |
| `oshark`, `oracle`, `counter` | −0.36 ±1.62 |
| 3 × `oshark` | 0.00 |
| `spoofer`, `oracle`, `counter` | +2.96 ±4.70 |
| the same, spoofer never spoofs | **+1.90 ±1.81** |
| 3 × `fickle` | **+2.27 ±1.38** |
| 3 × `bait` | **−1.31 ±0.82** |
| `bait`, `bait`, `fickle` | +1.00 ±2.65 |

That's +$0.91 a round on average. On the 40 logged figgie.com rounds, where
the hand-built rule was found, the two come out even
(`tools/paper_bot.py --carry --base resale_cheap=2,resale_bid=true
resale_learn=true`: −$0.33 a round with resting quotes, +$0.53 with takes
only). There the learner rediscovered the hand-built rule by itself: "$2 or
less" got its largest weight, and it learned that resale works better late
in the round. The bait ring still takes more from it than from the hand-built
rule, because the learner's record of its own failures fades between rounds.
The JavaScript port matches Python on 289 snapshots and all 567 orders, with
the learned model equal to the last bit after every turn.

**v12 live: +$799 over 10 rounds (+$79.90/round, ±34)**, the best 10-round
result yet, though still within the noise of v9-v11. The learner started cold
(no saved model) and learned for the rest of the test. It took three private
tables. At the first, the app closed the page after the third round, and the
rounds the runner went on to play there were lost with it. The learner, saved
in the browser, kept what it had learned from them (148 more offers). At the
second, the browser pane was hidden during the second round. The page froze
twice for about two minutes and figgie.com dropped it to the login screen, so
that round isn't counted. The six rounds at the third table ran without a stall.

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | Resale | P&L |
|---|---|---|---|---|---|---|
| ♥ | 2 2 2 4 | 0 0 7 5 | 94% | 17/7/10/10 | +$5 | +86 |
| ♦ | 2 1 5 2 | 0 0 0 6 | 100% | 14/8/10/19 | +$27 | +134 |
| ♥ | 2 2 2 4 | 0 0 6 0 | 100% | 12/8/25/12 | +$19 | +126 |
| ♠ | 4 2 2 2 | 6 6 0 0 | 100% | 13/7/10/7 | +$13 | +69 |
| ♦ | 2 6 1 1 | 3 0 0 0 | 100% | 4/11/5/15 | +$18 | −3 |
| ♣ | 1 2 5 2 | 0 0 0 0 | 100% | 11/16/5/9 | +$12 | +9 |
| ♦ | 3 2 4 1 | 0 0 1 0 | 100% | 18/7/6/16 | +$50 | +43 |
| ♠ | 1 2 2 5 | 5 0 1 0 | 99% | 12/17/15/8 | +$24 | +52 |
| ♠ | 3 4 2 1 | 6 4 0 0 | 100% | 18/6/17/11 | +$27 | +144 |
| ♦ | 2 2 5 1 | 0 0 0 6 | 97% | 12/8/18/10 | +$8 | +139 |

* **Resale made +$203** (+$20.30 a round; v11: +$153). The bot made 111 cheap
  buys and resold 109: 97 at a profit of $1-16 and 12 at cost, none at a
  loss, after a median 8 seconds. Two clubs bought 15-16 seconds before the
  bell were still held at it.
* **Every buy was at $1 or $2.** The learner could pay up to $5, but it never
  judged a $3-5 card worth the risk, so live it played the hand-built rule,
  learned from the tape within the first round. It ended round 1 with 54
  observations, giving a $1 card nobody had bid on yet a 68% chance of
  being bid back up. By the end it had 583 observations and gave 88%. Its own
  resales did at least as well as it predicted (calibration 1.00-1.20 at
  every bell), and the kill switch never fired. Its final weights, on the
  log-odds: "$2 or less" +2.3, −1.5 per $5 of price, +1.8 from the start of
  the round to the end (resale works better late), +0.4 for each other
  player bidding $2 or more above the price, −0.6 for a seller who has
  offered the suit three times in 20 seconds. The per-seller offsets stayed
  small (−0.3 to +0.5).
* **The hand-built rule would have done about as well.** Replayed on these
  ten books (`tools/paper_bot.py --log live_logs_v12.json --carry --base
  resale_cheap=2,resale_bid=true,resale_learn=false resale_learn=true`),
  learned minus hand-built comes to −$1.50 a round with takes only and +$0.90
  with resting quotes. In each case one round that ends with a different
  number of goal cards accounts for most of it. The extra resale income over
  v11 came from the tables: they offered more cards at $1-2 (121 in the ten
  rounds against v11's 94), and about as many of those were bid back up (79%
  against 81%). Against figgie.com's bots the learner matches the rule that
  was found by hand. What it adds is that it got there on its own, and that
  at a table where the rule fails (the simulator's spoofing and bait tables)
  it adjusts.
* **The goal was the favourite at the bell in all 10 rounds** (94-100%). The
  consensus named it in 10 of 10 again: the lowest of the three bots' top
  bids was $7-11 for the goal and $3-6 for every other suit. In the first two
  minutes 23 of the bot's 47 non-resale buys were the goal (v11: 16 of 47).
* **Dead cards at the bell fell to 2.0 a round** (v11: 3.0, v10: 4.7).
* **The two weak rounds** came from misleading deals, as in v11. In the −$3
  round, six clubs in hand pointed at spades (61% at the open). The bot
  bought four spades at $6-9 in the first minute, then sold its one diamond
  for $12 with diamonds at 33%, 137 seconds before the bell. Diamonds were the
  goal; resale's +$18 kept the round near even. In the +$9 round, five
  hearts pointed at diamonds (49% at the open). It bought three diamonds at
  $5-10 and sold its two clubs at $8-9 with clubs at 17-18%, and clubs were
  the goal.

**Fixed after the test (userscript 0.12.1).** The learner keys its
per-seller offsets by seat, so at the second and third tables the new bots
inherited the old ones' offsets (−0.23 to +0.52). They were small, but seat 1
at a new table is a different player. A new table, whether noticed at a round
start or when a saved model is loaded, now drops them. For the Gaussian
posterior that is exact marginalisation (their rows and columns go), and it
leaves the shared weights as learned. The JavaScript parity check now also
covers the learner's round starts: 12 models, each at the same table, at a new
one, and carried over from another page, all equal to the last bit.

## v13: robustness against opponents that fight back

Up to v12 the simulator's opponents were mostly benchmarks the bot was built
to beat. v13 asks how it does against opponents that try to exploit it, or
that are simply as good as it is, and fixes what that turns up, without giving
up what works at figgie.com.

**A test bench first.** `figgie/arena.py` plays shark variants in paired
sessions (several rounds at one table, the same bot objects throughout, so
whatever learns carries over) against 21 tables:
- the old benchmarks;
- strong opponents: earlier sharks, partly informed, and three copies of
  the live bot itself;
- every adversary;
- 3- and 5-player tables.

Seeds come from three disjoint ranges: train to tune, val to choose, holdout
to report once. A variant's score is half its average gain over tables and
half its average over the worst quarter of tables, so a change has to help
broadly. Two changes made the experiments below affordable, both with
results equal to the last bit:
- **Quote reading:** caching each opponent's quote-reading factor, with the
  arithmetic in the same order, made simulated games 2.2-2.7 times faster.
- **Card values:** computing the bonus-contest sums once for the two decks
  that share them made each card valuation a third cheaper.

**New adversaries** (`figgie/adversaries.py`; they see the deck through the
simulator's oracle hook, which the real bot never has):
- **`pump`:** a ring that wash-trades a dead suit at $18 among itself. The
  tape then shows every member paying up for it: a top bid, and a consensus,
  that real trades back.
- **`bait2`:** the bait ring aimed at the learner's $3-5 range, which lets
  the first resales work.
- **`sniper`:** never quotes, and takes a quote only once it has stopped
  moving.
- **`penny`:** outbids every goal bid and undercuts every dead-suit offer by
  $1.
- **`quiet`:** buys the goal without ever showing a bid.
- **`holdout`:** charges more for goal cards the more someone accumulates,
  and bids $1 for dead cards near the bell.
- **`adapt`:** learns over a session what outsiders pay for dead cards and
  quotes just inside it.

The baseline (the live settings, 12 sessions of 4 rounds per table) found
four problems:
- **The pump ring** took $63 a round. The bot was 98% sure of the decoy by
  the 30th second, bought all ten decoy cards and sold its goal cards.
- **bait2** took $17.
- **The strongest opponents** held it to −$7 to +$10.
- **The live settings themselves** lost $6.30 a round on average to the
  plain simulator settings. Switching one signal off at a time pinned it on
  the colour reading (+$8.50 a round off, against +$1 for the consensus).
  Colour reading was shipped in v10 because figgie.com's early bids sit on
  the goal's colour, not the goal. The simulator's informed bots bid the
  goal itself.

**Rejected: smart money that tracks each player's latest valuation**
(`smart_revoke`). An offer or sale well below a player's own earlier bid
withdrew that bid, so a ring dumping its decoy on outsiders while washing it
high keeps cancelling itself. On the 50 logged live rounds it was neutral
until the bell, then cost: the goal was the favourite at the bell in 44
rounds instead of 47. figgie.com's bots do sell goal cards cheaply late (22
of the 23 suits bots paid $8+ for and later sold back down were the goal).
It also wasn't the cure. With market reading switched off entirely, the bot
still lost $48-64 a round to the pump ring. Three colluding players who know
the goal sell it dead cards and buy its goal cards whatever it believes.

**`read_learn`: learning which signals to trust at this table.** A
`ReadingLearner` (figgie/patterns.py) holds two probabilities and updates
each by Bayes at every bell, from the revealed goal:
- **colour:** the early top bid sits on the goal's colour, not on the goal.
  The test is whether the top bid a minute in was on the goal or its partner
  (partner: 50% under colour, 10% under suit).
- **consensus:** the suit every opponent bid up is the goal (right 90% when
  reliable, 25% when not).

Both start at 0.9, drift back toward it by 10% a round and by half at a new
table, and scale the colour reading and the consensus slope. Results:
- **Simulator:** over 8-round sessions it gains +$6.04 a round on average
  across 15 tables, the worst quarter +$0.36, no table clearly worse. Gains
  run up to +$14 against informed bots and +$4 to +$9 against the strong
  tables (self-play: −$0.23).
  Switching both signals off by hand would gain +$8.03, but loses $6.86 a
  round in self-play and gives up what works at figgie.com.
- **Live logs, one bot replayed through all 50 rounds in order:**
  - Consensus stayed at 0.91-0.99: it was right 42 times, wrong once, and
    didn't form 7 times.
  - Colour mostly stayed at 0.83-0.99. Of the early top bids that sat on
    the goal's colour, 12 were on the partner and 11 on the goal (19 more
    sat on the other colour and 8 rounds had none). It dipped once to 0.41
    after a run of rounds where the goal itself was bid first, then
    recovered.
  - Replayed one round at a time from the prior, beliefs barely change: at
    most −0.014 in average log P(true goal), and the goal was still the
    favourite at the bell in 47 of 50 rounds.

**`resale_robust`: a learner that a poisoned tape can't steer.** Two changes
to `ResaleLearner`:
- **Proven bids only.** A bid answers a resale question only once it has
  proved real (the `smart_confirm` rule), or as a trade, so flashed bids no
  longer make cheap cards look resellable.
- **A `held` feature.** It says whether we were long the suit. The market's
  answers come while we're flat, but a resale card is always bought into a
  long position, and the bait rings bid a suit back up only while no
  outsider holds it. Decisions are scored as of after the buy, so the model
  learns from the first failures whether other players' bids depend on our
  position. Where they don't, the weight stays near zero.

Saved v12 models load with the new weight at its prior. Unit tests show both
defences working. In the arena it is neutral: 0.00 on average over 10
tables, nothing significant either way, because the learner rarely buys at
the bait tables in short sessions. On the logged live books it is +$0.78 a
round with takes only and +$1.02 with quotes, mostly from rounds ending with
different goal-card counts. Shipped as a defence.

**Information-aware trading: measured, not built.** `tools/info_value.py`
tells an otherwise identical bot the goal T seconds into the round, on the
same deals. That gain is the ceiling for anything that learns the goal by
then, including trades made only to learn something.

| Table | Told at the open | at 30 s | at 60 s | at 120 s | at 180 s |
|---|---|---|---|---|---|
| `hand`, `counter`, `noise` | +$89 | +$74 | +$68 | +$51 | +$36 |
| 3 × `oracle` | +$24 | +$0.4 | +$0.2 | +$0.4 | +$0.4 |
| 3 × `fickle` | +$11 | +$1 | +$0.4 | +$0.3 | 0 |
| 3 × `oshark` | +$12 | +$4 | +$1 | +$1 | +$2 |
| 3 × the live bot | +$6 | +$7 | +$9 | +$1 | +$1 |
| `oshark`, `oracle`, `counter` | +$30 | +$9 | +$10 | +$8 | +$6 |

Against informed opponents the market hands the bot the goal within about 30
seconds anyway, so a probe could only win back part of the first half-minute.
Against uninformed ones, knowing the goal is worth a lot, but nobody at the
table knows it, so there is nothing to extract. figgie.com's bots converge
on the goal 2-3 minutes in, from the same tape. The one cheap channel, the
evidence in who lifts an early offer, the bot already uses (`fill_lr_offer`).
So no trades purely to learn something.

**Rejected: an endgame and two quoting changes.** Over the arena's 21 tables:
- **`end_horizon`** (60 ticks): +$0.49 a round. Over the last 60 ticks it
  faded the memory of a suit's best P(goal) to today's and shrank the edges
  the bot demands. On the logged live books it added $2.38 a round, but in 9
  of 50 rounds it ended with different goal cards. In one v12 round it sold
  7 hearts the live bot held at the bell, which would have cost the majority
  bonus, and the replay doesn't even count the bonus.
- **`reopen`:** −$0.13 a round, −$10 at the spoofing table. After someone
  else's trade cleared the book, it put our quotes back where they stood.
- **`step_random`:** −$0.26 a round, −$6 at the spoofing table, and no help
  against the sniper. It walked quotes on random ticks.

None was kept.

**The parameters: searched, and left alone.** `tools/optimize.py` searched the
18 parameters that shape quoting, taking and holding. The smart-money
parameters fitted to figgie.com stayed fixed. The search ran in five steps:
1. 32 candidates, each redrawing three parameters from v13's values (half the
   time anywhere in range, half nearby).
2. They played 16 training tables in three halving stages, on fresh deals at
   every stage.
3. The three best were scored on the validation seeds at all 21 tables. Five
   of those tables (self-play, `penny`, `adapt`, `quiet`, five players) the
   search had never played.
4. The best of the three was scored once on the holdout seeds.

Nothing beat the current settings:
- **Training:** every candidate scored below the base at every stage (best
  −0.44).
- **Validation:** the best scored −0.92 (mean +0.07, worst quarter −1.92).
- **Holdout:** the pick (`step_every=3, churn_guard=0.44, take_frac=0.165`)
  made +$0.36 a round on average, within the noise. Its worst quarter was
  −$1.28 and it was clearly worse against the pump ring (−$2.78 ±1.58).

So the hand-tuned values already sit at a robust optimum for this objective,
and v13 keeps them. The run is in `data/optimize_v13.json`. The command was
`python tools/optimize.py --candidates 32` from base
`sharklive:read_learn=true,resale_robust=true`, which is today's `sharklive`.
At the time its self-play tables seated v12 copies, so a rerun now plays
v13 copies there.

The JavaScript port matches Python on 273 snapshots and all 438 orders with
the v13 settings, the learned resale model equal to the last bit after every
turn, at 36 round starts, and for the bid-reading learner over 20 random
12-round histories.

**v13 live: +$989 over 10 rounds (+$98.90/round, ±32)**, the best 10-round
result yet, though still within the noise of v11 and v12. At figgie.com v13
plays almost exactly like v12, by design. The reading learner kept trusting
both signals, and the hardened resale learner bought the same cheap cards. So
the extra $19 a round is the deals and the table, not the changes. All ten
rounds were played at one private table (Bobcat, Bear, Penguin, all Hard).
They started from v12's saved resale model (583 observations, upgraded to the
new layout) and a fresh reading learner. This session wasn't open in any
window, so the browser pane was hidden from the start, and the page stalled
for up to 16 seconds in the first two rounds. From then on a mouse movement
over the page every minute kept it awake, and the last eight rounds ran
without a stall.

| Goal | Dealt ♠♣♥♦ | Final ♠♣♥♦ | P(goal) at the bell | Top bids ♠/♣/♥/♦ | Resale | P&L |
|---|---|---|---|---|---|---|
| ♥ | 2 2 3 3 | 0 0 7 4 | 98% | 13/8/9/6 | +$22 | +144 |
| ♥ | 0 1 3 6 | 0 0 6 0 | 100% | 11/14/21/10 | +$12 | +141 |
| ♣ | 3 2 3 2 | 0 6 0 0 | 100% | 4/23/10/8 | +$20 | +110 |
| ♦ | 2 1 5 2 | 0 0 0 6 | 100% | 6/11/18/22 | +$20 | +152 |
| ♣ | 3 3 2 2 | 2 6 0 0 | 100% | 12/23/8/16 | +$19 | +94 |
| ♣ | 2 4 2 2 | 3 6 0 0 | 98% | 6/11/7/7 | +$19 | +135 |
| ♥ | 2 3 2 3 | 0 0 1 0 | 97% | 7/5/14/13 | +$22 | +34 |
| ♠ | 2 4 1 3 | 6 0 0 2 | 100% | 19/5/9/11 | +$14 | +110 |
| ♥ | 2 3 3 2 | 7 0 6 3 | 100% | 4/10/23/7 | +$15 | +72 |
| ♠ | 2 1 2 5 | 3 0 10 6 | 5% | 8/4/6/13 | +$0 | −3 |

* **Resale made +$163** (+$16.30 a round; v12: +$203). The bot made 95
  cheap buys and resold 93, none at a loss and 2 at cost, after a median 5
  seconds. For the first time the learner paid $3 for a card: twice, and
  both resold for a $3 profit. The new "held" weight, which asks whether a
  suit stops being bid back up once we hold it, dipped to −0.8 after round 1.
  From round 3 it stayed between −0.1 and +0.3: figgie.com's bots don't care
  what we hold, as expected.
* **The bid-reading learner kept trusting both signals.** The consensus
  formed in rounds 1-5 and named the goal every time (trust 0.90 to 0.99).
  The early top bid sat on the goal twice and on its partner twice, so
  colour trust stayed at 0.83-0.99 and ended at 0.97.
* **The goal was the favourite at the bell in 9 of 10 rounds.**
* **The bots went broke, and that cost the last two rounds.** Chips carry
  over at a table, and a player can't bid more than it has. After eight
  rounds the bots had −$31, $43 and $11. From round 7 one of them never bid,
  and in round 10 two of them; trades fell to 21 in round 10 (41-82 a round
  before). That broke both the consensus, which needs every opponent, and
  resale, since nobody could bid cards back up. Rounds 9 and 10 ended with
  10 and 16 dead cards at the bell (rounds 1-8: 1.4 a round). In round 10
  only Bear could bid, and its $13 bid on diamonds pointed the bot at the
  red suits; with five diamonds dealt it bought eight hearts, and spades
  were the goal (−$3). A long run at one table should move to a fresh table
  before the bots run dry.
* **The other weak round** (+$34) was hearts. The bot sold a heart into a
  $14 bid with hearts at 39% (spades 46%) and never contested them; Penguin
  took the bonus.

## 0.13.1: set and forget

The bot is unchanged; the userscript can now be pasted into the console and
left alone. Three things used to need a person:

* **The next round.** Only the table's host, you, can start one. With
  **AUTO** on (the default) the script starts it 8 seconds after the bell,
  with the `newRound` message the host's **New Round** button sends, and asks
  again every 15 seconds until it starts. A table that won't deal another
  round within a minute is left for a fresh one.
* **Broke bots.** Everyone sits down with $350 and chips carry over from
  round to round. figgie.com takes the ante even from a player who can't
  cover it, so a bot's chips can go negative, and nobody can bid more than
  they hold, so a broke bot can only sell. That is what spoiled v13's last
  two rounds. Once any bot ends a round below $100 (two antes), the script
  leaves and opens a fresh private table with as many bots. At $100 a bot
  still has $50 to bid with after the next ante, so this fires well before
  any bot goes negative, and long before the shark could hold $1,300 of a
  table's $1,400. It reads the bots' chips from their seats, where every
  player sees them.
* **Opening a table.** Switched ON at the home screen, it opens one itself
  after a 5-second countdown.

A table move uses the app's own handlers, found in the React fiber tree, so
the site does exactly what it does for a person:
1. the in-game **Leave Game** confirmation, which closes a table no other
   person sits at;
2. **Create New** → **Create Game** (standard), with the bot difficulty set
   to Hard first;
3. **Allow players to join?** → **No**;
4. `addBot` on each empty seat. The full lobby deals by itself after a
   30-second countdown.

Each step has a deadline. If one passes, the panel says why, the script stays
where it is, and it tries again two minutes later. ON and AUTO are remembered
for the tab, so a copy that loads with the page (a userscript manager, or
pasting it again) carries on after a reload.

### Live test (2026-11-16)

| Step | Time |
|---|---|
| Home screen → private lobby with 3 bots seated | 11-27 s |
| Lobby countdown → deal | 30 s |
| Bell → next round dealt | 8 s, trading 6 s later |
| Bell → old table closed → new lobby with 3 bots seated | 15 s |

Rounds, by table (all against Hard bots except where noted):

| Table | How it got there | Rounds (P&L) |
|---|---|---|
| 1 | opened from the home screen | +98, then a page reload mid-round |
| 2 | your own table, rejoined after the reload | −35 (from mid-round) |
| 3 | forced move (Medium bots: the bug below) | +102 |
| 4 | opened from home after another reload | +115, +153, −56, (tab closed) |
| 5 | opened from home on a fresh page | −19, +11, then a chip-based move that crashed the page |
| 6 | opened from home after the crash, with the fix | −32, then a forced move from a hidden pane |
| 7 | that move (bell to trading at the new table: 52 s) | +5, then figgie.com hung on "Logging in as a guest" |
| 8 | opened from home after a reload | |

AUTO started every next round it was asked to (6 of 6). It opened a table
from the home screen six times out of six, and every move reached a new
table except the one that crashed the page.

Tables 5 and 6 (−19, +11, −32) were played in a hidden browser pane, and a
hidden pane starves the page: at one point figgie.com's clock in the page
ran a minute behind the server's. Nothing in the page, the bot included, can
react meanwhile, and its resting quotes sit on the book. The three rounds
played while someone was watching made +98, +115 and +153. Table 4's −56
came between check-ins 1½ minutes apart, when the pane may have been hidden
too. Leave the tab visible.

What broke on the way, and the fixes:
* **A reload took the pasted copy with it** partway through round 2. ON and
  AUTO are now remembered for the tab; after the next reload the new copy
  came back ON by itself and had a Hard table dealing 41 seconds later.
* **The first forced move opened a Medium table.** figgie.com keeps the bot
  difficulty in the page and resets it to Medium on every reload, so "keep
  the last table's difficulty" can't be read from it. Every table the
  script opens now has Hard bots (`cfg.tableBots`).
* **For six seconds into each new round the panel said "Round over −$50".**
  The site's timer-ended flag stays set until the new round's clock starts.
* **A move crashed figgie.com's page** while it was in a hidden pane. The
  old game screen stays mounted until its exit animation finishes, and a
  page you can't see gets no animation frames, so it was still there when
  Create Game emptied the player list; one of its trade buttons then read
  `seatId` of a missing player, and React unmounted the whole page. The
  script now waits until the old game screen is gone before Create Game,
  and delivers any animation frame the page has waited a quarter second for
  from its own clock, so screen changes finish in a background tab too. The
  next move from a hidden pane went through cleanly.
* **figgie.com hung on "Logging in as a guest"** in the middle of a round,
  as it did in earlier tests after the page had been starved, and was still
  hanging 80 seconds later. A reload logged the guest straight back in and
  the script had the next table dealing a minute later. A copy loaded by a
  userscript manager now does that by itself: when the page has hung there
  for 90 seconds, or gone blank for 15, it reloads it (at most once every 5
  minutes). A pasted copy would be lost in a reload, so it says to reload and
  paste again instead.

### 0.13.2: leaving a table in the safe order

The user reported that it still crashed now and then, with no details, and
the crashed tab was gone, so this fix comes from reading figgie.com's code
rather than from a stack trace. figgie.com's game screen crashes the whole
page if it renders while the store's player list is empty: its trade
buttons read the `seatId` of "your player, or else the first player"
(0.13.1's crash). Several socket events replace that list with whatever the
server sends. And the site's own Leave Game, which 0.13.1 called, closes the
table first and changes screens second, so the server's replies to the
closing can arrive while the game screen is still animating out. Its "match
closed" handler then resets the match and navigates home a second time, and
any reply that carries an empty player list crashes it. Whether that
happens depends on timing. A person clicking Leave Game runs the same risk,
but the script leaves a table every five or so rounds.

0.13.2 does it the other way round. It sends the game screen home (the same
navigation Leave Game uses), waits until that screen has unmounted (its
socket listeners go with it), and only then closes the old table and resets
the match. Two smaller changes:
* The animation-frame helper now steps in only once the page has had no
  frame for half a second, so in a visible tab it changes nothing at all.
* Every uncaught error on the page (figgie.com's or the script's) is kept in
  the browser with its stack and what the script was doing
  (`__figgieShark.errors`, and `localStorage['figgieShark.errors']` after a
  reload), so the next crash leaves evidence.

A stress test (2026-11-17, desktop-sized window, a move after every round
and each round ended after 20 seconds of trading) opened 12 tables, 11 of
them by moves, with no crash. It found a second fault, which looks just like
a crash from the user's chair. In the lobby of the 8th table, figgie.com
threw the script back to the home screen. A logger on the socket then showed
that figgie.com's "match closed" message is empty (`onMatchClosed {}`), and
both the lobby and the game screen act on it without asking which table it
was about:
* the lobby says "Match has been cancelled due to inactivity" and goes home;
* the game screen goes home and resets the match.

On the web that message is a browser `alert()`, which freezes the whole
page, script included, until someone clicks OK. Any table this page left
without closing, such as one abandoned by a reload or a lobby it was thrown
out of, is eventually closed by the server "for inactivity". That kicks the
script out of whatever it is playing then, and leaves another abandoned
table behind.

So while ON with AUTO:
* a "match closed" that arrives on the game screen or in a lobby the script
  is opening is ignored, unless this page sent "close" or "leave" in the
  last 10 seconds;
* after closing the old table, the script waits (5 seconds at most) for the
  server's "match closed" before it opens the next one;
* a lobby it is thrown out of, or gives up on, is closed before it opens
  another table;
* figgie.com's `alert()`s go to the console and `__figgieShark.errors`
  instead of freezing the page.

The browser pane went away before these last changes had run through a "match
closed" from an old table; they were written against the captured messages
and figgie.com's code.

## v13.3: quicker takes, and spares of a locked goal

The user noticed three things live: the bot didn't sell into $10+ bids for a
suit it thought unlikely, didn't sell into $10+ bids for the goal while
holding 7+ of it, and didn't buy $1 offers at once. The v12 and v13 logs (20
rounds, every quote and trade, at 1-second resolution; note that any trade
clears the whole book at figgie.com) show how often each happened, and a
replay of the bot at each one shows why:

| Situation | Times | We took it | figgie.com's bots took it | Cleared by another trade |
|---|---|---|---|---|
| $1 offers before the last 15 s | 60 | 37 | 15 | 7 |
| $11+ bids on a suit under 15% likely, cards held | 6 | 4 | 1 | 1 |
| $11+ bids on the goal, 7+ held | 2 | 1 (at $16) | 0 | 1 |

* **The goal with 7+ held.** The unsold one was an $11 bid for the goal
  (99%) with 7 hearts held: the card was worth $9.91 to the bot, and the
  take rule's margin ($1 + 20%) wanted $12.89. Mid-round the waiting premium
  (a goal card "may yet fetch $25 from bonus chasers") would have held out
  for even more. But a goal suit has 8 or 10 cards, so keeping 6 wins the
  bonus outright: with 7 or more, a spare card is worth its payout and no
  more. New rule `locked_sell=7` (live): with 7+ cards of a suit that is 95%+
  the goal, sell into any bid that beats keeping the card by $1, without the
  margin, the waiting premium or the churn guard. In the arena it is neutral
  (−0.03 $/round ±0.05, every table inside its noise), as it should be: the
  simulator's bots seldom bid over $10 for a goal someone has locked.
  figgie.com's bots do.
* **Unlikely suits.** Of the two the bot didn't hit, one was a $12 bid on
  diamonds (19%) with 6 held: if diamonds were the goal, 6 would win the
  bonus outright and 5 might not, which the valuation priced at $11.14 a
  card. Holding was right. The other was an $11 bid 22 seconds in on
  diamonds (14%) with 3 held, where the option value of waiting (dead cards
  still fetch about $5 early in a round) put the card at $10.39; selling
  would have gained about $2 in expectation. Left as it is.
* **$1 offers.** Of the 15 that figgie.com's bots took first, 13 were on
  dead suits in the last 15-30 seconds, about half blocked by the resale cap
  of 2 cards per suit and the rest judged unprofitable by the learner. In 2
  the replayed bot did want the card: a race. The bot's own $1 buys resell
  almost every time, even near the bell (69 of 70, at $2.80-3.60 on
  average). Raising the cap to 3 a suit (or 3 a suit and 6 in all) was
  neutral on average in the arena but lost a little at the tables that bait
  the resale model (baited −0.78, bait-pair −0.99 $/round, inside their
  noise; arena score −0.18 and −0.14), so the caps stay; the fix for $1
  offers is the speed below.
* **Speed.** The userscript looked for trades to take every 250 ms (on a
  200 ms poll), so a new quote could wait up to ~0.45 s. It now weighs each
  new bid or offer the moment figgie.com announces it (`onEventSetTradeValue`).
  Live (2026-11-18), most takes went out 0-3 ms after the quote reached the
  page. Re-valuing on every quote costs the bot 0.4 ms at the 90th
  percentile. What it still loses are races against figgie.com's own bots,
  which run on the server with no network round trip.

### A "match closed" that was meant for us

The live test of v13.3 froze twice, each time just as figgie.com sent its
empty "match closed" mid-round. 0.13.2 had dropped it as "an old table
closing", but the game's clock stopped at that moment and never moved again,
so it was about the table being played. Seen with tables abandoned by page
reloads, it came every five minutes (01:19:59, 01:24:59, 01:30:02),
presumably a server-side sweep of inactive tables that ends the player's
current game too.

So mid-round the message is now held for up to 3 seconds. If the clock ticks
(`onDecrementTimer`) in that time, it was about another table and is
dropped. If not, figgie.com gets it, goes home, and AUTO opens a fresh table.
While a table is being opened, the message goes straight through, and the
existing recovery replaces a lobby the script is thrown out of. As a
backstop, a round whose clock has stood still for 15 seconds, while the page
itself ran smoothly, is left for a fresh table. Live, the third such message
was released after 3 seconds and the script had a new private lobby with 3
bots seated 12 seconds after the clock stopped.

### Live test (2026-11-18)

Eleven rounds against Hard bots, unattended once started, at three tables
(the script opened all three itself, and moved from the second to the third
when a bot ended a round under $100):

| Table | Rounds (P&L) |
|---|---|
| 1 | +86, −38, then figgie.com: "You are logged in on another device" |
| 2 | +119, +104, −17, +85, +135, then a move (a bot under $100) |
| 3 | +17, +157, +111, +51 |

+$810 in all, +$73.6 a round (±37), inside the noise of v13's +$98.9 (±32).
In all 9 rounds whose bell was recorded, the bot's favourite was the goal (at
P ≥ 0.98). In 6 of them it held 6-8 of its cards (+$85 to +$157); in the
other 3 it held none (−17, +17, +51).

* **The locked goal.** Holding 7 spades at P(goal) 1.0, four seconds from the
  bell, it sold the spare into an $11 bid: what the old margin would have
  refused below $13.
* **$1 offers.** At tables 2 and 3 others offered 55 cards at $1. The bot got
  18, figgie.com's bots 16, and another trade cleared the book before anyone
  took the other 20 or so. The bot's $1 fills landed a median 170 ms after
  the offer appeared (p90 484 ms), counting the round trip to the server.
* **A bug the test found.** At table 3 only 4 of 265 takes went out within 5
  ms of their quote. That copy had loaded before the socket connected, so its
  quote listener ran before the store's and looked at a book without the new
  quote, which then waited for the 250 ms check. The reaction now runs as a
  microtask after every listener. Patched into the running page, 44 of the
  next 49 takes went out within 50 ms (most 5-12 ms).
* **"You are logged in on another device"** (01:41, table 1): the same guest
  account connected elsewhere, or a reconnect counted as one, and figgie.com
  dropped the page to its login spinner. The script logged the pop-up instead
  of freezing on it and, a pasted copy, could only say "reload". A copy in a
  userscript manager reloads after 90 seconds there.