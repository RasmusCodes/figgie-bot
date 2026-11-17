# figgie-bot

A bot for **Figgie**, Jane Street's card-trading game. It counts cards with
exact Bayesian inference over the 12 possible decks, reads what the other
players' bids give away, values every card including its effect on the
majority bonus, and market-makes on those values. It also learns, as it
plays, which of the other players' offers are mispriced (cards dumped that
someone soon bids back up), from every offer it watches rather than from rules
fitted to one site's bots, and trades against them, with a kill switch for
when that stops paying or someone baits it. And it learns from each round's
revealed goal how far to trust its ways of reading the market at this table,
so a signal that works at figgie.com but is faked or wrong elsewhere fades.

* **Live on [figgie.com/play](https://www.figgie.com/play/)**, as a userscript
  that trades your seat at a private table of figgie.com's own bots.
* **In a Python simulator** (pure standard library) for benchmarking against
  other bots, including adversaries written to exploit it.
* **2 to 5 players** (the official game is 4 or 5).

The live bot is a line-for-line JavaScript port of the Python one; a test
harness confirms the two produce identical numbers and identical orders.

---

## Results

### Live, against figgie.com's Hard bots

Private tables (no humans allowed), three figgie.com bots on **Hard**, P&L
per 4-minute round including the $50 ante:

| Version | Rounds | Total | Per round | ±95% | What changed |
|---|---|---|---|---|---|
| v1 | 9 | −$261 | −$29.0 | ±35 | exact card counting, naive market-making |
| v2 | 7 | +$174 | +$24.9 | ±45 | reads the highest bids ("smart money"); patient quoting |
| v3 | 10 | +$423 | +$42.3 | ±35 | won't sell a card before the market reveals the goal |
| v4 | 5 | +$271 | +$54.2 | ±64 | steadier reactions to a jumpy signal |
| v5 | 10 | +$159 | +$15.9 | ±44 | chases the 6th goal card (rivals consolidate the rest) |
| v6 | 10 | +$360 | +$36.0 | ±45 | ... but only once it holds half the goal suit |
| v7 | 10 | +$475 | +$47.5 | ±45 | bid reading fitted to 42 logged live rounds; spoof-resistant; 2-5 players |
| v8 | 10 | +$335 | +$33.5 | ±34 | on figgie.com, also weighs whether *every* opponent bid a suit up |
| v9 | 10 | +$535 | +$53.5 | ±41 | early offers priced for who lifts them; full round logs |
| v9.1 | 10 | +$551 | +$55.1 | ±41 | v9 again, out of sample; also logs withdrawn quotes |
| v10 | 10 | +$603 | +$60.3 | ±34 | cheap resale with a kill switch; early bids read by colour |
| v11 | 10 | +$735 | +$73.5 | ±44 | lets go of suits it has given up on sooner |
| v12 | 10 | +$799 | +$79.9 | ±34 | learns which cheap offers resell, from the tape |
| **v13** | 10 | **+$989** | **+$98.9** | ±32 | learns which market signals to trust at a table; resale learner hardened |

Since v3 it has been profitable in every 10-round test, and v8 to v13 ended
68 of their 70 rounds with the true goal as their favourite (v7: 74% on the
goal at the bell on average).

v13's +$98.90 a round is the best so far, $16.30 of it from reselling cheap
cards (+$163: 93 resales, none at a loss). But it is still inside the noise
of v11 and v12: ten rounds is a small sample, and once the goal is known the
deal decides much of the round. At figgie.com v13 plays almost exactly like
v12, by design:
- **Reading learner:** it kept trusting both of the site-fitted signals
  there (consensus 0.99, colour 0.97 after ten rounds).
- **Resale:** the hardened learner bought the same $1-2 cards, plus two at
  $3.

All ten rounds were at one table, and by the last two the bots were nearly
broke. Chips carry over, and a bot can't bid more than it has. The market
thinned, and those two rounds made +$72 and −$3. v12 had learned the "$2 or
less" resale rule from the tape in its first round, and on the same books
the hand-built rule makes about as much. Round-by-round tables and the
reasoning behind every change are in [docs/HISTORY.md](docs/HISTORY.md).

### Simulator

Mean P&L per game in $, 2,000 games per row on identical deals for both
versions, seats shuffled every game. The last column is the paired
difference with its ±95%; bold where it is clear of zero:

| Opponents (table size) | v8 (`sharkv8`) | v9 (`shark`) | v9 − v8 |
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

The spoofer row is mostly a quirk of that opponent (v9 keeps dead cards long
enough to sell them into its flashed bids; see the history).

v10's cheap-resale exploit (`resale_cheap=2`, with `resale_bid=true` also
bidding for dumped cards) against v9, 1,000 paired games per row:

