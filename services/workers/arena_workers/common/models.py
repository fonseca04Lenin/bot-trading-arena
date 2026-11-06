from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Side = Literal["BUY", "SELL", "SHORT", "COVER"]


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    qty: float
    avg_cost: float


@dataclass(frozen=True, slots=True)
class Signal:
    bot_slug: str
    symbol: str
    side: Side
    target_pct: float
    rationale: str
    bar_ts: datetime
    evidence: list[dict[str, float | str]] = field(default_factory=list)
