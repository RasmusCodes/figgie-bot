"""Run many games between bots and summarise who makes money."""
from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass, field
from multiprocessing import Pool
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .adversaries import AdaptBot, Bait2Bot, BaitBot, HoldoutBot, PennyBot, PumpBot, QuietBot, SniperBot, SpooferBot
from .bots import CounterBot, FickleBot, HandBot, NoiseBot, OracleBot
from .engine import NUM_SUITS, SUITS, Bot, Game, GameResult, Rules, Trade
from .shark import (
    SHARK_LIVE,
    SHARK_LIVE_V12,
    SHARK_V1,
    SHARK_V2,
    SHARK_V3,
    SHARK_V4,
    SHARK_V5,
    SHARK_V6,
    SHARK_V8,
    SHARK_V10,
    OracleSharkBot,
    SharkBot,
)


def _shark_v1(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V1, **kw})


def _shark_v2(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V2, **kw})


def _shark_v3(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V3, **kw})


def _shark_v4(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V4, **kw})


def _shark_v5(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V5, **kw})


def _shark_v6(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V6, **kw})


def _shark_v8(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V8, **kw})


def _shark_v10(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_V10, **kw})


def _shark_live(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_LIVE, **kw})


def _shark_v12(**kw) -> SharkBot:
    return SharkBot(**{**SHARK_LIVE_V12, **kw})


REGISTRY: Dict[str, Callable[..., Bot]] = {
    "shark": SharkBot,
    "sharklive": _shark_live,
    "sharkv12": _shark_v12,
    "sharkv1": _shark_v1,
    "sharkv2": _shark_v2,
    "sharkv3": _shark_v3,
    "sharkv4": _shark_v4,
    "sharkv5": _shark_v5,
    "sharkv6": _shark_v6,
    "sharkv8": _shark_v8,
    "sharkv10": _shark_v10,
    "hand": HandBot,
    "counter": CounterBot,
    "oracle": OracleBot,
    "oshark": OracleSharkBot,
    "spoofer": SpooferBot,
    "fickle": FickleBot,
    "bait": BaitBot,
    "bait2": Bait2Bot,
    "pump": PumpBot,
    "sniper": SniperBot,
    "penny": PennyBot,
    "quiet": QuietBot,
    "holdout": HoldoutBot,
    "adapt": AdaptBot,
    "noise": NoiseBot,
}


def _parse_value(text: str):
    low = text.lower()
    if low in ("none", "null"):
        return None
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def make_bot(spec: str) -> Bot:
    """Build a bot from ``name`` or ``name:param=value,param=value``.

    Anything after a ``#`` is a free-form tag (``shark#ref``) that only changes
    the label, so identical bots can be told apart in a results table.
    """
    name, _, arg_str = spec.split("#", 1)[0].partition(":")
    key = name.strip().lower()
    if key not in REGISTRY:
        raise ValueError(f"unknown bot {name!r}; choose from {', '.join(sorted(REGISTRY))}")
    kwargs = {}
    for part in filter(None, (p.strip() for p in arg_str.split(","))):
        k, eq, val = part.partition("=")
        if not eq:
            raise ValueError(f"bad bot parameter {part!r} in {spec!r} (expected name=value)")
        kwargs[k.strip()] = _parse_value(val.strip())
    bot = REGISTRY[key](**kwargs)
    bot.name = spec
    return bot


def play_one(job: Tuple[Sequence[str], int, Rules]) -> Tuple[List[tuple], int]:
    """Play one game with randomly shuffled seats.  Returns per-seat stats."""
    lineup, seed, rules = job
    seats = list(lineup)
    random.Random(seed).shuffle(seats)
    res = Game([make_bot(spec) for spec in seats], rules=rules, seed=seed).run()
    traded = [0] * len(seats)
    for t in res.trades:
        traded[t.buyer] += 1
        traded[t.seller] += 1
    rows = []
    for p, spec in enumerate(seats):
        bonus = 1.0 / len(res.bonus_winners) if p in res.bonus_winners else 0.0
        rows.append((spec, res.pnl[p], bonus, res.goal_counts[p], traded[p]))
    return rows, len(res.trades)


@dataclass
class BotStats:
    label: str
    n: int = 0
    pnl: float = 0.0
    pnl_sq: float = 0.0
    bonus: float = 0.0
    goal_cards: int = 0
    trades: int = 0

    def add(self, pnl: float, bonus: float, goal: int, trades: int) -> None:
        self.n += 1
        self.pnl += pnl
        self.pnl_sq += pnl * pnl
        self.bonus += bonus
        self.goal_cards += goal
        self.trades += trades

    @property
    def mean(self) -> float:
        return self.pnl / self.n if self.n else 0.0

    @property
    def ci95(self) -> float:
        if self.n < 2:
            return float("nan")
        var = (self.pnl_sq - self.n * self.mean**2) / (self.n - 1)
        return 1.96 * math.sqrt(max(var, 0.0) / self.n)