| Opponents (4 players) | resale | resale + bids |
|---|---|---|
| `hand`, `counter`, `noise` | +0.07 ±0.06 | +0.12 ±0.16 |
| 3 × `counter` | −0.11 ±0.11 | +0.24 ±0.44 |
| 3 × `oracle` | −0.17 ±0.24 | −0.11 ±0.47 |
| `oshark`, `oracle`, `counter` | −0.16 ±0.14 | −0.05 ±0.30 |
| `spoofer`, `oracle`, `counter` | **+8.66 ±2.30** | **+7.33 ±2.40** |
| 3 × `fickle` (dead suits churn, as at figgie.com) | **+1.33 ±0.47** | **+3.87 ±0.82** |
| 3 × `bait` (a ring built to exploit it) | **−6.45 ±0.68** | **−7.01 ±0.73** |

It is off by default in the simulator and on in the figgie.com settings.

v11 against v10 (1,000 paired games per table): +1.36 ±1.19 against `hand`,
`counter`, `noise`; +0.42 ±1.14 against 3 × `counter`; +0.35 ±0.45 against 3
× `oracle`; +0.60 ±0.81 against `oshark`, `oracle`, `counter`; +0.05 ±0.17
against 3 × `oshark`; −0.71 ±2.05 at the spoofing table; **+1.18 ±0.54**
against 3 × `fickle`.

v12's learned resale (`resale_learn=true`) against v11's hand-built rule, both
with `resale_cheap=2,resale_bid=true`, in sessions of 10 rounds at one table
(the learner keeps what it learns from round to round; `tools/sessions.py`,
40 sessions per table, paired on the same deals):

| Opponents (4 players) | learned − hand-built |
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

Replayed over the 40 logged figgie.com rounds, where the hand-built rule was
fitted, the learned one comes out even with it (−$0.33 a round with resting
quotes, +$0.53 with takes only).

v13's two additions against v12's figgie.com settings (`sharkv12`) in the
arena (`figgie.arena`, 12 sessions of 8 rounds per table, training seeds), $
per round:
- **`read_learn=true`** (learn which market signals to trust here): **+6.04**
  on average over 15 tables, the worst quarter +0.36. Against 3 × `oracle`
  **+13.7**, 3 × `counter` **+13.8**, `oshark`, `oracle`, `counter`
  **+9.4**, `holdout` **+10.6**, 3 × `fickle` **+8.4**, 3 × `oshark`
  **+4.2**, three copies of the live bot −0.2. On the 50 logged live rounds
  it leaves the beliefs as they were.
- **`resale_robust=true`:** 0.00 on average over 10 tables, a defence rather
  than a gain.

A seeded search over the quoting, taking and holding parameters
(`tools/optimize.py`: 32 candidates, successive halving on training seeds,
choice on validation seeds including five unseen tables, one holdout report)
found nothing that beats the current values robustly. Its pick made +$0.36 a
round on the holdout seeds but −$1.28 over its worst quarter of tables, so the
parameters stay. The details, and what else was tried and dropped (an endgame
wind-down, quotes put back after a clear, random quote timing, wash-proof
smart money, trades made only to learn something), are in the history.

Opponents: `noise` (random), `hand` (prices off its own hand only),
`counter` (the same exact card counting, naive pricing), `oracle` (a counter
told the goal at the deal 60% of the time: it bids the goal into the teens and
dumps the rest), `oshark` (the v4 shark plus a strong hint of the goal half
the time: informed *and* chasing the bonus), `spoofer` (an oracle that
always knows the goal and flashes $20 bids on a dead suit to mislead
bid-readers), `fickle` (an oracle whose value for each suit drifts, so dead
suits trade at $1-2 one moment and draw $4-7 bids the next) and `bait` (a ring
of oracles that fake the resale pattern with wash trades among themselves and
never bid for a suit an outsider has bought into). v13 adds adversaries
(`figgie/adversaries.py`): `bait2` (the bait ring aimed at the learner's
$3-5 range, letting the first resales work), `pump` (a ring that wash-trades
a dead suit at $18 among itself, so every member shows a high price on the
tape, and sells it to whoever believes them), `sniper` (never quotes, and
takes a quote only once it has stopped moving), `penny` (front-runs every
goal bid and dead-suit offer by $1), `quiet` (buys the goal without ever
showing a bid), `holdout` (prices the bonus fight: the more someone
accumulates the goal, the dearer its goal cards) and `adapt` (learns, over a
session, the prices outsiders pay and quotes just inside them). All but
`noise`, `hand` and `counter` see the deck, so they exist only in the
simulator; none of that can reach the real bot, which never gets the oracle
hook.

