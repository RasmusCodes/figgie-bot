// ==UserScript==
// @name         Figgie Shark
// @namespace    figgie-bot
// @version      0.13.0
// @description  Lets figgie-bot's Bayesian card-counting SharkBot trade your seat on figgie.com - only at tables where every other seat is a figgie.com bot.
// @match        https://www.figgie.com/play*
// @match        https://figgie.com/play*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

/*
 * Figgie Shark: a line-for-line JavaScript port of figgie-bot's SharkBot
 * (figgie/model.py + figgie/shark.py) plus an adapter for figgie.com/play.
 *
 * Install: Tampermonkey or Violentmonkey -> "Create a new script" -> paste this
 * file -> save.  (Or paste the whole file into the DevTools console on
 * figgie.com/play for a one-off session.)
 *
 * Play: Play as Guest -> Create New -> fill every empty seat with a bot (+) ->
 * set "Allow Players to Join" to No -> start -> switch the Shark panel ON.
 *
 * Fair play, by construction:
 *   - It only trades when every other seat is a figgie.com bot.  If a person
 *     sits down (or a bot is standing in for a person) it stops.
 *   - It only uses what a person in your seat can see: your own hand, the
 *     bids/offers, the trade tape and the clock.  The web client's state also
 *     contains the other players' records and a deck object; it never reads
 *     them.
 *   - It sends at most a few orders per second, through the same store
 *     methods the site's own Bid/Offer/Buy/Sell/Cancel buttons call.
 */