@dataclass
class TournamentResult:
    lineup: List[str]
    games: int
    rules: Rules
    stats: Dict[str, BotStats] = field(default_factory=dict)
    trades_per_game: float = 0.0
    seconds: float = 0.0

    def table(self) -> str:
        lines = [
            f"{self.games} games | lineup: {', '.join(self.lineup)} | "
            f"{self.rules.n_players} players, {self.rules.ticks} ticks | "
            f"{self.trades_per_game:.1f} trades/game | {self.seconds:.1f}s",
            f"{'bot':<34}{'seats':>7}{'mean P&L':>11}{'±95%':>8}{'bonus won':>11}{'goal cards':>12}{'trades':>8}",
        ]
        for st in sorted(self.stats.values(), key=lambda s: -s.mean):
            lines.append(
                f"{st.label:<34}{st.n:>7}{st.mean:>+11.2f}{st.ci95:>8.2f}"
                f"{st.bonus / st.n:>10.1%}{st.goal_cards / st.n:>12.2f}{st.trades / st.n:>8.1f}"
            )
        return "\n".join(lines)


def run_tournament(
    lineup: Sequence[str],
    games: int = 200,
    seed: int = 0,
    rules: Optional[Rules] = None,
    workers: Optional[int] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> TournamentResult:
    rules = rules or Rules(n_players=len(lineup))
    if len(lineup) != rules.n_players:
        raise ValueError(f"lineup has {len(lineup)} bots but rules say {rules.n_players} players")
    for spec in set(lineup):
        make_bot(spec)  # fail fast on typos
    jobs = [(tuple(lineup), seed * 1_000_003 + i, rules) for i in range(games)]
    out = TournamentResult(list(lineup), games, rules)
    workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    total_trades = 0

    def consume(results):
        nonlocal total_trades
        for done, (rows, n_trades) in enumerate(results, 1):
            total_trades += n_trades
            for label, pnl, bonus, goal, trades in rows:
                out.stats.setdefault(label, BotStats(label)).add(pnl, bonus, goal, trades)
            if progress:
                progress(done, games)

    if workers <= 1 or games < 4:
        consume(play_one(j) for j in jobs)
    else:
        with Pool(workers) as pool:
            consume(pool.imap_unordered(play_one, jobs, chunksize=max(1, games // (workers * 8))))
    out.trades_per_game = total_trades / games
    out.seconds = time.time() - t0
    return out


class Narrator:
    """Game observer that prints a play-by-play."""

    def __init__(self, belief_every: int = 40, show_quotes: bool = False, out=print) -> None:
        self.belief_every = belief_every
        self.show_quotes = show_quotes
        self.out = out

    def _who(self, game: Game, p: int) -> str:
        return f"P{p}:{game.names[p]}"

    def on_start(self, game: Game) -> None:
        self.out(f"seed {game.seed} | {game.config.describe()}")
        self.out("seat              S   C   H   D")
        for p, h in enumerate(game.initial_hands):
            self.out(f"{self._who(game, p):<16}" + "".join(f"{x:>4}" for x in h))
        self.out("")

    def on_quote(self, game: Game, ev) -> None:
        if self.show_quotes:
            side = "bids" if ev.is_bid else "offers"
            self.out(f"t={ev.tick:3d}  {self._who(game, ev.player)} {side} {SUITS[ev.suit]} @ ${ev.price}")

    def on_trade(self, game: Game, t: Trade) -> None:
        self.out(
            f"t={t.tick:3d}  {self._who(game, t.buyer)} buys {SUITS[t.suit]} from "
            f"{self._who(game, t.seller)} @ ${t.price}"
        )

    def on_tick(self, game: Game) -> None:
        if self.belief_every and (game.tick + 1) % self.belief_every == 0:
            for p, bot in enumerate(game.bots):
                describe = getattr(bot, "describe", None)
                if describe is not None:
                    self.out(f"      [{self._who(game, p)} thinks] {describe()}")

    def on_end(self, game: Game, res: GameResult) -> None:
        g = res.config.goal
        self.out("")
        self.out(f"goal suit was {SUITS[g]} ({res.config.counts[g]} cards); bonus ${res.config.bonus}")
        self.out(f"{'seat':<16}{'final S C H D':>16}{'goal':>6}{'P&L':>10}")
        for p in range(len(res.names)):
            h = " ".join(str(x) for x in res.final_hands[p])
            star = " *bonus" if p in res.bonus_winners else ""
            self.out(f"{self._who(game, p):<16}{h:>16}{res.goal_counts[p]:>6}{res.pnl[p]:>+10.1f}{star}")
        self.out(f"{len(res.trades)} trades")


def watch(lineup: Sequence[str], seed: Optional[int] = None, rules: Optional[Rules] = None, **narrator_kw) -> GameResult:
    rules = rules or Rules(n_players=len(lineup))
    bots = [make_bot(spec) for spec in lineup]
    return Game(bots, rules=rules, seed=seed, observers=[Narrator(**narrator_kw)]).run()