---

## Is it unbeatable? No.

Figgie is a game of hidden information for up to five players, traded in a
continuous double auction; there is no known way to compute an equilibrium,
and this bot does not try. It is a Bayesian trader with tuned heuristics, and
it has exploitable habits. The known ones, with what they cost:

* **Its bid reading can be lied to.** The bot treats the highest bid on a
  suit as evidence that the suit is the goal. v7 limits the damage: a bid
  only counts once the bot has seen it standing in two different seconds of
  the round, seen it outbid, or seen it survive until a trade clears the book
  (`smart_confirm`), and until then the bot trades against it on its old
  beliefs, so it happily sells a dead card into a flashed $20 bid. Without
  that check the same signal lost $13 a round; with it v7 lost about $4 to
  the `spoofer` above, and v9, which holds its cards longer early, makes
  $14.6 a round *more* at the spoofing table than at its honest twin. A
  spoofer willing to leave its bids up for longer, and risk being hit, can
  still move it.
* **Colluders can fake the market with real trades.** The `pump` ring
  wash-trades a dead suit at $18 among itself, which no confirmation rule
  can tell from real buying. The v12 bot was 98% sure of the decoy after 30
  seconds and lost $63 a round. v13 learns at the bell that the consensus
  lied at this table and stops trusting it within a round or two
  (`read_learn`), but three colluders who know the goal still take about $60
  a round: they sell it dead cards and buy its goal cards whatever it
  believes, and with its market reading switched off it loses $48-64.
* **It trades before the market has spoken.** By the bell it knows the goal
  (v8-v9.1: the favourite in 29 of 30 live rounds), but the clearest signal,
  every bot bidding the goal up, only appears 2-3 minutes into a round. Until
  then it trades on its hand and on single bids, and the logs show where
  that goes wrong. v9's first-minute buys were mostly dead cards: 23 of 27, 13
  of them the goal's plentiful same-colour partner. figgie.com's bots bid that
  partner as often as the goal early on, and the bot read their bids as
  pointing at a suit when they only point at a colour. On figgie.com v10 reads
  early bids as evidence about the colour (`smart_colour_fade`): replayed, that
  improved its belief in the true goal in 8 of 10 rounds both on the v9 rounds
  and on ten new ones. It costs about $8 a round in the simulator, whose
  bots bid the goal itself, so since v13 the bot learns at each bell whether
  this table's early bids point at the colour or at the suit (`read_learn`)
  and fades the colour reading where they point at the suit. Early *offers*
  are priced for informed buyers (v9).
* **One late bid can flip its favourite.** 37 seconds before the bell of a
  v9.1 round, one bot's $15 bid for a dead suit (the bot sold it a card) moved
  that suit from 10% to 63%, because before it the suit's low top bid had
  counted 3.3 nats against it. That round was lost earlier, but a bot that
  bid like that on purpose could mislead it near the end.
* **Its resale buying can be baited.** The `bait` ring above fakes the
  pattern and never bids for a suit the bot has bought into, which costs it
  about $6.50 a game. The kill switch caps the cards at one, but the ring's
  lost bids for the bot's *own* dead cards are a cost it can't see.
  figgie.com's bots don't adapt like that. v12's learner sees the ring's
  pattern work for everyone but itself and scales its odds down after a
  couple of failed resales, but it forgets part of that between rounds, so
  the ring still takes $1.30 a round more from it than from the hand-built
  rule. v13's learner (`resale_robust`) counts only bids that proved real,
  and learns whether other players' bids depend on its holding the suit,
  which is exactly the ring's trick. It is neutral in the arena, because in
  short sessions the learner rarely buys from the rings at all.
* **It ends rounds holding dead cards**, three a round in v9, v9.1 and v11,
  nearly five in v10 and two in v12. Dumping uncertain suits early loses, because some
  turn out to be the goal. v10 also clung to suits it had given up on; v11
  drops the lean on its offers and halves its memory of a suit's best
  P(goal), which brought the count back to three. What's left is mostly suits
  that collapse in the last half-minute: the memory still values them by
  their recent high, so live it held five spades at 4% offered at $23-25 into
  $3-6 bids. Fading the memory before the bell is worth only $1-3 a round on
  the logged books, and it sometimes sells a goal card into a late dip.