(function () {
  'use strict';

  // ===========================================================================
  // Core: pure model + bot (mirrors figgie/model.py and figgie/shark.py)
  // ===========================================================================
  const Core = (function () {
    const NUM_SUITS = 4;
    const SUIT_KEYS = ['spades', 'clubs', 'hearts', 'diamonds']; // index order S, C, H, D (same as Python)
    const SUIT_SYMBOLS = ['♠', '♣', '♥', '♦'];
    const PARTNER = [1, 0, 3, 2];
    const POT = 200;
    const GOAL_PAYOUT = 10;
    const SUITS = [0, 1, 2, 3];

    const CONFIGS = [];
    for (let t = 0; t < 4; t++) {
      for (let e = 0; e < 4; e++) {
        if (e === t) continue;
        const counts = SUITS.map((s) => (s === t ? 12 : s === e ? 8 : 10));
        const goal = PARTNER[t];
        CONFIGS.push({ twelve: t, eight: e, counts, goal, bonus: POT - GOAL_PAYOUT * counts[goal] });
      }
    }

    const PASCAL = [];
    for (let n = 0; n <= 48; n++) {
      const row = [];
      for (let k = 0; k <= n; k++) row.push(k === 0 || k === n ? 1 : PASCAL[n - 1][k - 1] + PASCAL[n - 1][k]);
      PASCAL.push(row);
    }
    function comb(n, k) {
      return n < 0 || k < 0 || k > n ? 0 : PASCAL[n][k];
    }
    const sum = (xs) => xs.reduce((a, b) => a + b, 0);

    function handLikelihood(hand) {
      return CONFIGS.map((c) => {
        let p = 1;
        for (const s of SUITS) p *= comb(c.counts[s], hand[s]);
        return p;
      });
    }

    // P(constrained players hold >= mins of a suit) when `rem` cards of it are
    // spread uniformly over nOthers hands of H cards plus `kitty` undealt cards
    // (3 players: one card is left out) - multivariate hypergeometric.
    const scpCache = new Map();
    function suitConstraintProb(rem, mins, H, nOthers, kitty) {
      kitty = kitty || 0;
      const k = mins.length;
      if (k === 0) return 1;
      if (rem < sum(mins)) return 0;
      const key = rem + '|' + mins.join(',') + '|' + H + '|' + nOthers + '|' + kitty;
      const hit = scpCache.get(key);
      if (hit !== undefined) return hit;
      const pool = (nOthers - k) * H + kitty;
      const ways = (i, left) => {
        if (i === k) return comb(pool, left);
        let acc = 0;
        for (let x = mins[i]; x <= Math.min(H, left); x++) acc += comb(H, x) * ways(i + 1, left - x);
        return acc;
      };
      const v = ways(0, rem) / comb(nOthers * H + kitty, rem);
      scpCache.set(key, v);
      return v;
    }

    function posterior(hand0, mins, H, nOthers, extra, kitty) {
      let w = handLikelihood(hand0);
      if (extra) w = w.map((a, i) => a * extra[i]);
      for (let i = 0; i < CONFIGS.length; i++) {
        if (w[i] === 0) continue;
        const c = CONFIGS[i];
        for (const s of SUITS) {
          const ms = mins.map((m) => m[s]).filter((x) => x > 0).sort((a, b) => a - b);
          if (ms.length) {
            w[i] *= suitConstraintProb(c.counts[s] - hand0[s], ms, H, nOthers, kitty);
            if (w[i] === 0) break;
          }
        }
      }
      let total = sum(w);
      if (!(total > 0)) {
        w = handLikelihood(hand0);
        total = sum(w);
        if (!(total > 0)) return CONFIGS.map(() => 1 / CONFIGS.length); // a hand no deck can produce
      }
      return w.map((x) => x / total);
    }

    function goalProbs(post) {
      const out = [0, 0, 0, 0];
      CONFIGS.forEach((c, i) => {
        out[c.goal] += post[i];
      });
      return out;
    }

    // ----- reading other players' quotes ---------------------------------------
    const compCache = new Map();
    function compositions(total) {
      let v = compCache.get(total);
      if (!v) {
        v = [];
        for (let a = 0; a <= total; a++)
          for (let b = 0; b <= total - a; b++)
            for (let c = 0; c <= total - a - b; c++) v.push([a, b, c, total - a - b - c]);
        compCache.set(total, v);
      }
      return v;
    }

    const naiveCache = new Map();
    function naiveGoalTable(H, nOthers) {
      const key = H + '|' + nOthers;
      let v = naiveCache.get(key);
      if (!v) {
        v = compositions(H).map((a) => goalProbs(posterior(a, [], H, nOthers)));
        naiveCache.set(key, v);
      }
      return v;
    }

    const hwCache = new Map();
    function handWeights(hand0, H) {
      const key = hand0.join(',') + '|' + H;
      let v = hwCache.get(key);
      if (!v) {
        const comps = compositions(H);
        v = CONFIGS.map((c) => {
          const rem = SUITS.map((s) => c.counts[s] - hand0[s]);
          if (Math.min(...rem) < 0) return comps.map(() => 0);
          return comps.map((a) => comb(rem[0], a[0]) * comb(rem[1], a[1]) * comb(rem[2], a[2]) * comb(rem[3], a[3]));
        });
        hwCache.set(key, v);
      }
      return v;
    }

    // othersQuotes[i]: Map key -> {s, isBid, price} (latest quote per suit/side)
    function quoteLikelihood(hand0, othersMins, othersQuotes, H, model) {
      const out = CONFIGS.map(() => 1);
      if (!(model.weight > 0)) return out;
      const comps = compositions(H);
      const table = naiveGoalTable(H, othersMins.length);
      const weights = handWeights(hand0, H);
      const { value_scale: scale, tau, eps } = model;
      const keep = 1 - eps;
      othersMins.forEach((minsP, pi) => {
        const quotes = othersQuotes[pi];
        if (!quotes || quotes.size === 0) return;
        const items = [...quotes.values()];
        const lik = comps.map((a, ai) => {
          if (a[0] < minsP[0] || a[1] < minsP[1] || a[2] < minsP[2] || a[3] < minsP[3]) return -1;
          const q = table[ai];
          let l = 1;
          for (const it of items) {
            let z = it.isBid ? (scale * q[it.s] - it.price) / tau : (it.price - scale * q[it.s]) / tau;
            z = Math.max(-30, Math.min(30, z));
            l *= eps + keep / (1 + Math.exp(-z));
          }
          return l;
        });
        for (let ci = 0; ci < CONFIGS.length; ci++) {
          let num = 0;
          let den = 0;
          const wrow = weights[ci];
          for (let ai = 0; ai < comps.length; ai++) {
            const w = wrow[ai];
            const l = lik[ai];
            if (w > 0 && l >= 0) {
              den += w;
              num += w * l;
            }
          }
          if (den > 0) out[ci] *= Math.pow(num / den, model.weight);
        }
      });
      return out;
    }

    // ----- smart money: the market's extreme prices as goal-suit votes ---------------
    // Mirrors SmartMoneyModel in figgie/model.py.
    const SMART_DEFAULTS = {
      weight: 1.0,
      bid_mid: 8.0,
      bid_up: 0.45,
      bid_down: 0.08,
      offer_mid: 5.0,
      offer_down: 0.35,
      offer_up: 0.08,
      cap: 3.0,
      player_cap: 0.0, // > 0: one vote per other player, each capped at this many nats ...
      total_cap: 4.0, // ... with the summed votes capped at this
      bid_none: null, // score a suit nobody has bid on as this top bid (null: no evidence)
      // consensus: the lowest of the opponents' own top bids on a suit is high only when every
      // opponent bid it up - which figgie.com's bots all do for the goal, and one bluffer can't fake
      consensus_slope: 0.0,
      consensus_mid: 5.0,
      consensus_cap: 4.0,
    };

    function consensusLogLR(topBy, s, m) {
      if (!(m.consensus_slope > 0) || !topBy || topBy.length < 2) return 0;
      const none = m.bid_none !== null && m.bid_none !== undefined ? m.bid_none : 0;
      let low = Infinity;
      for (const tops of topBy) low = Math.min(low, tops[s] === null || tops[s] === undefined ? none : tops[s]);
      return Math.min(m.consensus_cap, m.consensus_slope * Math.max(0, low - m.consensus_mid));
    }

    function smartMoneyLogLR(topBid, lowOffer, m) {
      let x = 0;
      if (topBid === null || topBid === undefined) topBid = m.bid_none;
      if (topBid !== null && topBid !== undefined) {
        const d = topBid - m.bid_mid;
        x += Math.max(-m.cap, Math.min(m.cap, (d > 0 ? m.bid_up : m.bid_down) * d));
      }
      if (lowOffer !== null && lowOffer !== undefined) {
        const d = lowOffer - m.offer_mid;
        x += Math.max(-m.cap, Math.min(m.cap, (d > 0 ? m.offer_up : m.offer_down) * d));
      }
      return x;
    }

    // Move each suit's log-evidence mix/2 of the way toward its same-colour partner's: at mix 1 both
    // suits of a colour get their average (evidence about the colour only), at 0 nothing changes.
    function colourBlend(x, mix) {
      if (!(mix > 0)) return x.slice();
      return SUITS.map((s) => x[s] + 0.5 * mix * (x[PARTNER[s]] - x[s]));
    }

    // topBy: each other player's own top bids (only the consensus term uses it); colourMix (0-1)
    // reads the top-bid / bottom-offer evidence as evidence about the colour (figgie/model.py)
    function smartMoneyLikelihood(topBid, lowOffer, m, topBy, colourMix) {
      if (!(m.weight > 0)) return CONFIGS.map(() => 1);
      const x = colourBlend(SUITS.map((s) => m.weight * smartMoneyLogLR(topBid[s], lowOffer[s], m)), colourMix || 0);
      const byGoal = SUITS.map((s) => Math.exp(x[s] + consensusLogLR(topBy, s, m)));
      return CONFIGS.map((c) => byGoal[c.goal]);
    }

    // One vote per player: topBy[i][s] / lowBy[i][s] are the i-th other player's extremes.
    function smartMoneyVotesLikelihood(topBy, lowBy, m) {
      if (!(m.weight > 0)) return CONFIGS.map(() => 1);
      const byGoal = SUITS.map((s) => {
        let x = 0;
        for (let i = 0; i < topBy.length; i++) x += Math.max(-m.player_cap, Math.min(m.player_cap, smartMoneyLogLR(topBy[i][s], lowBy[i][s], m)));
        return Math.exp(m.weight * Math.max(-m.total_cap, Math.min(m.total_cap, x)));
      });
      return CONFIGS.map((c) => byGoal[c.goal]);
    }

    // ----- valuation -------------------------------------------------------------
    // All ways `rem` unseen cards of a suit can sit in the other players' hands (and, with
    // 3 players, the one undealt card), as [split, probability, cards left undealt].
    const splitCache = new Map();
    function splits(rem, mins, H, kitty) {
      kitty = kitty || 0;
      const key = rem + '|' + mins.join(',') + '|' + H + '|' + kitty;
      const hit = splitCache.get(key);
      if (hit) return hit;
      const n = mins.length;
      const out = [];
      const rec = (i, left, cur, w) => {
        if (!kitty && i === n - 1) {
          if (mins[i] <= left && left <= H) out.push([cur.concat([left]), w * comb(H, left), 0]);
          return;
        }
        if (i === n) {
          if (left <= kitty) out.push([cur, w * comb(kitty, left), left]);
          return;
        }
        for (let x = mins[i]; x <= Math.min(H, left); x++) rec(i + 1, left - x, cur.concat([x]), w * comb(H, x));
      };
      rec(0, rem, [], 1);
      const total = out.reduce((a, o) => a + o[1], 0);
      const v = total ? out.map(([x, w, kx]) => [x, w / total, kx]) : [];
      splitCache.set(key, v);
      return v;
    }

    // kitty: cards left undealt (3 players: 1); pot: the antes (3 players: $198).  With
    // cards left out, the bonus depends on how many goal cards are among them.
    function valueCards(post, hand0, handNow, mins, nets, H, alpha, consolidate, consolidateAt, kitty, pot) {
      kitty = kitty || 0;
      const n = mins.length;
      let base;
      if (alpha === null || alpha === undefined) {
        base = (k, ys) => {
          let m = -1;
          let cnt = 0;
          for (const v of ys) {
            if (v > m) {
              m = v;
              cnt = 1;
            } else if (v === m) cnt++;
          }
          if (k > m) return 1;
          if (k < m) return 0;
          return 1 / (1 + cnt);
        };
      } else {
        const pw = [];
        for (let v = 0; v < 64; v++) pw.push(Math.pow(v, alpha));
        base = (k, ys) => {
          const a = pw[k];
          if (a === 0) return 0;
          let d = a;
          for (const v of ys) d += pw[v];
          return a / d;
        };
      }
      // consolidate (0-1): blend in the outcome where every goal card we don't hold ends up
      // with one rival, as the bonus-chasing house bots make happen; consolidateAt (0-1): only
      // once we hold at least that share of the goal suit (figgie/model.py value_cards)
      const blended = consolidate > 0 ? (k, ys) => (1 - consolidate) * base(k, ys) + consolidate * base(k, [sum(ys)]) : base;
      const gateAt = consolidateAt || 0;
      const pGoal = [0, 0, 0, 0];
      const buy = [0, 0, 0, 0];
      const sell = [0, 0, 0, 0];
      const buyFrom = SUITS.map(() => new Array(n).fill(0));
      const sellTo = SUITS.map(() => new Array(n).fill(0));
      let expected = 0;
      CONFIGS.forEach((c, ci) => {
        const pc = post[ci];
        if (pc < 1e-12) return;
        const g = c.goal;
        const k = handNow[g];
        const share = k >= gateAt * c.counts[g] ? blended : base;
        const sp = splits(c.counts[g] - hand0[g], mins.map((m) => m[g]), H, kitty);
        if (!sp.length) return;
        const netG = nets.map((nt) => nt[g]);
        let e0 = 0;
        let eb = 0;
        let es = 0;
        const dBf = new Array(n).fill(0);
        const wBf = new Array(n).fill(0);
        const dSt = new Array(n).fill(0);
        for (const [x, wp, kx] of sp) {
          // with cards left out, weight each split by its own bonus (the pot left after $10 per held goal card)
          const w = kitty ? wp * (pot - GOAL_PAYOUT * (c.counts[g] - kx)) : wp;
          const ys = x.map((xi, i) => xi + netG[i]);
          const s0 = share(k, ys);
          e0 += w * s0;
          const held = sum(ys);
          if (held > 0) {
            let acc = 0;
            for (let i = 0; i < n; i++) {
              const yi = ys[i];
              if (yi > 0) {
                ys[i] = yi - 1;
                const sb = share(k + 1, ys);
                ys[i] = yi;
                acc += yi * sb;
                dBf[i] += w * (sb - s0);
                wBf[i] += wp;
              }
            }
            eb += (w * acc) / held;
          } else {
            eb += w * s0;
          }
          if (k > 0) {
            let acc = 0;
            for (let i = 0; i < n; i++) {
              ys[i] += 1;
              const ss = share(k - 1, ys);
              ys[i] -= 1;
              acc += ss;
              dSt[i] += w * (s0 - ss);
            }
            es += (w * acc) / n;
          }
        }
        const bonus = kitty ? 1 : c.bonus; // with cards left out the bonus is already in the weights
        pGoal[g] += pc;
        expected += pc * (GOAL_PAYOUT * k + bonus * e0);
        buy[g] += pc * (GOAL_PAYOUT + bonus * (eb - e0));
        if (k > 0) sell[g] += pc * (GOAL_PAYOUT + bonus * (e0 - es));
        for (let i = 0; i < n; i++) {
          if (wBf[i] > 0) buyFrom[g][i] += pc * (GOAL_PAYOUT + (bonus * dBf[i]) / wBf[i]);
          if (k > 0) sellTo[g][i] += pc * (GOAL_PAYOUT + bonus * dSt[i]);
        }
      });
      return { pGoal, buy, sell, buyFrom, sellTo, expected };
    }

    // ----- beliefs ---------------------------------------------------------------
    class Beliefs {
      constructor(me, nPlayers, hand, H) {
        this.me = me;
        this.H = H;
        this.kitty = Math.max(0, 40 - H * nPlayers); // cards left undealt (3 players: 1)
        this.pot = Math.floor(POT / nPlayers) * nPlayers; // the antes (3 players: $198)
        this.hand0 = hand.slice();
        this.others = [];
        for (let p = 0; p < nPlayers; p++) if (p !== me) this.others.push(p);
        this.slot = new Map(this.others.map((p, i) => [p, i]));
        this.net = Array.from({ length: nPlayers }, () => [0, 0, 0, 0]);
        this.mins = Array.from({ length: nPlayers }, () => [0, 0, 0, 0]);
        this.quotes = new Map(this.others.map((p) => [p, new Map()]));
        this.quoteLik = null;
        this.topBid = [null, null, null, null]; // highest price another player bid or paid, per suit
        this.lowOffer = [null, null, null, null]; // lowest price another player offered or sold at
        this.topBy = new Map(this.others.map((p) => [p, [null, null, null, null]])); // the same, per player
        this.lowBy = new Map(this.others.map((p) => [p, [null, null, null, null]]));
        this.smart = null;
        this.smartColourMix = 0; // 0-1: read top bids / bottom offers as colour evidence (colourBlend)
        this.consolidate = 0; // see valueCards
        this.consolidateAt = 0;
        this.state = 0;
        this.minsState = 0;
        this.post = null;
        this.postKey = -1;
        this.val = null;
        this.valKey = null;
      }
      get hand() {
        return SUITS.map((s) => this.hand0[s] + this.net[this.me][s]);
      }
      setQuote(p, s, isBid, price) {
        const m = this.quotes.get(p);
        const key = s + '|' + (isBid ? 1 : 0);
        m.delete(key); // re-insert so iteration order matches Python's dict update order
        m.set(key, { s, isBid, price });
      }
      observeTrade(t) {
        this.net[t.buyer][t.suit] += 1;
        this.net[t.seller][t.suit] -= 1;
        if (t.seller !== this.me) {
          this.raiseMin(t.seller, t.suit, -this.net[t.seller][t.suit]);
          this.setQuote(t.seller, t.suit, false, t.price);
          this.noteOffer(t.suit, t.price, t.seller);
        }
        if (t.buyer !== this.me) {
          this.setQuote(t.buyer, t.suit, true, t.price);
          this.noteBid(t.suit, t.price, t.buyer);
        }
        this.state += 1;
      }
      observeQuote(ev) {
        if (ev.player === this.me) return false;
        this.setQuote(ev.player, ev.suit, ev.isBid, ev.price);
        if (ev.isBid) return this.noteBid(ev.suit, ev.price, ev.player);
        const moved = this.noteOffer(ev.suit, ev.price, ev.player);
        return this.observeOffer(ev.player, ev.suit) || moved;
      }
      noteBid(s, price, p) {
        let moved = false;
        if (this.topBid[s] === null || price > this.topBid[s]) {
          this.topBid[s] = price;
          moved = true;
        }
        const mine = this.topBy.get(p);
        if (mine[s] === null || price > mine[s]) {
          mine[s] = price;
          moved = true;
        }
        return this.smartMoved(moved);
      }
      noteOffer(s, price, p) {
        let moved = false;
        if (this.lowOffer[s] === null || price < this.lowOffer[s]) {
          this.lowOffer[s] = price;
          moved = true;
        }
        const mine = this.lowBy.get(p);
        if (mine[s] === null || price < mine[s]) {
          mine[s] = price;
          moved = true;
        }
        return this.smartMoved(moved);
      }
      smartMoved(moved) {
        if (moved && this.smart && this.smart.weight > 0) {
          this.minsState += 1;
          this.state += 1;
          return true;
        }
        return false;
      }
      observeOffer(p, s) {
        if (p !== this.me && this.raiseMin(p, s, 1 - this.net[p][s])) {
          this.state += 1;
          return true;
        }
        return false;
      }
      raiseMin(p, s, need) {
        if (need > this.mins[p][s]) {
          this.mins[p][s] = need;
          this.minsState += 1;
          return true;
        }
        return false;
      }
      refreshQuoteReading(model) {
        this.quoteLik = quoteLikelihood(
          this.hand0,
          this.others.map((p) => this.mins[p]),
          this.others.map((p) => this.quotes.get(p)),
          this.H,
          model
        );
        this.minsState += 1;
        this.state += 1;
      }
      posterior() {
        if (!this.post || this.postKey !== this.minsState) {
          let extra = this.quoteLik;
          if (this.smart && this.smart.weight > 0) {
            const sm =
              this.smart.player_cap > 0
                ? smartMoneyVotesLikelihood(this.others.map((p) => this.topBy.get(p)), this.others.map((p) => this.lowBy.get(p)), this.smart)
                : smartMoneyLikelihood(this.topBid, this.lowOffer, this.smart, this.others.map((p) => this.topBy.get(p)), this.smartColourMix);
            extra = extra === null ? sm : extra.map((a, i) => a * sm[i]);
          }
          this.post = posterior(this.hand0, this.others.map((p) => this.mins[p]), this.H, this.others.length, extra, this.kitty);
          this.postKey = this.minsState;
        }
        return this.post;
      }
      setSmartColourMix(mix) {
        if (mix !== this.smartColourMix) {
          this.smartColourMix = mix;
          this.minsState += 1;
          this.state += 1;
        }
      }
      pGoal() {
        return goalProbs(this.posterior());
      }
      valuation(alpha) {
        const key = this.state + '|' + this.minsState + '|' + alpha + '|' + this.consolidate + '|' + this.consolidateAt;
        if (!this.val || this.valKey !== key) {
          this.val = valueCards(
            this.posterior(),
            this.hand0,
            this.hand,
            this.others.map((p) => this.mins[p]),
            this.others.map((p) => this.net[p]),
            this.H,
            alpha,
            this.consolidate,
            this.consolidateAt,
            this.kitty,
            this.pot
          );
          this.valKey = key;
        }
        return this.val;
      }
    }

    // ----- quoting helpers (figgie/bots.py work_bid / work_offer) -----------------
    function workBid(m, suit, limit, opening, step) {
      let cur = m.bestBid(suit);
      const off = m.bestOffer(suit);
      const cap = off === null ? limit : Math.min(limit, off.price - 1);
      if (cur !== null && cur.player === m.me) {
        if (cur.price > cap) {
          m.cancelBid(suit);
          cur = null;
        } else {
          if (step && cur.price < cap) m.bid(suit, Math.min(cap, cur.price + step));
          return;
        }
      }
      if (cap < 1) return;
      const target = cur === null ? (opening === null || opening === undefined ? cap : Math.max(1, Math.min(cap, opening))) : Math.min(cap, cur.price + 1);
      if (cur === null || target > cur.price) m.bid(suit, target);
    }

    function workOffer(m, suit, limit, opening, step) {
      if (m.hand[suit] <= 0) return;
      let cur = m.bestOffer(suit);
      const bid = m.bestBid(suit);
      const floor = bid === null ? Math.max(1, limit) : Math.max(1, limit, bid.price + 1);
      if (cur !== null && cur.player === m.me) {
        if (cur.price < floor) {
          m.cancelOffer(suit);
          cur = null;
        } else {
          if (step && cur.price > floor) m.offer(suit, Math.max(floor, cur.price - step));
          return;
        }
      }
      const target = cur === null ? (opening === null || opening === undefined ? floor : Math.max(floor, opening)) : Math.max(floor, cur.price - 1);
      if (cur === null || target < cur.price) m.offer(suit, target);
    }

    // ----- the bot -------------------------------------------------------------------
    // Mirrors SharkParams in figgie/shark.py - keep them in sync (tests/js_harness.html checks).
    const SHARK_DEFAULTS = {
      alpha_start: 3.0,
      alpha_end: 40.0,
      take_edge: 1.0,
      take_frac: 0.2,
      quote_edge: 1.0,
      quote_frac: 0.2,
      adverse: 0.15,
      max_pay: 50.0,
      open_frac: 0.3,
      open_markup: 3.0,
      step: 1,
      step_every: 3,
      revalue_every: 5,
      read_weight: 0.5,
      read_scale: 20.0,
      read_tau: 4.0,
      read_eps: 0.3,
      read_every: 5,
      smart_weight: 1.0,
      smart_bid_mid: 17.0,
      smart_bid_up: 0.8,
      smart_offer_mid: 5.0,
      smart_offer_down: 0.56,
      churn_guard: 0.6,
      churn_p: 0.15,
      hold_goal: 25.0,
      hold_dead: 5.0,
      smart_player_cap: 0.0,
      smart_total_cap: 4.0,
      sticky_halflife: 30.0,
      buy_halflife: 8.0,
      consolidate: 1.0,
      consolidate_at: 0.5,
      smart_bid_down: 0.3,
      smart_cap: 10.0,
      smart_bid_none: 4.0,
      smart_confirm: 2,
      smart_confirm_trade: 1,
      smart_consensus: 0.0,
      smart_consensus_mid: 5.0,
      smart_consensus_cap: 4.0,
      fill_lr_offer: 3.0,
      fill_tau: 60.0,
      smart_colour_fade: 0.0,
      resale_cheap: 0,
      resale_margin: 2,
      resale_window: 45,
      resale_edge: 0.5,
      resale_min_hits: 2,
      resale_min_left: 15,
      resale_suit_cap: 2,
      resale_total_cap: 4,
      resale_stop: 6.0,
      resale_patience: 30,
      resale_bid: false,
      resale_learn: false,
      resale_learn_max: 5,
      resale_robust: false,
      adverse_offer: 0.0,
      read_learn: false,
      read_learn_at: 60,
    };
    const round2 = (x) => Math.round(x * 100) / 100;

    // Cheap resale (figgie/patterns.py, mirrored line by line): a card dumped for $1-2 that
    // another player soon bids back up to $4+.  Learns the pattern from the market and from our
    // own resales (which count double), and stops when they fail us.
    class ResaleTracker {
      constructor(o) {
        this.cheap = o.cheap;
        this.margin = o.margin;
        this.window = o.window;
        this.priorHits = 1.0;
        this.priorMisses = 2.0;
        this.ownWeight = 2.0;
        this.marketCap = 20.0;
        this.minHits = o.minHits;
        this.stopLoss = o.stopLoss;
        this.maxNetMisses = 2;
        this.open = []; // [tick, suit, price, seller]: cheap cards awaiting a resale bid
        this.hits = 0;
        this.misses = 0;
        this.prices = []; // the bids that resold a cheap card
        this.inventory = [[], [], [], []]; // our resale buys per suit: [tick, paid, written off]
        this.ownHits = 0;
        this.ownMisses = 0;
        this.realized = 0;
      }
      // what this round showed, discounted by `keep`, to seed the next round's tracker
      memory(keep = 0.5, nPrices = 12) {
        return [keep * this.hits, keep * this.misses, keep * this.ownHits, keep * this.ownMisses, this.prices.slice(-nPrices)];
      }
      seed(hits, misses, ownHits, ownMisses, prices) {
        this.hits += hits;
        this.misses += misses;
        this.ownHits += ownHits;
        this.ownMisses += ownMisses;
        this.prices.push(...prices);
      }
      cheapSeen(tick, s, price, seller) {
        if (price <= this.cheap) this.open.push([tick, s, price, seller]);
      }
      // a real bid (one that stood, or a purchase) by `bidder` for suit s
      bidSeen(tick, s, price, bidder) {
        const keep = [];
        for (const ev of this.open) {
          const [t0, s0, p0, seller] = ev;
          if (s0 === s && bidder !== seller && price >= p0 + this.margin && tick - t0 <= this.window) {
            this.hits += 1;
            this.prices.push(price);
          } else keep.push(ev);
        }
        this.open = keep;
      }
      expire(tick) {
        const keep = [];
        for (const ev of this.open) {
          if (tick - ev[0] > this.window) this.misses += 1;
          else keep.push(ev);
        }
        this.open = keep;
        for (let s = 0; s < 4; s++) {
          for (const item of this.inventory[s]) {
            if (!item[2] && tick - item[0] > this.window) {
              // bought to resell and still unsold: count it against the pattern and the stop-loss
              item[2] = true;
              this.ownMisses += 1;
              this.realized -= item[1];
            }
          }
        }
      }
      bought(tick, s, price) {
        this.inventory[s].push([tick, price, false]);
      }
      sold(s, price) {
        if (!this.inventory[s].length) return;
        const [, paid, writtenOff] = this.inventory[s].shift();
        if (writtenOff) {
          this.realized += price;
          return;
        }
        this.realized += price - paid;
        if (price > paid) this.ownHits += 1;
        else this.ownMisses += 1;
      }
      held(s) {
        return this.inventory[s].length;
      }
      heldTotal() {
        return this.inventory[0].length + this.inventory[1].length + this.inventory[2].length + this.inventory[3].length;
      }
      pHit() {
        const seen = this.hits + this.misses;
        const k = seen > 0 ? Math.min(1, this.marketCap / seen) : 1;
        const w = this.ownWeight;
        const hits = k * this.hits + w * this.ownHits + this.priorHits;
        return hits / (k * seen + w * (this.ownHits + this.ownMisses) + this.priorHits + this.priorMisses);
      }
      allowed(cap) {
        return Math.min(cap, 1 + Math.floor(this.ownHits));
      }
      resalePrice() {
        if (this.prices.length < this.minHits) return null;
        const ps = this.prices.slice().sort((a, b) => a - b);
        return ps[Math.floor(ps.length / 4)];
      }
      active() {
        if (this.realized <= -this.stopLoss || this.ownMisses - this.ownHits >= this.maxNetMisses) return false;
        return this.hits + this.ownHits >= this.minHits;
      }
      value(price) {
        if (price > this.cheap || !this.active()) return null;
        const r = this.resalePrice();
        if (r === null || r < price + this.margin) return null;
        const p = this.pHit();
        return p * (r - price) - (1 - p) * price;
      }
      target(s, tick, patience) {
        if (!this.inventory[s].length) return null;
        const [t0, paid] = this.inventory[s][0];
        const r = this.resalePrice();
        let target = Math.max(paid + this.margin, r !== null ? r : 0);
        if (tick - t0 > patience) target = Math.max(paid + 1, target - 1);
        return target;
      }
    }

    // Learned resale (v12; figgie/patterns.py ResaleLearner, mirrored line by line): for every
    // offer another player shows at up to maxPrice, the tape says within seconds whether a third
    // player bid enough more for the suit; a Bayesian logistic regression learns from that which
    // offers resell, at whatever table it plays, calibrated by how our own resales fare.  It
    // outlives the round (startRound keeps the model).
    const sigmoid = (z) => {
      if (z >= 0) return 1 / (1 + Math.exp(-z));
      const e = Math.exp(z);
      return e / (1 + e);
    };
    const LEARNER_FEATURES = ['bias', 'price', 'cheap', 'vs_trades', 'demand', 'depth', 'p_goal', 'time', 'streak', 'held'];
    const V12_D = 9; // models saved by v12 have no "held" weight: upgrade() inserts it
    const sameList = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
    // v13 (robust): labels come only from bids that proved real (bidSeen) and trades, and the
    // "held" feature lets the model learn whether others' bids depend on our holding the suit
    class ResaleLearner extends ResaleTracker {
      constructor(o) {
        o = o || {};
        const maxPrice = o.maxPrice !== undefined ? o.maxPrice : 5;
        super({
          cheap: maxPrice,
          margin: o.margin !== undefined ? o.margin : 2,
          window: o.window !== undefined ? o.window : 45,
          minHits: 2,
          stopLoss: o.stopLoss !== undefined ? o.stopLoss : 6.0,
        });
        this.robust = Boolean(o.robust);
        this.priorVar = 1.0;
        this.maxPrice = maxPrice;
        this.minLeft = o.minLeft !== undefined ? o.minLeft : 15;
        this.sellerVar = 0.5;
        this.marketWeight = 0.5;
        this.forget = 0.05;
        this.zLcb = 1.0;
        this.calPrior = 2.0;
        this.calDecay = 0.7;
        this.tableDecay = 0.5;
        const d = LEARNER_FEATURES.length;
        this.mu = [-1.0];
        for (let i = 1; i < d; i++) this.mu.push(0);
        this.S = [];
        for (let i = 0; i < d; i++) {
          const row = [];
          for (let j = 0; j < d; j++) row.push(i === j ? 1.0 : 0);
          this.S.push(row);
        }
        this.sellers = new Map(); // player -> index of their offset in mu / S
        this.calHits = 0; // our own resale buys that a third player bid back up ...
        this.calPred = 0; // ... against the chances the model gave them
        this.table = null;
        this.nObs = 0;
        this.ctxPg = [0.25, 0.25, 0.25, 0.25]; // our P(goal) per suit, refreshed every turn
        this.me = -1;
        this.ticks = 240;
        this.clearRound();
      }
      clearRound() {
        this.opps = []; // [tick, suit, price, features, seller], each awaiting a resale bid
        this.bids = []; // [tick, suit, price, bidder] of others, in time order
        this.trades = [[], [], [], []];
        this.offersBy = new Map(); // 'seller|suit' -> ticks of their offers
        this.inventory = [[], [], [], []];
        this.ownOpen = []; // [tick, suit, price, seller, features, prediction]
        this.realized = 0;
        this.hits = 0;
        this.misses = 0;
        this.net = [0, 0, 0, 0]; // our cards bought minus sold this round, per suit
      }
      startRound(me, ticks, table) {
        if (table != null && this.table !== null && !sameList(table, this.table)) {
          this.calHits *= this.tableDecay;
          this.calPred *= this.tableDecay;
          this.forgetSellers();
        }
        if (table != null) this.table = table.slice();
        this.me = me;
        this.ticks = ticks;
        this.clearRound();
        this.ownHits *= 0.5;
        this.ownMisses *= 0.5;
        this.calHits *= this.calDecay;
        this.calPred *= this.calDecay;
        for (let i = 0; i < this.S.length; i++) this.S[i][i] += this.forget;
        if (this.prices.length > 50) this.prices.splice(0, this.prices.length - 50);
      }
      // new opponents: the per-seller offsets are keyed by seat, so drop them (exact
      // marginalisation of a Gaussian posterior: their rows and columns go)
      forgetSellers() {
        const d = LEARNER_FEATURES.length;
        this.mu = this.mu.slice(0, d);
        this.S = this.S.slice(0, d).map((r) => r.slice(0, d));
        this.sellers = new Map();
      }
      vec(x, seller, grow) {
        const idx = [];
        for (let i = 0; i < x.length; i++) idx.push(i);
        const vals = x.slice();
        if (seller !== null && seller !== undefined) {
          let k = this.sellers.has(seller) ? this.sellers.get(seller) : null;
          if (k === null && grow) {
            k = this.mu.length;
            this.sellers.set(seller, k);
            this.mu.push(0);
            for (const row of this.S) row.push(0);
            const row = [];
            for (let j = 0; j < k; j++) row.push(0);
            row.push(this.sellerVar);
            this.S.push(row);
          }
          if (k !== null) {
            idx.push(k);
            vals.push(1);
          }
        }
        return [idx, vals];
      }
      zVar(idx, vals) {
        let z = 0;
        for (let a = 0; a < idx.length; a++) z += this.mu[idx[a]] * vals[a];
        let v = 0;
        for (let a = 0; a < idx.length; a++) {
          const row = this.S[idx[a]];
          let acc = 0;
          for (let b = 0; b < idx.length; b++) acc += row[idx[b]] * vals[b];
          v += acc * vals[a];
        }
        return [z, v];
      }
      update(x, seller, y, wt) {
        const [idx, vals] = this.vec(x, seller, true);
        const [z, v] = this.zVar(idx, vals);
        const p = sigmoid(z);
        const h = wt * p * (1 - p);
        const g = wt * (y - p);
        const n = this.mu.length;
        const sx = [];
        for (let i = 0; i < n; i++) {
          const row = this.S[i];
          let acc = 0;
          for (let b = 0; b < idx.length; b++) acc += row[idx[b]] * vals[b];
          sx.push(acc);
        }
        const denom = 1 + h * v;
        for (let i = 0; i < n; i++) {
          if (sx[i] === 0) continue;
          const f = (sx[i] * h) / denom;
          const row = this.S[i];
          for (let j = 0; j < n; j++) if (sx[j] !== 0) row[j] -= f * sx[j];
        }
        for (let i = 0; i < n; i++) {
          const row = this.S[i];
          let acc = 0;
          for (let b = 0; b < idx.length; b++) acc += row[idx[b]] * vals[b];
          this.mu[i] += acc * g;
        }
        this.nObs += 1;
      }
      // chance that a card bought at this opportunity is bid back up: a lower confidence bound or the mean
      pResale(x, seller, lcb) {
        const [idx, vals] = this.vec(x, seller, false);
        const [z, v] = this.zVar(idx, vals);
        if (lcb) return sigmoid(z - this.zLcb * Math.sqrt(Math.max(v, 0)));
        return sigmoid(z / Math.sqrt(1 + (Math.PI * v) / 8));
      }
      calibration() {
        return Math.min(1.2, (this.calPrior + this.calHits) / (this.calPrior + this.calPred));
      }
      // held (default: whether we are long s now) is the position the answer depends on: true for
      // a buy we are deciding on or have made
      features(tick, s, price, seller, held) {
        if (held === undefined || held === null) held = this.net[s] > 0;
        const tr = this.trades[s].slice(-3);
        const ref = tr.length ? tr.slice().sort((a, b) => a - b)[Math.floor(tr.length / 2)] : price;
        let demand = 0;
        const depth = [];
        for (let i = this.bids.length - 1; i >= 0; i--) {
          const [t, s2, p, who] = this.bids[i];
          if (tick - t > 60) break;
          if (s2 !== s || who === seller) continue;
          if (tick - t <= 30 && p > demand) demand = p;
          if (p >= price + this.margin && !depth.includes(who)) depth.push(who);
        }
        let streak = 0;
        for (const t of this.offersBy.get(seller + '|' + s) || []) if (tick - t <= 20) streak += 1;
        return [1, price / 5, price <= 2 ? 1 : 0, (price - ref) / 5, demand / 5, depth.length / 2, this.ctxPg[s], tick / Math.max(1, this.ticks), Math.min(3, streak) / 3, this.robust && held ? 1 : 0];
      }
      cheapSeen() {} // fed by quoteSeen / tradeSeen instead
      // a bid that proved real (robust): only these, and trades, answer the questions
      bidSeen(tick, s, price, bidder) {
        if (!this.robust || bidder === this.me) return;
        this.bids.push([tick, s, price, bidder]);
        this.resolve(tick, s, price, bidder);
      }
      quoteSeen(tick, s, isBid, price, player) {
        if (player === this.me) return;
        if (isBid) {
          if (!this.robust) {
            this.bids.push([tick, s, price, player]);
            this.resolve(tick, s, price, player);
          }
          return;
        }
        const key = player + '|' + s;
        if (!this.offersBy.has(key)) this.offersBy.set(key, []);
        this.offersBy.get(key).push(tick);
        if (price <= this.maxPrice && this.ticks - tick >= this.minLeft) this.opps.push([tick, s, price, this.features(tick, s, price, player), player]);
      }
      tradeSeen(tick, s, price, buyer, seller) {
        if (buyer === this.me) this.net[s] += 1;
        else if (seller === this.me) this.net[s] -= 1;
        this.trades[s].push(price);
        if (buyer !== this.me) {
          this.bids.push([tick, s, price, buyer]); // paying a price is bidding it
          this.resolve(tick, s, price, buyer);
        }
        if (seller !== this.me && buyer !== this.me && price <= this.maxPrice && this.ticks - tick >= this.minLeft) {
          // a cheap sale between two others, unless it was an offer we already count
          if (!this.opps.some((o) => o[4] === seller && o[1] === s && o[2] === price)) this.opps.push([tick, s, price, this.features(tick, s, price, seller), seller]);
        }
      }
      resolve(tick, s, price, bidder) {
        const keep = [];
        for (const o of this.opps) {
          const [t0, s0, p0, x, seller] = o;
          if (s0 === s && bidder !== seller && price >= p0 + this.margin && tick - t0 <= this.window) {
            this.update(x, seller, 1, this.marketWeight);
            this.hits += 1;
            this.prices.push(price);
          } else keep.push(o);
        }
        this.opps = keep;
        const mine = [];
        for (const item of this.ownOpen) {
          const [t0, s0, p0, seller, , pred] = item;
          if (s0 === s && bidder !== seller && price >= p0 + this.margin && tick - t0 <= this.window) {
            this.calHits += 1;
            this.calPred += pred;
          } else mine.push(item);
        }
        this.ownOpen = mine;
      }
      expire(tick) {
        const keep = [];
        for (const o of this.opps) {
          if (tick - o[0] > this.window) {
            this.update(o[3], o[4], 0, this.marketWeight);
            this.misses += 1;
          } else keep.push(o);
        }
        this.opps = keep;
        const mine = [];
        for (const item of this.ownOpen) {
          if (tick - item[0] > this.window) this.calPred += item[5]; // never bid back up
          else mine.push(item);
        }
        this.ownOpen = mine;
        for (let s = 0; s < 4; s++) {
          for (const item of this.inventory[s]) {
            if (!item[2] && tick - item[0] > this.window) {
              item[2] = true;
              this.ownMisses += 1;
              this.realized -= item[1];
            }
          }
        }
      }
      boughtFrom(tick, s, price, seller) {
        this.bought(tick, s, price);
        const x = this.features(tick, s, price, seller, true);
        this.ownOpen.push([tick, s, price, seller === undefined ? null : seller, x, this.pResale(x, seller, false)]);
      }
      active() {
        return !(this.realized <= -this.stopLoss || this.ownMisses - this.ownHits >= this.maxNetMisses);
      }
      // expected gain from buying a card of s at `price` (from `seller`, if known) to resell it; an
      // unsold card is worth what it is to us anyway (holdValue, at most the price); null: may not buy
      valueAt(tick, s, price, seller, holdValue) {
        if (price > this.maxPrice || !this.active()) return null;
        const r = this.resalePrice();
        const exitPx = Math.max(price + this.margin, r !== null ? r : 0);
        const x = this.features(tick, s, price, seller, true); // as it will be once we hold the card
        const p = Math.min(1, this.pResale(x, seller, true) * this.calibration());
        const salvage = Math.min(Math.max(0, holdValue || 0), price);
        return p * (exitPx - price) + (1 - p) * (salvage - price);
      }
      // for the panel: the model's chance for a $1 card nobody has bid on yet, bought
      pHit() {
        return this.pResale([1, 0.2, 1, 0, 0, 0, 0, 0.5, 0, this.robust ? 1 : 0], null, false) * this.calibration();
      }
      // mu, S and sellers of a saved model in today's layout: a v12 model (no "held" weight) gets one
      // inserted after its shared weights, at the prior, and its seller offsets move up one place
      upgrade(m) {
        let mu = m.mu.slice();
        let S = m.S.map((r) => r.slice());
        let sellers = new Map(m.sellers.map(([p, k]) => [p, k]));
        const dOld = m.d !== undefined ? m.d : V12_D;
        const d = LEARNER_FEATURES.length;
        if (dOld < d) {
          const ins = d - dOld;
          const n = mu.length + ins;
          const pos = [];
          for (let i = 0; i < dOld; i++) pos.push(i);
          for (let i = d; i < n; i++) pos.push(i);
          const S2 = [];
          for (let i = 0; i < n; i++) S2.push(new Array(n).fill(0));
          for (let a = 0; a < pos.length; a++) for (let b = 0; b < pos.length; b++) S2[pos[a]][pos[b]] = S[a][b];
          for (let i = dOld; i < d; i++) S2[i][i] = this.priorVar;
          mu = mu.slice(0, dOld).concat(new Array(ins).fill(0), mu.slice(dOld));
          S = S2;
          sellers = new Map([...sellers.entries()].map(([p, k]) => [p, k >= dOld ? k + ins : k]));
        }
        return [mu, S, sellers];
      }
      // an opportunity's features as saved by v12 (no "held"): not held
      pad(x) {
        const out = x.slice();
        while (out.length < LEARNER_FEATURES.length) out.push(0);
        return out;
      }
      state() {
        return {
          d: LEARNER_FEATURES.length,
          mu: this.mu.slice(),
          S: this.S.map((r) => r.slice()),
          sellers: [...this.sellers.entries()].map(([p, k]) => [p, k]),
          cal: [this.calHits, this.calPred],
          table: this.table === null ? null : this.table.slice(),
          n_obs: this.nObs,
          ctx_pg: this.ctxPg.slice(),
          me: this.me,
          ticks: this.ticks,
          opps: this.opps.map((o) => [o[0], o[1], o[2], o[3].slice(), o[4]]),
          bids: this.bids.map((b) => b.slice()),
          trades: this.trades.map((t) => t.slice()),
          offers_by: [...this.offersBy.entries()].map(([k, v]) => [k, v.slice()]),
          inventory: this.inventory.map((items) => items.map((it) => it.slice())),
          own_open: this.ownOpen.map((it) => [it[0], it[1], it[2], it[3], it[4].slice(), it[5]]),
          counts: [this.hits, this.misses, this.ownHits, this.ownMisses, this.realized],
          prices: this.prices.slice(),
          net: this.net.slice(),
        };
      }
      load(st) {
        [this.mu, this.S, this.sellers] = this.upgrade(st);
        [this.calHits, this.calPred] = st.cal;
        this.table = st.table === null ? null : st.table.slice();
        this.nObs = st.n_obs;
        this.ctxPg = st.ctx_pg.slice();
        this.me = st.me;
        this.ticks = st.ticks;
        this.opps = st.opps.map((o) => [o[0], o[1], o[2], this.pad(o[3]), o[4]]);
        this.bids = st.bids.map((b) => b.slice());
        this.trades = st.trades.map((t) => t.slice());
        this.offersBy = new Map(st.offers_by.map(([k, v]) => [k, v.slice()]));
        this.inventory = st.inventory.map((items) => items.map((it) => it.slice()));
        this.ownOpen = st.own_open.map((it) => [it[0], it[1], it[2], it[3], this.pad(it[4]), it[5]]);
        [this.hits, this.misses, this.ownHits, this.ownMisses, this.realized] = st.counts;
        this.prices = st.prices.slice();
        this.net = st.net ? st.net.slice() : [0, 0, 0, 0];
      }
      // the model to hand to the next round's bot, aged by one round as startRound would
      memory() {
        return [
          {
            d: LEARNER_FEATURES.length,
            mu: this.mu.slice(),
            S: this.S.map((r, i) => r.map((x, j) => x + (i === j ? this.forget : 0))),
            sellers: [...this.sellers.entries()].map(([p, k]) => [p, k]),
            cal: [this.calHits * this.calDecay, this.calPred * this.calDecay],
            own: [this.ownHits * 0.5, this.ownMisses * 0.5],
            table: this.table === null ? null : this.table.slice(),
            n_obs: this.nObs,
            prices: this.prices.slice(-50),
          },
        ];
      }
      // the model exactly as this round started (right after startRound): logged as resale_seed
      roundStartModel() {
        return {
          exact: true,
          d: LEARNER_FEATURES.length,
          mu: this.mu.slice(),
          S: this.S.map((r) => r.slice()),
          sellers: [...this.sellers.entries()].map(([p, k]) => [p, k]),
          cal: [this.calHits, this.calPred],
          own: [this.ownHits, this.ownMisses],
          table: this.table === null ? null : this.table.slice(),
          n_obs: this.nObs,
          prices: this.prices.slice(),
        };
      }
      seed(...args) {
        if (args.length === 1 && args[0] && typeof args[0] === 'object' && !Array.isArray(args[0])) {
          const m = args[0];
          [this.mu, this.S, this.sellers] = this.upgrade(m);
          [this.calHits, this.calPred] = m.cal;
          [this.ownHits, this.ownMisses] = m.own;
          if (!m.exact && m.table !== null && this.table !== null && !sameList(m.table, this.table)) {
            this.calHits *= this.tableDecay;
            this.calPred *= this.tableDecay;
            this.forgetSellers();
          }
          if (m.exact) this.table = m.table === null ? null : m.table.slice();
          this.nObs = m.n_obs;
          this.prices = m.prices.slice();
        } else if (args.length === 5) {
          this.prices.push(...args[4]);
        }
      }
    }

    // v13 (read_learn; figgie/patterns.py ReadingLearner, mirrored line by line): how far to trust
    // the colour reading and the consensus at this table, learned from the goals the bell reveals
    class ReadingLearner {
      constructor() {
        this.prior = [0.9, 0.9];
        this.partnerIfColour = 0.5;
        this.partnerIfSuit = 0.1;
        this.rightIfReliable = 0.9;
        this.rightIfNot = 0.25;
        this.forget = 0.1;
        this.tableForget = 0.5;
        this.clamp = 0.01;
        this.logit = this.prior.map((p) => ReadingLearner.lo(p));
        this.table = null;
        this.rounds = 0;
        this.seen = [0, 0];
      }
      static lo(p) {
        return Math.log(p / (1 - p));
      }
      pColour() {
        return sigmoid(this.logit[0]);
      }
      pConsensus() {
        return sigmoid(this.logit[1]);
      }
      drift(w) {
        for (let i = 0; i < 2; i++) {
          const p0 = ReadingLearner.lo(this.prior[i]);
          this.logit[i] += w * (p0 - this.logit[i]);
        }
      }
      startRound(table) {
        if (table != null && this.table !== null && !sameList(table, this.table)) this.drift(this.tableForget);
        if (table != null) this.table = table.slice();
      }
      // the bell: earlyTop is the suit with the highest bid a minute in (null: none, or a tie),
      // consensus the suit every opponent had bid up most (null: none)
      endRound(goal, earlyTop, consensus) {
        this.drift(this.forget);
        const lim = ReadingLearner.lo(1 - this.clamp);
        if (earlyTop !== null && (earlyTop === goal || earlyTop === (goal ^ 1))) {
          const partner = earlyTop !== goal;
          const a = partner ? this.partnerIfColour : 1 - this.partnerIfColour;
          const b = partner ? this.partnerIfSuit : 1 - this.partnerIfSuit;
          this.logit[0] = Math.max(-lim, Math.min(lim, this.logit[0] + Math.log(a / b)));
          this.seen[0] += 1;
        }
        if (consensus !== null) {
          const right = consensus === goal;
          const a = right ? this.rightIfReliable : 1 - this.rightIfReliable;
          const b = right ? this.rightIfNot : 1 - this.rightIfNot;
          this.logit[1] = Math.max(-lim, Math.min(lim, this.logit[1] + Math.log(a / b)));
          this.seen[1] += 1;
        }
        this.rounds += 1;
      }
      state() {
        return { logit: this.logit.slice(), table: this.table === null ? null : this.table.slice(), rounds: this.rounds, seen: this.seen.slice() };
      }
      load(st) {
        this.logit = st.logit.slice();
        this.table = st.table === null ? null : st.table.slice();
        this.rounds = st.rounds;
        this.seen = st.seen.slice();
      }
    }

    class SharkBot {
      constructor(params) {
        params = params || {};
        for (const k of Object.keys(params)) if (!(k in SHARK_DEFAULTS)) throw new Error('unknown SharkBot parameter ' + k);
        this.p = Object.assign({}, SHARK_DEFAULTS, params);
        this.reading = { weight: this.p.read_weight, value_scale: this.p.read_scale, tau: this.p.read_tau, eps: this.p.read_eps };
        this.smart = Object.assign({}, SMART_DEFAULTS, {
          weight: this.p.smart_weight,
          bid_mid: this.p.smart_bid_mid,
          bid_up: this.p.smart_bid_up,
          offer_mid: this.p.smart_offer_mid,
          offer_down: this.p.smart_offer_down,
          player_cap: this.p.smart_player_cap,
          total_cap: this.p.smart_total_cap,
          bid_down: this.p.smart_bid_down,
          cap: this.p.smart_cap,
          bid_none: this.p.smart_bid_none,
          consensus_slope: this.p.smart_consensus,
          consensus_mid: this.p.smart_consensus_mid,
          consensus_cap: this.p.smart_consensus_cap,
        });
        this.quoteAfterTake = true; // simulator semantics; the live adapter waits for the trade instead
        // v12 learned resale: one learner for the bot's whole life (the adapter hands it from round
        // to round), so what it learns at a table carries on
        this.learner = null;
        // v13: what it has learned about reading this table's bids (read_learn), kept likewise
        this.reader = null;
      }
      onStart(info) {
        this.me = info.player;
        this.ticks = info.ticks;
        this.beliefs = new Beliefs(info.player, info.nPlayers, info.hand, info.handSize);
        let smart = this.smart;
        this.colourScale = 1;
        this.earlyTop = null;
        this.earlyDone = false;
        if (this.p.read_learn) {
          if (!this.reader) this.reader = new ReadingLearner();
          this.reader.startRound(info.names ? info.names.filter((_, p) => p !== info.player) : null);
          this.colourScale = this.reader.pColour();
          smart = Object.assign({}, smart, { consensus_slope: smart.consensus_slope * this.reader.pConsensus() });
        }
        this.beliefs.smart = smart.weight > 0 ? smart : null;
        this.beliefs.consolidate = this.p.consolidate;
        this.beliefs.consolidateAt = this.p.consolidate_at;
        this.slot = this.beliefs.slot;
        this.cost = [0, 0, 0, 0]; // average-cost book of the cards we bought and still hold
        this.bought = [0, 0, 0, 0];
        this.val = null;
        this.valTick = -1e9;
        this.readTick = -1e9;
        this.dirty = true;
        this.pSticky = null; // recent-max P(goal): protects what we hold
        this.pAvg = null; // moving-average P(goal): caps what we pay
        this.pTick = null;
        this.pending = new Map(); // suit -> [quote, turns seen]: other players' bids not yet proven
        this.now = 0; // tick of our latest turn: stamps events that come without one
        const P = this.p;
        if (P.resale_cheap > 0 && P.resale_learn) {
          if (!this.learner) this.learner = new ResaleLearner({ maxPrice: P.resale_learn_max, margin: P.resale_margin, window: P.resale_window, minLeft: P.resale_min_left, stopLoss: P.resale_stop, robust: P.resale_robust });
          const others = info.names ? info.names.filter((_, p) => p !== info.player) : null;
          this.learner.startRound(info.player, info.ticks, others);
          this.resale = this.learner;
        } else {
          this.resale = P.resale_cheap > 0 ? new ResaleTracker({ cheap: P.resale_cheap, margin: P.resale_margin, window: P.resale_window, minHits: P.resale_min_hits, stopLoss: P.resale_stop }) : null;
        }
        this.resaleBuy = null; // suit of a resale buy we have sent, until it fills
        this.resaleBids = [0, 0, 0, 0]; // the resale bid we last quoted per suit (0: none)
      }
      // Keep a sticky (recent-max) and a smoothed (moving-average) copy of P(goal).
      track(tick, pg) {
        const P = this.p;
        if (this.pTick === null) {
          this.pSticky = pg.slice();
          this.pAvg = pg.slice();
          this.pTick = tick;
          return;
        }
        const dt = tick - this.pTick;
        if (dt > 0) {
          const ds = P.sticky_halflife > 0 ? Math.pow(0.5, dt / P.sticky_halflife) : 0;
          const da = P.buy_halflife > 0 ? Math.pow(0.5, dt / P.buy_halflife) : 0;
          this.pSticky = pg.map((p, i) => Math.max(p, this.pSticky[i] * ds));
          this.pAvg = pg.map((p, i) => p + (this.pAvg[i] - p) * da);
          this.pTick = tick;
        } else {
          this.pSticky = P.sticky_halflife > 0 ? pg.map((p, i) => Math.max(p, this.pSticky[i])) : pg.slice();
          if (P.buy_halflife <= 0) this.pAvg = pg.slice();
        }
      }
      pHold(s, v) {
        return this.pSticky !== null ? Math.max(v.pGoal[s], this.pSticky[s]) : v.pGoal[s];
      }
      pPay(s, v) {
        return this.pAvg !== null ? Math.min(v.pGoal[s], this.pAvg[s]) : v.pGoal[s];
      }
      onTrade(t) {
        if (this.pending.size) {
          // a trade clears the book: a pending bid we saw rest through one of our turns was real
          for (const [ev, seen] of this.pending.values()) if (seen >= this.p.smart_confirm_trade) this.accept(ev);
          this.pending.clear();
        }
        this.beliefs.observeTrade(t);
        if (t.buyer === this.me) {
          this.cost[t.suit] += t.price;
          this.bought[t.suit] += 1;
        } else if (t.seller === this.me && this.bought[t.suit] > 0) {
          this.cost[t.suit] -= this.cost[t.suit] / this.bought[t.suit];
          this.bought[t.suit] -= 1;
        }
        const r = this.resale;
        if (r && r === this.learner) {
          const tick = t.tick !== undefined ? t.tick : this.now;
          if (t.seller === this.me) r.sold(t.suit, t.price);
          else if (t.buyer === this.me && (this.resaleBuy === t.suit || (t.price > 0 && t.price <= this.resaleBids[t.suit]))) {
            r.boughtFrom(tick, t.suit, t.price, t.seller); // a resale buy, booked with its seller
            this.resaleBuy = null;
          }
          r.tradeSeen(tick, t.suit, t.price, t.buyer, t.seller);
        } else if (r) {
          const tick = t.tick !== undefined ? t.tick : this.now;
          if (t.buyer !== this.me) {
            r.bidSeen(tick, t.suit, t.price, t.buyer); // a purchase is as real as a bid gets
            if (t.seller !== this.me) r.cheapSeen(tick, t.suit, t.price, t.seller);
          }
          if (t.seller === this.me) r.sold(t.suit, t.price);
          else if (t.buyer === this.me && (this.resaleBuy === t.suit || (t.price > 0 && t.price <= this.resaleBids[t.suit]))) {
            r.bought(tick, t.suit, t.price); // a resale buy we sent, or a fill on a resale bid
            this.resaleBuy = null;
          }
        }
        this.dirty = true;
      }
      // Churn guard: the least we'll take for a card we paid for, unless the suit looks dead.
      sellFloor(s, v) {
        const P = this.p;
        if (P.churn_guard <= 0 || this.bought[s] === 0 || this.pHold(s, v) < P.churn_p) return 0;
        return (P.churn_guard * this.cost[s]) / this.bought[s];
      }
      // Option value of waiting: until the market shows whether the suit is the goal, a card
      // may yet pay out / sell to bonus chasers, or be dumped later; the premium fades by the bell.
      holdFloor(s, v, tick) {
        const P = this.p;
        if (P.hold_goal <= 0 && P.hold_dead <= 0) return 0;
        return this.waitValue(s, v, tick, this.pHold(s, v));
      }
      // Value of keeping a card of s for now, if it is the goal with probability p.
      waitValue(s, v, tick, p) {
        const P = this.p;
        const pg = v.pGoal[s];
        const ifGoal = pg > 0.02 ? v.sell[s] / pg : GOAL_PAYOUT;
        const w = Math.max(0, 1 - tick / Math.max(1, this.ticks));
        return p * Math.max(ifGoal, w * P.hold_goal) + (1 - p) * w * P.hold_dead;
      }
      // Likelihood ratio that an offer's suit is the goal given that someone lifts it: fill_lr_offer
      // at the open, fading toward 1 with time constant fill_tau ticks (figgie/shark.py).
      offerLR(tick) {
        const P = this.p;
        if (P.fill_lr_offer === 1 || P.fill_tau <= 0) return 1;
        return 1 + (P.fill_lr_offer - 1) * Math.exp(-tick / P.fill_tau);
      }
      // smart_confirm > 0: another player's bid only counts once it has rested through that many of
      // our turns, been outbid by someone else, or been cleared by a trade after we saw it (figgie/shark.py)
      onQuote(ev) {
        if (ev.tick === undefined) ev = Object.assign({}, ev, { tick: this.now });
        if (this.resale && this.resale === this.learner) this.learner.quoteSeen(ev.tick, ev.suit, ev.isBid, ev.price, ev.player); // every quote, as it comes
        if (this.resale && !ev.isBid && ev.player !== this.me) this.resale.cheapSeen(ev.tick, ev.suit, ev.price, ev.player);
        if (this.p.smart_confirm > 0 && ev.isBid && ev.player !== this.me) {
          const old = this.pending.get(ev.suit);
          if (old && old[0].player !== ev.player && old[1] >= 1) this.accept(old[0]); // outbid after resting: real
          this.pending.set(ev.suit, [ev, 0, null]); // [bid, ticks seen standing, last tick seen]
          return;
        }
        this.accept(ev);
      }
      accept(ev) {
        if (this.resale && ev.isBid && ev.player !== this.me) {
          this.resale.bidSeen(ev.tick !== undefined ? ev.tick : this.now, ev.suit, ev.price, ev.player); // only bids that proved real
        }
        if (this.beliefs.observeQuote(ev)) this.dirty = true;
      }
      checkPending(m) {
        for (const s of [...this.pending.keys()]) {
          const entry = this.pending.get(s);
          const ev = entry[0];
          const cur = m.bestBid(s);
          if (cur !== null && cur.player === ev.player && cur.price === ev.price) {
            if (entry[2] !== m.tick) {
              // once per tick (= second live), however often we act
              entry[1] += 1;
              entry[2] = m.tick;
              if (entry[1] >= this.p.smart_confirm) {
                this.pending.delete(s);
                this.accept(ev);
              }
            }
          } else {
            this.pending.delete(s); // gone without a trade or a higher bid: pulled, so ignore it
          }
        }
      }
      alpha(tick) {
        const a0 = this.p.alpha_start;
        const a1 = this.p.alpha_end;
        const frac = Math.min(1, tick / Math.max(1, this.ticks - 1));
        return a0 * Math.pow(a1 / a0, frac);
      }
      valuation(tick) {
        const fade = this.p.smart_colour_fade;
        if (fade > 0 && this.beliefs.smart) {
          // early bids read as colour evidence, turning suit-specific over `fade` ticks (figgie/shark.py)
          let mix = Math.floor(Math.max(0, 1 - tick / fade) * 20) / 20;
          if (this.colourScale !== 1) mix *= this.colourScale; // read_learn: how far colour reading works here
          if (mix !== this.beliefs.smartColourMix) {
            this.beliefs.setSmartColourMix(mix);
            this.dirty = true;
          }
        }
        if (this.reading.weight > 0 && tick - this.readTick >= this.p.read_every) {
          this.beliefs.refreshQuoteReading(this.reading);
          this.readTick = tick;
          this.dirty = true;
        }
        if (this.dirty || !this.val || tick - this.valTick >= this.p.revalue_every) {
          this.val = this.beliefs.valuation(round2(this.alpha(tick)));
          this.valTick = tick;
          this.dirty = false;
        }
        this.track(tick, this.val.pGoal);
        return this.val;
      }
      // opts.takeOnly: only cross the spread; opts.suitOrder: order to quote suits in
      // the bell (the adapter calls it with the goal figgie.com reveals): read_learn updates
      endRound(goal) {
        if (this.reader && this.p.read_learn) this.reader.endRound(goal, this.earlyTop, this.consensusSuit());
      }
      // the suit every opponent has bid up the most (the highest of the lowest per-opponent top
      // bids), if that lowest bid clears the consensus midpoint by $3 and no suit ties it
      consensusSuit() {
        const b = this.beliefs;
        if (b.others.length < 2) return null;
        const lows = SUITS.map((s) => Math.min(...b.others.map((p) => b.topBy.get(p)[s] || 0)));
        const best = Math.max(...lows);
        if (best < this.p.smart_consensus_mid + 3 || lows.filter((x) => x === best).length > 1) return null;
        return lows.indexOf(best);
      }
      act(m, opts) {
        opts = opts || {};
        this.now = m.tick;
        if (!this.earlyDone && m.tick >= this.p.read_learn_at) {
          this.earlyDone = true;
          const tops = this.beliefs.topBid.map((x) => (x !== null ? x : 0));
          const best = Math.max(...tops);
          this.earlyTop = best > 0 && tops.filter((x) => x === best).length === 1 ? tops.indexOf(best) : null;
        }
        if (this.pending.size) this.checkPending(m);
        if (this.resale) {
          this.resale.expire(m.tick);
          this.resaleBuy = null; // a resale buy that has not filled by now never will
        }
        let v = this.valuation(m.tick);
        if (this.resale && this.resale === this.learner) this.learner.ctxPg = v.pGoal.slice(); // the learner's p_goal feature
        const took = this.take(m, v);
        if (opts.takeOnly || (took && !this.quoteAfterTake)) return took;
        if (took) v = this.valuation(m.tick);
        this.quote(m, v, opts.suitOrder || SUITS);
        return took;
      }
      // Expected gain from buying a card of s at `price` to resell it, if the resale pattern is
      // live and there is room for another resale card (null otherwise).
      resaleGain(m, s, price) {
        const r = this.resale;
        const P = this.p;
        if (!r || this.ticks - m.tick < P.resale_min_left || price > m.cash) return null;
        if (r.held(s) >= P.resale_suit_cap || r.heldTotal() >= r.allowed(P.resale_total_cap)) return null;
        let g;
        if (r === this.learner) {
          // who is selling (when it's the offer we'd lift), and what the card is worth to us anyway
          const off = m.bestOffer(s);
          const seller = off !== null && off.price === price && off.player !== this.me ? off.player : null;
          const hold = this.val ? this.val.sell[s] : 0;
          g = r.valueAt(m.tick, s, price, seller, hold);
        } else g = r.value(price);
        return g !== null && g >= P.resale_edge ? g : null;
      }
      take(m, v) {
        const P = this.p;
        const hand = m.hand;
        const r = this.resale;
        const takeFrac = P.take_frac;
        let best = null;
        for (const s of SUITS) {
          const off = m.bestOffer(s);
          if (off !== null && off.player !== this.me && off.price <= m.cash) {
            const val = Math.min(v.buyFrom[s][this.slot.get(off.player)], P.max_pay * this.pPay(s, v));
            const gain = val - off.price;
            if (gain >= P.take_edge + takeFrac * val) {
              if (best === null || gain > best[0]) best = [gain, true, s, off.price, false];
            } else if (r) {
              const g = this.resaleGain(m, s, off.price);
              if (g !== null && (best === null || g > best[0])) best = [g, true, s, off.price, true];
            }
          }
          const bid = m.bestBid(s);
          if (bid !== null && bid.player !== this.me && hand[s] > 0) {
            const keep = v.sellTo[s][this.slot.get(bid.player)];
            const val = Math.max(keep, this.sellFloor(s, v), this.holdFloor(s, v, m.tick));
            const gain = bid.price - val;
            if (gain >= P.take_edge + takeFrac * val) {
              if (best === null || gain > best[0]) best = [gain, false, s, bid.price, false];
            } else if (r && r.held(s) > 0) {
              // a resale card: sell it into the first bid that pays the resale target, unless the
              // card is worth more to us than that bid
              const target = r.target(s, m.tick, P.resale_patience);
              const g = bid.price - keep;
              if (bid.price >= target && g >= P.take_edge && (best === null || g > best[0])) best = [g, false, s, bid.price, true];
            }
          }
        }
        if (best === null) return false;
        const [, isBuy, s, price, resale] = best;
        if (!isBuy) return Boolean(m.sell(s, price));
        if (resale) this.resaleBuy = s; // onTrade books the card as resale stock when the fill comes
        return Boolean(m.buy(s, price));
      }
      quote(m, v, suitOrder) {
        const P = this.p;
        const hand = m.hand;
        const step = P.step_every <= 1 || m.tick % P.step_every === 0 ? P.step : 0;
        const quoteFrac = P.quote_frac;
        for (const s of suitOrder) {
          let b = v.buy[s];
          let a = v.sell[s];
          if (hand[s] > 0 && b > a) {
            b = a = 0.5 * (b + a); // locally convex: price both sides off the chord
          }
          const pg = v.pGoal[s];
          const bidValue = Math.min(b, P.max_pay * this.pPay(s, v)) * (1 - quoteFrac - P.adverse);
          let bidLimit = Math.min(m.cash, Math.floor(bidValue - P.quote_edge));
          if (P.resale_bid && this.resale) {
            // while the resale pattern is live, stand ready to buy dumped cards ourselves
            this.resaleBids[s] = 0;
            for (let price = P.resale_cheap; price > Math.max(bidLimit, 0); price--) {
              if (this.resaleGain(m, s, price) !== null) {
                bidLimit = this.resaleBids[s] = price;
                break;
              }
            }
          }
          workBid(m, s, bidLimit, Math.floor(bidLimit * P.open_frac), step);
          if (hand[s] > 0) {
            // up to v10, offers leaned toward the card's value if the suit is the goal (adverse_offer,
            // off since v11: fill_lr_offer prices an informed lifter, and fades as the market speaks)
            const ifGoal = pg > 0.02 ? a / pg : 0;
            const askValue = a * (1 + quoteFrac) + P.adverse_offer * P.adverse * Math.max(0, ifGoal - a) + P.quote_edge;
            let holdValue = this.holdFloor(s, v, m.tick) * (1 + quoteFrac) + P.quote_edge;
            const lr = this.offerLR(m.tick);
            if (lr > 1 && (P.hold_goal > 0 || P.hold_dead > 0)) {
              // early on, a lift says the buyer knows more than we do: ask at least what keeping
              // the card is worth given that someone lifted it
              const ph = this.pHold(s, v);
              const lifted = (ph * lr) / (ph * lr + 1 - ph);
              holdValue = Math.max(holdValue, this.waitValue(s, v, m.tick, lifted) * (1 + quoteFrac) + P.quote_edge);
            }
            const askLimit = Math.ceil(Math.max(askValue, holdValue, this.sellFloor(s, v)));
            workOffer(m, s, askLimit, askLimit + Math.ceil(P.open_markup), step);
          }
        }
      }
    }

    return {
      NUM_SUITS,
      SUIT_KEYS,
      SUIT_SYMBOLS,
      CONFIGS,
      comb,
      handLikelihood,
      suitConstraintProb,
      posterior,
      goalProbs,
      compositions,
      quoteLikelihood,
      smartMoneyLogLR,
      smartMoneyLikelihood,
      smartMoneyVotesLikelihood,
      SMART_DEFAULTS,
      valueCards,
      Beliefs,
      ResaleTracker,
      ResaleLearner,
      ReadingLearner,
      SharkBot,
      SHARK_DEFAULTS,
      workBid,
      workOffer,
    };
  })();

  // ===========================================================================
  // figgie.com adapter
  // ===========================================================================
  function startAdapter() {
    if (window.__figgieShark) return window.__figgieShark;
    const S = Core.SUIT_KEYS;
    const SYM = Core.SUIT_SYMBOLS;
    const CFG = {
      pollMs: 200, // read the game state this often
      takeMs: 250, // look for mispriced quotes to hit/lift this often
      actMs: 1000, // re-quote every suit this often (= one simulator tick)
      ordersPerSec: 4, // hard cap on messages we send
      ticks: 240, // the simulator's round length in ticks
      takeWaitMs: 1500, // after hitting/lifting, wait this long (or for the fill) before quoting again
    };
    // Settings for figgie.com's own bots, on top of the simulator defaults.  Every one of them bids
    // the goal suit up at some point and rarely more than one bids up anything else, so "every
    // opponent bid this suit" (the consensus term) is strong evidence there; the simulator's bots
    // don't behave that way, so it is off by default (see data/live_rounds.json).  Their early bids
    // single out the goal's colour rather than the goal (smart_colour_fade; in 20 logged rounds, 8 of
    // 10 replayed better with it in each half), and they bid cards dumped for $1-2 straight back up to
    // $4+, which the resale exploit buys into (resale_cheap, resale_bid; figgie/patterns.py).  Since
    // v12 it learns which offers resell instead of assuming "$2 or less" (resale_learn), and keeps
    // what it learned from round to round and, saved in this browser, from table to table.
    // v13 also learns from each round's revealed goal how far to trust the colour reading and the
    // consensus here (read_learn), and hardens the resale model against a poisoned tape
    // (resale_robust); the resale model saved by v12 loads into it.
    const LIVE_PARAMS = { smart_consensus: 0.8, smart_colour_fade: 90, resale_cheap: 2, resale_bid: true, resale_learn: true, resale_robust: true, read_learn: true };
    const LEARNER_KEY = 'figgieShark.resaleLearner.v12';
    const READER_KEY = 'figgieShark.reading.v13';
    const app = {
      core: Core,
      cfg: CFG,
      store: null,
      socket: null,
      enabled: false,
      status: 'Starting…',
      roundKey: null,
      bot: null,
      seatIds: [],
      seatIndex: new Map(),
      me: -1,
      mySeat: null,
      nPlayers: 0,
      tradeQueue: [],
      lastBook: null,
      lastAct: 0,
      lastTake: 0,
      pendingTakeUntil: 0,
      tokens: CFG.ordersPerSec,
      lastRefill: Date.now(),
      roundLen: null,
      startChips: null,
      humans: [],
      actions: [],
      tradingOpen: false,
      error: null,
      suitRotation: 0,
      // This round's public tape for later study: every quote change and trade we saw, stamped
      // with the seconds left; our own trades also carry our P(goal) just before and whether we
      // crossed the spread ("took") or were filled on a resting quote.
      log: [],
      lastTakeOrder: null,
    };
    window.__figgieShark = app;
    const clockNow = () => {
      const t = app.store && app.store.timeLeftInMatch;
      return typeof t === 'number' ? Math.round(t * 10) / 10 : null;
    };

    // ----- finding the game -----------------------------------------------------
    // The game store is the value of a React context provider near the root;
    // walking the fiber tree finds it without touching the bundler's module table.
    function findStore() {
      const hosts = [document.getElementById('root')].concat([...document.querySelectorAll('body > div')]).filter(Boolean);
      for (const host of hosts) {
        const key = Object.keys(host).find((k) => k.startsWith('__reactContainer$') || k.startsWith('__reactFiber$'));
        if (!key) continue;
        let start = host[key];
        if (start && start.stateNode && start.stateNode.current) start = start.stateNode.current;
        const stack = [start];
        let seen = 0;
        while (stack.length && seen < 50000) {
          const f = stack.pop();
          seen++;
          if (!f) continue;
          const v = f.memoizedProps && f.memoizedProps.value;
          if (v && typeof v === 'object' && 'tradeRow' in v && typeof v.setTradeValue === 'function' && typeof v.completeTrade === 'function') return v;
          if (f.sibling) stack.push(f.sibling);
          if (f.child) stack.push(f.child);
        }
      }
      return null;
    }

    function ensureSocket() {
      let sock = null;
      try {
        sock = app.store.socket && app.store.socket.getSocket ? app.store.socket.getSocket() : null;
      } catch (e) {
        sock = null;
      }
      if (sock && sock !== app.socket && typeof sock.on === 'function') {
        if (app.socket) {
          try {
            app.socket.off('onEventCompleteTrade', onTradeEvent);
          } catch (e) {
            /* old socket gone */
          }
        }
        sock.on('onEventCompleteTrade', onTradeEvent);
        app.socket = sock;
        app.roundKey = null; // resync the round from the trade tape
      }
    }

    // Only the public part of a fill: suit, price, buyer seat, seller seat.
    function onTradeEvent(payload) {
      try {
        const ids = payload && payload.traderIds;
        const s = payload ? S.indexOf(payload.suit) : -1;
        if (!ids || s < 0 || typeof payload.price !== 'number') return;
        app.tradeQueue.push({ suit: s, price: payload.price, buyerSeat: ids.buyer, sellerSeat: ids.seller });
      } catch (e) {
        /* ignore malformed events */
      }
    }

    // ----- reading public state ----------------------------------------------------
    const handArray = (h) => S.map((k) => (h && typeof h[k] === 'number' ? h[k] : 0));
    const myPlayer = () => {
      const st = app.store;
      if (!st || !st.user || !Array.isArray(st.players)) return null;
      return st.players.find((p) => p.playfabId === st.user.playfabId) || null;
    };
    function quoteAt(s, side) {
      const row = app.store.tradeRow && app.store.tradeRow[S[s]];
      const q = row && row[side];
      return q && q.price !== null && q.price !== undefined && q.seatId !== null && q.seatId !== undefined ? q : null;
    }
    // Trades on the tape, oldest first.  Uses only buyer/seller seat, suit and price.
    function tapeTrades() {
      const hist = (app.store.tradeHistory || []).filter((e) => e && e.type === 'trade' && e.buyer && e.seller);
      const out = hist.map((e) => ({ suit: S.indexOf(e.suit), price: e.price, buyerSeat: e.buyer.seatId, sellerSeat: e.seller.seatId, ts: e.timestamp }));
      if (out.length > 1 && typeof out[0].ts === 'number' && typeof out[out.length - 1].ts === 'number') {
        // timestamps count time remaining in standard games and time elapsed in learning games;
        // either way the list is stored newest-first when its first entry is the most recent
        const first = out[0].ts;
        const last = out[out.length - 1].ts;
        const newestFirst = app.store.isStandardMode === false ? first > last : first < last;
        if (newestFirst) out.reverse();
      }
      return out.filter((t) => t.suit >= 0);
    }

    // ----- round lifecycle ----------------------------------------------------------------
    function startRound(key, me, players) {
      const hand0 = handArray(me.startingHand);
      const n = players.length;
      if (n < 2 || n > 5) return false;
      const H = Math.floor(40 / n); // 2 players: 20 cards, 3: 13 (one card left out), 4: 10, 5: 8
      if (hand0.reduce((a, b) => a + b, 0) !== H) return false; // hand not dealt yet
      app.seatIds = players.map((p) => p.seatId).sort((a, b) => a - b);
      app.seatIndex = new Map(app.seatIds.map((sid, i) => [sid, i]));
      app.mySeat = me.seatId;
      app.me = app.seatIndex.get(me.seatId);
      app.nPlayers = n;
      // The learned-resale model (resale_learn) stays with us from round to round, and is saved in
      // this browser so it carries across tables and reloads.  The hand-built tracker's record
      // carries over at half weight instead (figgie/patterns.py).
      if (app.bot && app.bot.resale && !app.bot.learner) app.resaleMemory = app.bot.resale.memory();
      const bot = new Core.SharkBot(LIVE_PARAMS);
      bot.quoteAfterTake = false;
      if (app.learner) bot.learner = app.learner;
      if (LIVE_PARAMS.read_learn) {
        // v13: what it has learned about reading bids at figgie.com, from earlier rounds and pages
        if (!app.reader) {
          app.reader = new Core.ReadingLearner();
          const saved = loadJSON(READER_KEY);
          if (saved) app.reader.load(saved);
        }
        bot.reader = app.reader;
      }
      const names = app.seatIds.map((sid) => playerName(sid)); // a new table means new opponents
      bot.onStart({ player: app.me, hand: hand0, nPlayers: n, handSize: H, ticks: CFG.ticks, names });
      if (bot.learner) {
        if (!app.learner) {
          const saved = loadLearner();
          if (saved) bot.learner.seed(saved);
        }
        app.learner = bot.learner;
        app.resaleSeed = [bot.learner.roundStartModel()]; // logged, so replays start where we did
      } else {
        app.resaleSeed = bot.resale && app.resaleMemory ? app.resaleMemory.map((x) => (Array.isArray(x) ? x.slice() : x)) : null;
        if (app.resaleSeed) bot.resale.seed(...app.resaleSeed);
      }
      app.tick = 0;
      app.bot = bot;
      app.roundKey = key;
      app.tradeQueue = [];
      app.lastBook = null;
      app.roundLen = null;
      app.pendingTakeUntil = 0;
      app.startChips = me.chipCount;
      app.actions = [];
      app.log = [];
      app.lastTakeOrder = null;
      for (const t of tapeTrades()) feedTrade(t); // catch up if we joined mid-round
      return true;
    }

    function loadJSON(key) {
      try {
        const s = window.localStorage.getItem(key);
        return s ? JSON.parse(s) : null;
      } catch (e) {
        return null;
      }
    }
    function loadLearner() {
      return loadJSON(LEARNER_KEY);
    }
    function saveLearner() {
      try {
        if (app.learner) window.localStorage.setItem(LEARNER_KEY, JSON.stringify(app.learner.memory()[0]));
        if (app.reader) window.localStorage.setItem(READER_KEY, JSON.stringify(app.reader.state()));
      } catch (e) {
        /* storage blocked: it still carries over within this page */
      }
    }
    // forget what the resale model and the bid reading have learned (e.g. before playing very
    // different opponents)
    app.resetLearner = () => {
      app.learner = null;
      app.reader = null;
      try {
        window.localStorage.removeItem(LEARNER_KEY);
        window.localStorage.removeItem(READER_KEY);
      } catch (e) {
        /* nothing saved */
      }
    };

    function feedTrade(t) {
      const buyer = app.seatIndex.get(t.buyerSeat);
      const seller = app.seatIndex.get(t.sellerSeat);
      if (buyer === undefined || seller === undefined || !app.bot) return;
      const entry = { k: 't', at: typeof t.ts === 'number' ? t.ts : clockNow(), s: t.suit, p: t.price, b: buyer, sl: seller };
      if (buyer === app.me || seller === app.me) {
        const v = app.bot.val;
        const o = app.lastTakeOrder;
        entry.pg = v ? v.pGoal.map((x) => Math.round(x * 1000) / 1000) : null;
        entry.took = !!(o && o.s === t.suit && o.buy === (buyer === app.me) && Date.now() - o.ms < 3000);
        if (entry.took) app.lastTakeOrder = null;
      }
      app.log.push(entry);
      const stock = app.bot.resale ? app.bot.resale.heldTotal() : 0;
      app.bot.onTrade({ suit: t.suit, price: t.price, buyer, seller, tick: app.tick || 0 });
      if (app.bot.resale && app.bot.resale.heldTotal() !== stock) entry.rs = true; // bought or sold resale stock
      if (buyer === app.me || seller === app.me) {
        app.pendingTakeUntil = 0;
        const other = playerName(buyer === app.me ? t.sellerSeat : t.buyerSeat);
        note(`${buyer === app.me ? 'Bought' : 'Sold'} ${SYM[t.suit]} @ $${t.price} ${buyer === app.me ? 'from' : 'to'} ${other}`);
      }
    }

    function diffQuotes(traded) {
      const book = S.map((_, s) => ({ bid: quoteAt(s, 'bid'), offer: quoteAt(s, 'offer') }));
      for (let s = 0; s < 4; s++) {
        for (const side of ['bid', 'offer']) {
          const q = book[s][side];
          const sig = q ? q.seatId + ':' + q.price : '';
          const prev = app.lastBook ? app.lastBook[s][side] : '';
          if (q && sig !== prev) {
            const p = app.seatIndex.get(q.seatId);
            if (p !== undefined) app.log.push({ k: side === 'bid' ? 'b' : 'o', at: clockNow(), s, p: q.price, w: p });
            if (p !== undefined && q.seatId !== app.mySeat) app.bot.onQuote({ suit: s, isBid: side === 'bid', price: q.price, player: p, tick: app.tick || 0 });
          } else if (!q && prev && !traded) {
            // a quote withdrawn without a trade (trades clear the whole book; those aren't logged)
            const [seat, price] = prev.split(':').map(Number);
            const p = app.seatIndex.get(seat);
            if (p !== undefined) app.log.push({ k: side === 'bid' ? 'xb' : 'xo', at: clockNow(), s, p: price, w: p });
          }
        }
      }
      app.lastBook = book.map((b) => ({ bid: b.bid ? b.bid.seatId + ':' + b.bid.price : '', offer: b.offer ? b.offer.seatId + ':' + b.offer.price : '' }));
    }

    function playerName(seatId) {
      const p = (app.store.players || []).find((x) => x.seatId === seatId);
      return p ? p.name : 'seat ' + seatId;
    }

    // ----- sending orders ------------------------------------------------------------------
    function spend() {
      const now = Date.now();
      app.tokens = Math.min(CFG.ordersPerSec, app.tokens + ((now - app.lastRefill) / 1000) * CFG.ordersPerSec);
      app.lastRefill = now;
      if (app.tokens < 1) return false;
      app.tokens -= 1;
      return true;
    }

    function note(text) {
      app.actions.unshift(text);
      app.actions.length = Math.min(app.actions.length, 4);
    }

    function makeMarket(tick) {
      const st = app.store;
      const me = myPlayer();
      const hand = handArray(me.currentHand);
      const cash = typeof me.chipCount === 'number' ? me.chipCount : 0;
      const asQuote = (q) => (q ? { price: q.price, player: app.seatIndex.get(q.seatId) } : null);
      const row = (s) => st.tradeRow[S[s]];
      return {
        me: app.me,
        tick,
        hand,
        cash,
        bestBid: (s) => asQuote(quoteAt(s, 'bid')),
        bestOffer: (s) => asQuote(quoteAt(s, 'offer')),
        bid(s, price) {
          price = Math.round(price);
          if (!(price >= 1 && price <= 99 && price <= cash)) return false;
          const off = quoteAt(s, 'offer');
          const cur = quoteAt(s, 'bid');
          if ((off && price >= off.price) || (cur && price <= cur.price)) return false;
          const prev = row(s).prevPlayerBid;
          if (prev && prev.price !== null && prev.price >= price && prev.seatId !== app.mySeat) return false;
          if (!spend()) return false;
          st.setTradeValue(S[s], 'bid', app.mySeat, price);
          return true;
        },
        offer(s, price) {
          price = Math.round(price);
          if (!(price >= 1 && price <= 99) || hand[s] < 1) return false;
          const bid = quoteAt(s, 'bid');
          const cur = quoteAt(s, 'offer');
          if ((bid && price <= bid.price) || (cur && price >= cur.price)) return false;
          const prev = row(s).prevPlayerOffer;
          if (prev && prev.price !== null && prev.price <= price && prev.seatId !== app.mySeat) return false;
          if (!spend()) return false;
          st.setTradeValue(S[s], 'offer', app.mySeat, price);
          return true;
        },
        buy(s, maxPrice) {
          const off = quoteAt(s, 'offer');
          if (!off || off.seatId === app.mySeat || off.price > cash) return false;
          if (maxPrice !== null && maxPrice !== undefined && off.price > maxPrice) return false;
          if (!off.tradeId || off.tradeId === 'no_trade_id_set' || !spend()) return false;
          st.completeTrade(S[s], off.price, { buyer: app.mySeat, seller: off.seatId }, off.tradeId);
          row(s).offer.tradeId = 'no_trade_id_set'; // what the site's own Buy button does
          app.pendingTakeUntil = Date.now() + CFG.takeWaitMs;
          app.lastTakeOrder = { s, buy: true, ms: Date.now() };
          note(`Lifting ${SYM[s]} offer @ $${off.price}`);
          return true;
        },
        sell(s, minPrice) {
          const bid = quoteAt(s, 'bid');
          if (!bid || bid.seatId === app.mySeat || hand[s] < 1) return false;
          if (minPrice !== null && minPrice !== undefined && bid.price < minPrice) return false;
          if (!bid.tradeId || bid.tradeId === 'no_trade_id_set' || !spend()) return false;
          st.completeTrade(S[s], bid.price, { buyer: bid.seatId, seller: app.mySeat }, bid.tradeId);
          row(s).bid.tradeId = 'no_trade_id_set';
          app.pendingTakeUntil = Date.now() + CFG.takeWaitMs;
          app.lastTakeOrder = { s, buy: false, ms: Date.now() };
          note(`Hitting ${SYM[s]} bid @ $${bid.price}`);
          return true;
        },
        cancelBid(s) {
          const cur = quoteAt(s, 'bid');
          if (!cur || cur.seatId !== app.mySeat || !spend()) return false;
          st.cancelTrade(S[s], ['bid']);
          return true;
        },
        cancelOffer(s) {
          const cur = quoteAt(s, 'offer');
          if (!cur || cur.seatId !== app.mySeat || !spend()) return false;
          st.cancelTrade(S[s], ['offer']);
          return true;
        },
      };
    }

    // ----- main loop ---------------------------------------------------------------------------
    // A hidden tab's own timers get throttled (to one wake-up a minute after a few minutes in the
    // background), which stalls the bot mid-round.  A Web Worker's timers keep their pace, so the
    // loop is driven by ticks from a tiny worker, falling back to a plain interval if one can't start.
    function startClock(fn, ms) {
      let fallback = null;
      const useInterval = () => {
        if (fallback === null) fallback = setInterval(fn, ms);
      };
      try {
        const url = URL.createObjectURL(new Blob([`setInterval(() => postMessage(0), ${ms});`], { type: 'text/javascript' }));
        const worker = new Worker(url);
        worker.onmessage = fn;
        worker.onerror = () => {
          worker.terminate();
          useInterval();
        };
        app.clock = 'worker';
      } catch (e) {
        useInterval();
        app.clock = 'interval';
      }
    }

    function loop() {
      try {
        step();
        app.error = null;
      } catch (e) {
        app.error = String((e && e.message) || e);
        app.status = 'Error: ' + app.error;
        console.error('[figgie-shark]', e);
      }
      render();
    }

    function step() {
      if (!app.store) {
        app.store = findStore();
        if (!app.store) {
          app.status = 'Waiting for figgie.com to load…';
          return;
        }
      }
      ensureSocket();
      const st = app.store;
      const me = myPlayer();
      const players = Array.isArray(st.players) ? st.players : [];
      app.tradingOpen = false;
      const onGameScreen = st.isViewingGameScreen === true || st.currentScreen === 'Game';
      if (!st.matchId || !me || (st.user && st.user.isSpectator) || !onGameScreen) {
        app.roundKey = null;
        if (app.bot && app.bot.resale && !app.bot.learner) app.resaleMemory = app.bot.resale.memory();
        if (app.bot && app.bot.learner) saveLearner();
        app.bot = null;
        app.status = 'Open a table: Create New → fill the seats with bots (+) → Allow Players to Join: No → start.';
        return;
      }
      const key = st.matchId + '#' + st.currentRound;
      if (app.roundKey !== key && !startRound(key, me, players)) {
        app.status = 'Waiting for the deal…';
        return;
      }
      // Fair-play guard: every other seat must be a figgie.com bot.
      app.humans = players.filter((p) => p.playfabId !== st.user.playfabId && !(p.isBot && !p.isHumanBot)).map((p) => p.name || 'seat ' + p.seatId);
      const traded = app.tradeQueue.length > 0;
      while (app.tradeQueue.length) feedTrade(app.tradeQueue.shift());
      diffQuotes(traded);

      const t = st.timeLeftInMatch;
      app.tradingOpen = !st.isRoundEnded && !st.isPaused && !st.isReplayMode && !st.timerHasEnded && typeof t === 'number' && (st.isStandardMode === false || t > 0);
      if (st.isRoundEnded || st.timerHasEnded) {
        // chips are read after the ante has been taken, so add it back for the round's P&L
        const pnl = typeof me.chipCount === 'number' && typeof app.startChips === 'number' ? me.chipCount - app.startChips - Math.floor(200 / app.nPlayers) : null;
        app.status = 'Round over' + (pnl !== null ? ` — ${pnl >= 0 ? '+' : '−'}$${Math.abs(pnl)} this round (incl. ante).` : '.');
        if (app.bot && app.endedRound !== app.roundKey) {
          // the bell: figgie.com now shows everyone the goal (never read before the round is
          // over), so the bid reading can score itself against it (read_learn)
          const goal = st.isRoundEnded && st.deck && typeof st.deck.goalSuit === 'string' ? S.indexOf(st.deck.goalSuit) : -1;
          if (goal >= 0) {
            app.bot.endRound(goal);
            app.endedRound = app.roundKey;
          }
        }
        if ((app.learner || app.reader) && app.savedRound !== app.roundKey && (!app.reader || app.endedRound === app.roundKey)) {
          saveLearner(); // what this round taught the models, for the next table or reload
          app.savedRound = app.roundKey;
        }
        return;
      }
      if (!app.tradingOpen) {
        app.status = st.isPaused ? 'Paused by the host.' : 'Waiting for trading to open…';
        return;
      }
      // Map the clock onto the simulator's 240-tick schedule.
      let frac;
      if (st.isStandardMode === false) {
        frac = Math.min(1, t / (20 * 60)); // learning games count up for 20 minutes
      } else {
        app.roundLen = Math.max(app.roundLen || 0, t);
        frac = app.roundLen > 0 ? 1 - t / app.roundLen : 0;
      }
      const tick = Math.max(0, Math.min(CFG.ticks - 1, Math.floor(frac * CFG.ticks)));
      app.tick = tick;

      if (app.humans.length) {
        app.status = `Standing by: ${app.humans.join(', ')} ${app.humans.length > 1 ? 'are' : 'is'} at the table. The shark only plays against figgie.com bots.`;
        return;
      }
      if (!app.enabled) {
        app.status = 'Off — switch ON to let the shark trade your seat.';
        app.bot.valuation(tick); // keep beliefs fresh for the panel
        return;
      }
      app.status = 'Trading';
      const now = Date.now();
      if (now < app.pendingTakeUntil) return; // waiting for our hit/lift to fill
      if (now - app.lastAct >= CFG.actMs) {
        app.lastAct = now;
        app.lastTake = now;
        app.suitRotation = (app.suitRotation + 1) % 4;
        const order = [0, 1, 2, 3].map((i) => (i + app.suitRotation) % 4);
        app.bot.act(makeMarket(tick), { suitOrder: order });
      } else if (now - app.lastTake >= CFG.takeMs) {
        app.lastTake = now;
        app.bot.act(makeMarket(tick), { takeOnly: true });
      }
    }

    // ----- overlay -------------------------------------------------------------------------------
    const host = document.createElement('div');
    host.id = 'figgie-shark';
    host.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:2147483647;';
    const shadow = host.attachShadow({ mode: 'open' });
    shadow.innerHTML = `
      <style>
        :host { all: initial; }
        .panel { width: 340px; font: 12px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: #f4f1ff;
                 background: rgba(24, 18, 56, .94); border: 1px solid rgba(255,255,255,.14); border-radius: 12px;
                 box-shadow: 0 10px 30px rgba(0,0,0,.35); overflow: hidden; font-variant-numeric: tabular-nums; }
        .head { display: flex; align-items: center; gap: 8px; padding: 9px 10px; background: rgba(255,255,255,.06); cursor: pointer; user-select: none; }
        .title { font-weight: 700; font-size: 13px; letter-spacing: .2px; }
        .tick { margin-left: auto; color: #b9b3d9; font-size: 11px; }
        button { font: inherit; font-weight: 700; border: 0; border-radius: 999px; padding: 4px 12px; cursor: pointer; color: #1b1340; background: #b9b3d9; }
        button.on { background: #3ddc97; }
        .body { padding: 8px 10px 10px; }
        .status { color: #d9d4f5; margin-bottom: 8px; }
        .row { display: grid; grid-template-columns: 18px 1fr 34px 46px 76px; align-items: center; gap: 6px; padding: 2px 0; }
        .mkt { text-align: right; color: #f2c14e; font-size: 11px; }
        .sym { font-size: 15px; text-align: center; }
        .red { color: #ff6b81; }
        .bar { height: 7px; border-radius: 4px; background: rgba(255,255,255,.12); overflow: hidden; }
        .bar > i { display: block; height: 100%; background: #f2c14e; border-radius: 4px; }
        .pct { text-align: right; }
        .px { text-align: right; color: #b9b3d9; font-size: 11px; }
        .acts { margin-top: 8px; border-top: 1px solid rgba(255,255,255,.1); padding-top: 6px; color: #d9d4f5; }
        .acts div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .muted { color: #9a93c4; }
        .hidden { display: none; }
      </style>
      <div class="panel">
        <div class="head"><span class="title">\u{1F988} Figgie Shark</span><span class="tick"></span><button class="toggle">OFF</button></div>
        <div class="body">
          <div class="status"></div>
          <div class="rows"></div>
          <div class="acts"></div>
        </div>
      </div>`;
    const $ = (sel) => shadow.querySelector(sel);
    const toggle = $('.toggle');
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      app.enabled = !app.enabled;
      if (!app.enabled) cancelOurQuotes();
      render();
    });
    $('.head').addEventListener('click', () => $('.body').classList.toggle('hidden'));
    const rows = $('.rows');
    // the panel lists the suits in figgie.com's own order (♠ ♣ ♦ ♥); the bot's index order is ♠ ♣ ♥ ♦
    const ROW_ORDER = [0, 1, 3, 2];
    for (const s of ROW_ORDER) {
      const r = document.createElement('div');
      r.className = 'row';
      r.innerHTML = `<span class="sym ${s >= 2 ? 'red' : ''}">${SYM[s]}</span><span class="bar"><i></i></span><span class="pct"></span><span class="mkt"></span><span class="px"></span>`;
      rows.appendChild(r);
    }

    function cancelOurQuotes() {
      if (!app.store || app.mySeat === null) return;
      for (let s = 0; s < 4; s++) {
        for (const side of ['bid', 'offer']) {
          const q = quoteAt(s, side);
          if (q && q.seatId === app.mySeat) app.store.cancelTrade(S[s], [side]);
        }
      }
    }

    let lastRender = 0;
    function render() {
      const now = Date.now();
      if (now - lastRender < 200) return;
      lastRender = now;
      if (!host.isConnected && document.body) document.body.appendChild(host);
      toggle.textContent = app.enabled ? 'ON' : 'OFF';
      toggle.className = 'toggle' + (app.enabled ? ' on' : '');
      $('.status').textContent = app.status;
      $('.tick').textContent = app.bot && app.tradingOpen ? `tick ${app.tick}/240` : '';
      const v = app.bot && app.bot.val;
      const pg = app.bot ? app.bot.beliefs.pGoal() : null;
      const hand = app.bot ? app.bot.beliefs.hand : null;
      [...rows.children].forEach((r, i) => {
        const s = ROW_ORDER[i];
        const p = pg ? pg[s] : 0;
        r.querySelector('.bar > i').style.width = (p * 100).toFixed(0) + '%';
        r.querySelector('.pct').textContent = pg ? (p * 100).toFixed(0) + '%' : '—';
        r.querySelector('.px').textContent = v ? `buy ${v.buy[s].toFixed(0)} · sell ${hand && hand[s] > 0 ? v.sell[s].toFixed(0) : '–'}` : '';
        const top = app.bot ? app.bot.beliefs.topBid[s] : null;
        r.querySelector('.mkt').textContent = top !== null ? `bid $${top}` : '';
        r.title = pg
          ? `P(goal = ${S[s]}) = ${(p * 100).toFixed(1)}%. Highest bid by another player: ${top !== null ? '$' + top : 'none'}. ` +
            `Worth to you: next card $${v ? v.buy[s].toFixed(1) : '?'}`
          : '';
      });
      const r = app.bot && app.bot.resale;
      const learned = r && r === app.bot.learner;
      const resale = r
        ? `<div class="muted">Resale ${r.active() ? 'on' : 'off'}: ${r.heldTotal()} held, ${Math.round(r.ownHits)}/${Math.round(r.ownMisses)} resold/failed, ${r.realized >= 0 ? '+' : '−'}$${Math.abs(Math.round(r.realized))}</div>` +
          (learned ? `<div class="muted" title="Learned from every offer it has watched; our own resales scale it (1 = as predicted)">Learned from ${r.nObs} offers · $1 resells ${Math.round(100 * r.pHit())}% · our record ×${r.calibration().toFixed(2)}</div>` : '')
        : '';
      const rd = app.bot && app.bot.reader;
      const reading = rd
        ? `<div class="muted" title="How far it trusts reading early bids by colour, and the suit every bot bids up, at this table: learned from the goals revealed at the bell">Reading: colour ×${rd.pColour().toFixed(2)} · consensus ×${rd.pConsensus().toFixed(2)} (${rd.rounds} rounds)</div>`
        : '';
      $('.acts').innerHTML = (app.actions.length ? app.actions.map((a) => `<div>${a}</div>`).join('') : '<div class="muted">No trades yet.</div>') + resale + reading;
    }

    startClock(loop, CFG.pollMs);
    loop();
    return app;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = Core; // for tests
  } else if (typeof window !== 'undefined') {
    window.FiggieSharkCore = Core;
    if (/(^|\.)figgie\.com$/.test(window.location.hostname) && window.location.pathname.indexOf('/play') === 0) startAdapter();
  }
})();
