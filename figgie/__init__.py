"""Figgie: a rules-accurate engine, an exact Bayesian card-counting model and trading bots."""
from .bots import CounterBot, HandBot, NoiseBot
from .engine import (
    CONFIGS,
    PARTNER,
    SUIT_CHARS,
    SUITS,
    Bot,
    DeckConfig,
    Game,
    GameInfo,
    GameResult,
    Market,
    Quote,
    QuoteEvent,
    Rules,
    Trade,
)
from .model import Beliefs, Valuation, goal_probs, posterior, value_cards
from .shark import SharkBot, SharkParams
from .tournament import make_bot, run_tournament, watch

__all__ = [
    "CONFIGS", "PARTNER", "SUIT_CHARS", "SUITS", "Bot", "DeckConfig", "Game", "GameInfo", "GameResult",
    "Market", "Quote", "QuoteEvent", "Rules", "Trade", "Beliefs", "Valuation", "goal_probs", "posterior",
    "value_cards", "SharkBot", "SharkParams", "CounterBot", "HandBot", "NoiseBot", "make_bot",
    "run_tournament", "watch",
]