* **The bonus premium is a known price.** Holding half the goal suit, it
  values the deciding card at up to $60 and will pay up to about $39 for it
  (its $50 × P(goal) cap binds first), because live, rivals always collected
  the strays. An opponent that holds
  those strays and knows nobody else is chasing could sell it that card dear.
* **Its quoting is predictable.** Bids open at 30% of the limit and rise $1
  every 3 seconds, which tells a patient reader roughly what it will pay.
  Walking on random ticks instead didn't help against the `sniper`, and cost
  $6 a round at the spoofing table, so it stays.
* **Informed bonus-chasers break even with it.** Against three `oshark`s (who
  usually know the goal) it makes about $0 a round, and about the same
  against three copies of itself.

---

## Play it on figgie.com

1. Open <https://www.figgie.com/play/> and click **Play as Guest**.
2. Open the browser's console (F12 → **Console**), paste the whole of
   [`web/figgie-shark.user.js`](web/figgie-shark.user.js) and press Enter.
   Chrome asks you to type `allow pasting` the first time.
3. In the **Figgie Shark** panel (bottom right) switch **ON**.

That's all. With **AUTO** on (the default, next to ON) it:
* opens a private table with three Hard bots by itself, if you switch ON at
  the home screen (after a 5-second countdown);
* starts each next round 8 seconds after the bell;
* moves to a fresh private table with as many bots once one of them ends a
  round below $100. Everyone sits down with $350, chips carry over from round
  to round at a table, and a bot can't bid more than it has, so after five or
  six rounds against the shark the market dries up.

So it plays until you switch it OFF (it cancels its resting quotes) or close
the tab. A pasted script is gone when the page reloads; paste it again and it
carries on (ON and AUTO are remembered for the tab).

While it's ON with AUTO it also keeps figgie.com from interrupting the run:
the site announces some things (such as an old table being closed for
inactivity) with a browser pop-up that freezes the page until someone clicks
OK, and acts on "match closed" messages meant for other tables by throwing
you out of the one you're playing. The script logs those pop-ups instead and
ignores the stray messages.

For runs nobody watches, install it with a userscript manager instead
([Tampermonkey](https://www.tampermonkey.net/) or
[Violentmonkey](https://violentmonkey.github.io/): create a new script,
replace its contents with the file, save). Then it loads with every page, and
it gets figgie.com back on its feet by itself: if the site's page crashes
(goes blank) or hangs on "Logging in as a guest", it reloads the page, which
logs the guest straight back in, and opens the next table. The one thing it
can't do for you is log in: if figgie.com asks you to **Play as Guest**,
click it and it picks up from the home screen.

To pick the table yourself, do it before switching ON (or with AUTO off):
**Create New** → **Standard** → **Create Game**, then in the lobby set
**Allow players to join?** to **No**, pick a **Bot Difficulty**, click **+**
on the empty seats to add figgie.com bots, and click **Are you ready?** It
plays any table where every other seat is a figgie.com bot. The tables it
opens itself have Hard bots.

From the console:

```js
__figgieShark.enabled = true              // the same as switching ON
__figgieShark.autoNext = false            // AUTO off: no next rounds or new tables
__figgieShark.freshTable = false          // next rounds, but stay at this table
__figgieShark.cfg.freshTableBelow = 60    // move on below $60 instead of $100
__figgieShark.cfg.tableBots = 'medium'    // bots at the tables it opens
__figgieShark.resetLearner()              // forget what it has learned
__figgieShark.errors                      // page errors, with what it was doing
```

If figgie.com's page ever crashes or misbehaves, `copy(JSON.stringify(__figgieShark.errors))`
in Chrome's console copies the last 30 errors (figgie.com's or the script's,
with stack traces and what the script was doing at the time). They are kept
in the browser, so after a reload `localStorage['figgieShark.errors']` still
has them.

The panel shows the bot's live P(goal) for each suit (in figgie.com's order,
♠ ♣ ♦ ♥), the highest bid any
other player has shown for it, what the next card is worth to the bot (`buy`)
and what it would give up by selling one (`sell`), its last few trades, the
state of the resale exploit (on or off, cards held, resales that worked and
failed, its P&L so far, and how many offers the learned model has watched, the
chance it gives a $1 card of being bid back up, and how its own resales have
compared), and the round's P&L when the bell rings, with AUTO's countdown to
the next round or table and a running total for the page.

**Leave the tab visible** (a window of its own is fine). Its trading clock
runs in a Web Worker, which browsers don't throttle, and it supplies the
animation frames a hidden page doesn't get, so a background tab still
changes tables. But a page the browser starves can't react to the market:
in testing, a hidden page fell up to a minute behind figgie.com's clock
while its resting quotes sat on the book, and its rounds suffered. Nothing
runs while the computer sleeps. What the learners have learned is saved in
your browser, so it keeps learning across tables and reloads;
`__figgieShark.resetLearner()` starts it over.

### Fair play

* **Bots only.** It trades, starts rounds and opens tables only when every
  other seat is a figgie.com bot, and the tables it opens are private
  (**Allow players to join?** No). If a person is seated, or a bot is
  standing in for one, it stands by.
* **Only what you can see.** It uses your own hand, the bids and offers, the
  trade tape, the clock, and each seat's name, chips (shown on every seat)
  and whether it is a bot. The web client's state holds more than that; the
  bot reads the `deck` only for the goal suit after the bell, when the site
  shows it to everyone, and nothing else about the other players.
* **Human speed.** At most 4 orders a second, through the same store
  functions the site's own Bid / Offer / Buy / Sell / Cancel buttons call.
* Keep it to private tables and guest accounts, away from ranked play, and
  check figgie.com's terms before automating anything there.

### How it hooks into the site

figgie.com is an Expo / React Native Web app talking socket.io to
`figgietable.com`. The adapter:

* finds the app's MobX game store as the value of a React context provider
  (a short walk of the fiber tree from `#root`; nothing global is patched);
* reads `tradeRow` (the book), `tradeHistory` (the tape, stored newest-first),
  `timeLeftInMatch`, and your own player's `startingHand` / `currentHand` /
  `chipCount`;
* listens to the socket's `onEventCompleteTrade` (suit, price, buyer and
  seller seats only) so every fill reaches the bot in order;
* sends orders with `setTradeValue`, `completeTrade` and `cancelTrade`,
  applying the same checks as the UI (prices 1-99, bids must beat the bid,
  never crossing its own quotes);
* maps the round clock onto the simulator's 240-tick schedule, and accepts
  tables of 2-5 players (figgie.com itself requires 4 or 5);
* starts the next round with the socket's `newRound` (what the host's **New
  Round** button sends), and opens tables through the app's own handlers,
  found the same way in the fiber tree: the in-game **Leave Game**
  confirmation, **Create New** → **Create Game**, the lobby's **Allow players
  to join?** toggle, and `addBot` for each empty seat. The lobby deals on its
  own once it is full;
* wraps `requestAnimationFrame` so that, once the page has had no frame for
  half a second (a hidden tab), a frame it has waited a quarter second for
  is delivered from the script's clock instead: figgie.com only removes the
  old screen when its exit animation has run, and creating a table under a
  still-mounted game screen crashes the app;
* leaves a table by sending the game screen home first and closing the
  table once that screen is gone (figgie.com's own Leave Game does it the
  other way round, which can crash the page);
* while ON with AUTO, wraps the socket's incoming-event dispatch to drop
  figgie.com's empty "match closed" messages that arrive mid-game or in a
  lobby it's opening (they're about other tables), and turns `window.alert`
  into a log entry.

It was written against figgie.com web **v1.3.7.1** (November 2026). It relies
on the app's internals, so a site update can break it; the panel then reports
an error or "Waiting for figgie.com to load" instead of trading.

---

## How the bot thinks

**1. Count cards exactly.** P(deck | everything public) over all 12 decks.
Your hand gives a multivariate-hypergeometric likelihood. The tape adds hard
facts: nobody can sell a card they don't hold, and a resting offer proves the
offerer holds the suit. Those lower bounds are scored exactly, one suit at a
time. If 11 spades are proven to exist, spades is the 12-card suit and clubs
is the goal, with certainty. With three players one card is dealt to nobody,
and the counting accounts for it.

**2. Follow the smart money.** For each suit it keeps the highest price any
other player has bid or paid and the lowest price anyone has offered or sold
at. Fitted to the 42 live rounds logged against figgie.com's bots, a top bid
counts against a suit at 0.3 nats per $ below $17 and for it at 0.8 nats per $
above (a suit nobody has bid on scores like a $4 bid); a bottom offer under $5
counts against it. Bots there bid $10-15 on dead suits all the time, so only
the highest bids single out the goal. A bid counts only once the bot has seen
it standing in two different seconds of the round, or seen it outbid or
cleared by a trade.

On figgie.com it also weighs *consensus*: the lowest of the opponents' own
top bids on a suit (0.8 nats per $ above $5, capped at 4). In the 10 v7
rounds where the pattern was found, every Hard bot bid the goal suit up to
$7-10 at some point while no dead suit drew more than $3-6 from all three.
Out of sample, together with the top bids, it named the goal in all 20 v8 and
v9 rounds and in 8 of the 10 v9.1 rounds (twice one bot never bid the goal
above $4). One bluffer can't fake it. The simulator's bots don't behave that
way, so it is off there (`smart_consensus`);
[tools/fit_smart_money.py](tools/fit_smart_money.py) reproduces the fit from
[data/live_rounds.json](data/live_rounds.json). Also on figgie.com only, bids
in the first 90 seconds count as evidence about a suit's colour, split between
it and its same-colour partner, turning suit-specific in 5% steps
(`smart_colour_fade=90`).

**2b. Read hands from quotes, a little.** Each opponent is also modelled as
valuing a suit at about $20 × P(goal | their hand); summing over every hand
they could hold turns their latest quotes into a likelihood for each deck,
tempered by `read_weight`.

**3. Value cards including the bonus.** A goal card pays $10, and the rest of
the pot goes to whoever holds the most goal cards. For each deck the bot
enumerates how the unseen goal cards are split between the other players,
consistent with the tape, and scores its bonus share. Early on the race is
still open, so the share uses a Tullock contest `k^a / (k^a + Σ y^a)` whose
sharpness `a` grows from 3 to 40 over the round, ending at winner-takes-all.
Buying a goal card from the bonus leader is worth more than buying it from
someone with none, and the bot prices that. Once it holds half the goal suit
it values the bonus as if every goal card it lacks ends up with one rival,
which is what makes the 6th card of a 10-card goal worth chasing.

**4. Trade.**

* **Take:** cross the spread for the single best mispriced bid or offer, worth
  at least $1 + 20% after pricing that specific counterparty, never paying
  more than $50 × P(goal), never selling below 60% of what it paid while the
  suit still has a 15%+ chance of being the goal, and never selling below the
  option value of waiting for the market to reveal the goal. Both judge a suit
  by the highest P(goal) it has had lately, a memory with a 30-second
  half-life (`sticky_halflife`), so a brief dip doesn't trigger a dump.
* **Quote** every suit inside its value, giving up 20% + 15% (adverse
  selection) + $1 on bids and 20% + $1 on offers. Open at 30% of the limit on
  an empty book, step up $1 every 3 seconds, penny competitors, never pay
  through value. Up to v10, offers on a suit that might be the goal also
  leaned toward what the card would be worth if it were (`adverse_offer`).
  v11 leaves that risk to the rule below.
* **Early offers expect an informed buyer.** In the first minutes, whoever
  lifts an offer usually knows more than the bot, so each offer asks at least
  what keeping the card is worth *given that someone lifted it*: the lift
  counts as evidence for the goal with likelihood ratio 3 at the open, fading
  with a 60-second time constant (`fill_lr_offer`, `fill_tau`).
* **Near a majority** the next card is worth more than the last one. There it
  prices both sides off the chord, so its own bid and offer never cross.

**5. Exploit what repeats, and stop when it stops working.** figgie.com's
bots dump dead cards for $1-2 and, within seconds, bid them back up to $4+
(with 15+ seconds left: after 96% of the cheap cards in the v9 logs, 76% in
v9.1). A `ResaleTracker` ([figgie/patterns.py](figgie/patterns.py)) learns that
pattern as the round goes: it scores each cheap card as a hit or a miss by
whether another player's real bid follows within 45 seconds. Once the pattern
has shown up twice, the bot buys cheap offers worth at least $0.50 in expected
resale and sells each card into the first bid that pays the lower quartile of
the resale prices seen (`resale_cheap`; with `resale_bid` it also bids $1-2 for
the suits it doesn't want). Its own resales count double in the odds and the
market's record counts as at most 20 observations. It holds one unsold resale
card, plus one per resale that has worked, and buys none in the last 15
seconds. After two more failures than successes, or $6 lost, it stops for the
round. The record carries into the next round at half weight.

Since v12 (`resale_learn`) it learns the pattern instead of being told it. A
`ResaleLearner` treats every offer another player shows at up to $5 as a
question the tape answers within seconds: had it bought that card, would a
third player have bid $2 more for the suit within 45 seconds? An online
Bayesian logistic regression learns the answer from generic features (the
price, whether it's $2 or less, the price against recent trades, recent bids
and how many players bid above it, P(goal), the time, whether the seller keeps
dumping), plus an offset per seller. Every offer it watches is an
observation, so it is learning from the first minute of its first round at a
table. It buys when a cautious (lower-bound) estimate pays, scaled by how its
own resales have done against the model's predictions, so a pattern that works
for others but not for it shuts it down; the caps and kill switch above still
apply. The model stays with the bot from round to round and, on figgie.com,
from table to table (saved in the browser). The per-seller offsets are keyed
by seat, so a new table drops them. On figgie.com's logged rounds, and live in
v12, it rediscovered the "$2 or less" rule by itself. Since v13
(`resale_robust`) only bids that proved real answer its questions, and a
"held" feature lets it learn whether other players' bids depend on its
holding the suit, judging every buy as of after it.

### Which signals to trust (v13)

Two of its readings of the market were fitted to figgie.com's bots: reading
early bids as evidence about a colour rather than a suit, and the consensus
(every opponent bidding the same suit up). Elsewhere they can be wrong, or
faked. A `ReadingLearner` (`read_learn`) keeps a probability for each, "early
bids point at the goal's colour, not the goal" and "the suit everyone bid up
is the goal", and updates them by Bayes at every bell from the revealed goal.
Each probability scales its signal. They start at 0.9, so at figgie.com it
plays as before, and drift back toward that a little every round, so a table
that changes its ways can win the bot back. Replayed through the 50 logged
figgie.com rounds in order, it kept trusting the consensus (0.91-0.99) and,
but for one brief dip, the colour reading.

---

## Python usage

Pure standard library, Python 3.10+.

```bash
python -m figgie watch --lineup shark,hand,counter,noise --seed 7
```

```bash
python -m figgie bench --lineup shark,hand,counter,noise --games 2000
```

```bash
python -m figgie.compare "sharkv8" "shark" --games 600 --fields mixed,counters,oracles,spoofed,unspoofed
```

```bash
python tools/replay_live.py --trace 8
```

```bash
python tools/paper_bot.py resale_cheap=2 resale_bid=true
```

```bash
python tools/sessions.py "shark:resale_cheap=2,resale_bid=true" "shark:resale_cheap=2,resale_bid=true,resale_learn=true" --sessions 40
```

```bash
python -m figgie.arena sharkv12 sharklive --tables all --split val --sessions 16 --rounds 5
```

```bash
python tools/optimize.py --base sharklive --candidates 32
```

```bash
python tools/info_value.py --tables mixed,oracles,fickle,osharks,selfplay
```

`watch` prints a play-by-play with the shark's beliefs, `bench` runs a
parallel tournament, and `compare` A/B-tests variants on identical deals
(`--workers N` caps the processes it uses). `compare` gives every game fresh
bots; for bots that learn as they play, `tools/sessions.py` keeps each
variant at one table for a session of rounds (same opponents, same seats,
same deals for every variant) and splits the result into the first three
rounds and the rest. The lineup's length sets the
table size (2-5). `compare` fields: `mixed`, `counters`, `oracles`,
`strong-mix`, `osharks` (the default five), `spoofed` / `unspoofed`,
`fickle`, `baited` / `bait-pair` (the resale tables), and `duel`,
`duel-oracle`, `trio`, `five` for other table sizes. Any `SharkParams` field
can be set as `shark:name=value,...`; add `#tag` to tell identical bots apart
(`shark#ref`). Earlier versions: `sharkv1` ... `sharkv6`, `sharkv8` (v7 and
v8 play identically in the simulator) and `sharkv10` (so do v9 and v10).
`sharklive` is the figgie.com settings (v13's; `sharkv12` is v12's, without
`read_learn` and `resale_robust`).

`figgie.arena` is the test bench since v13: paired sessions of every variant
at 21 tables (the benchmarks, strong opponents including three copies of the
live bot, every adversary, 3 and 5 players; `--tables` takes the groups
`benchmark`, `strong`, `adversarial`, `sizes`, `all` or table names), on
seeds from three disjoint ranges (`--split train|val|holdout`), scored as
half the average gain over tables plus half the average over the worst
quarter. `tools/optimize.py` searches the quoting, taking and holding
parameters on it: random search with successive halving on the training
seeds, choice on the validation seeds at every table including five it never
trained on, one report on the holdout seeds; the smart-money parameters fitted
to figgie.com stay fixed. `tools/info_value.py` measures what knowing the goal
earlier would be worth.

The tools work on the logged figgie.com rounds in `data/`. `replay_live` feeds
one to the Python bot and prints what it believed every 5 seconds (`--log`
picks the file); without `--trace` it checks the replay against the beliefs the
live bot logged at its trades. `paper_bot` replays the logged books through a
changed bot that may hit the logged bids and lift the logged offers, and
reports what that would have made against the unchanged bot. With `--quotes`
the changed bot's own bids and offers rest in the book too, and fill whenever
a logged order would have crossed them. `--base` applies settings to both bots
and `--carry` lets each carry its own resale record (or learned model) from
round to round, for comparing two resale strategies. `paper_resale`
paper-trades the resale pattern on its own.

---

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs them on Python 3.10-3.12 (`.github/workflows/tests.yml`).

The JavaScript port is checked against Python in a browser. Generate the
reference vectors (`tests/js_vectors.json`, about 4 MB, is not committed; this
command uses the figgie.com settings), serve the folder, and open the harness;
it should print `PASS`:

```bash
python tests/make_js_vectors.py smart_consensus=0.8 smart_colour_fade=90 resale_cheap=2 resale_bid=true resale_learn=true resale_robust=true read_learn=true
```

```bash
python -m http.server 8765 --bind 127.0.0.1
```

Then open <http://localhost:8765/tests/js_harness.html>. Last run (v13):
snapshots from 2-, 3-, 4- and 5-player games; posteriors equal to 3e-16,
card values to 6e-14 dollars. All orders were identical: 438 orders from 273
snapshots with the figgie.com settings (`smart_consensus=0.8
smart_colour_fade=90 resale_cheap=2 resale_bid=true resale_learn=true
resale_robust=true read_learn=true`), 21 of those snapshots turns that traded
resale cards, with the learned-resale model after every turn equal to the last
bit, and at 36 round starts (12 models, each at the same table, a new one, and
carried from another page), and the bid-reading learner equal over 20 random
12-round histories. (v12's settings: 567 orders from 289 snapshots; v11's
hand-built resale: 636 from 292.) To check other code paths, pass other
parameter overrides to the generator (the harness reads them from the vectors
file), e.g. `python tests/make_js_vectors.py smart_player_cap=1.5`; with none
it checks the simulator's default settings.

If you change a parameter, change it in both `figgie/shark.py`
(`SharkParams`) and `web/figgie-shark.user.js` (`SHARK_DEFAULTS`), then rerun
the harness.

---

## Layout

```
figgie/
  engine.py       rules-accurate engine: deck, order book, clear-on-trade, settlement (2-5 players)
  model.py        exact posterior, quote and bid reading, bonus-aware card values
  shark.py        SharkBot: the trading strategy, and the presets of every earlier version
  patterns.py     ResaleTracker (the cheap-resale pattern, with its kill switch),
                  ResaleLearner (v12: learns which offers resell, online, from the tape) and
                  ReadingLearner (v13: which market signals to trust at this table)
  bots.py         baseline opponents (fickle among them) + quoting helpers
  adversaries.py  simulator-only bots that try to exploit the shark (spoofer, bait, bait2,
                  pump, sniper, penny, quiet, holdout, adapt)
  tournament.py   parallel tournaments, play-by-play narrator
  compare.py      paired A/B comparisons
  arena.py        v13 test bench: paired sessions at 21 tables, train/val/holdout seeds
  __main__.py     CLI (watch / bench)
web/
  figgie-shark.user.js   userscript: JS port + figgie.com adapter + panel
tests/
  test_figgie.py         engine, model and bot unit tests
  make_js_vectors.py     Python reference vectors for the JS port
  js_harness.html        browser cross-check of the JS port
docs/
  HISTORY.md             every live test, round by round, and what each version changed
data/
  live_rounds.json       the logged live rounds (hands, top bids, per-bot bids from v7 on, P&L)
  live_logs_v9.json      every quote and trade of the 10 v9 rounds, with the bot's beliefs at its trades
  live_logs_v91.json     the same for the 10 v9.1 rounds, withdrawn quotes included
  live_logs_v10.json     the same for the 10 v10 rounds, resale trades marked
  live_logs_v11.json     the same for the 10 v11 rounds
  live_logs_v12.json     the same for the 10 v12 rounds, with the learned model each round started from
  live_logs_v13.json     the same for the 10 v13 rounds, plus what the bid-reading learner trusted and saw
  optimize_v13.json      every candidate and score of the v13 parameter search (tools/optimize.py)
tools/
  fit_smart_money.py     refits and checks the bid reading against the logged rounds
  replay_live.py         replays a logged live round through the Python bot, second by second
  paper_bot.py           what a changed bot would have taken from the logged books
  paper_resale.py        paper-trades the cheap-resale pattern on the logged rounds
  sessions.py            paired sessions at one table, for bots that learn from round to round
  optimize.py            seeded parameter search on the arena (train / val / unseen tables / holdout)
  info_value.py          what knowing the goal earlier would be worth (the ceiling for probing trades)
```

---

## License

MIT; see [LICENSE](LICENSE).
