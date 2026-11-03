"""Code-side checks applied to the model's proposal before anything reaches the execution service (spec 8.4)."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..common.universe import CRYPTO, UNIVERSE, is_crypto
from .tools import ToolBox

MAX_RATIONALE = 240
MAX_NOTE = 200
MAX_POSITIONS = 5


class Evidence(BaseModel):
    metric: str
    value: float


class Decision(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"]
    target_pct: float = 0.0
    confidence: float
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale is empty")
        return v


class AgentOutput(BaseModel):
    decisions: list[Decision]
    market_note: str | None = None


@dataclass
class Review:
    valid: bool
    approved: list[Decision] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (symbol, reason)
    market_note: str | None = None
    error: str | None = None


_MD = re.compile(r"[*_`#>\[\]]|\n|\r")
_WORD = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
_ALLOWED_WORDS = {"RSI", "SMA", "EMA", "ET", "USD", "USA", "AM", "PM", "OK", "HOLD", "BUY", "SELL", "US"}
_KNOWN = {s.split("/")[0] for s in UNIVERSE} | _ALLOWED_WORDS


def clean_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", _MD.sub(" ", text)).strip()
    return text[:limit].rstrip()


def mentions_outside_universe(text: str) -> bool:
    return any(w not in _KNOWN for w in _WORD.findall(text))


def review(raw: Any, tools: ToolBox, portfolio: dict[str, Any], equities_open: bool) -> Review:
    """Validate the proposal. A schema failure turns the whole run into HOLD."""
    try:
        out = AgentOutput.model_validate(raw)
    except ValidationError as exc:
        return Review(valid=False, error=f"schema: {exc.errors()[0]['msg']}")
    rev = Review(valid=True)
    if out.market_note:
        note = clean_text(out.market_note, MAX_NOTE)
        if not mentions_outside_universe(note):
            rev.market_note = note
    held = {p["symbol"] for p in portfolio.get("positions", [])}
    cash = float(portfolio.get("cash", 0.0))
    equity = float(portfolio.get("equity", 0.0))
    slots = MAX_POSITIONS - len(held)
    for d in out.decisions:
        if d.action == "HOLD":
            continue
        reason = _reject(d, tools, held, cash, equity, slots, equities_open)
        if reason:
            rev.dropped.append((d.symbol, reason))
            continue
        d.rationale = clean_text(d.rationale, MAX_RATIONALE)
        if mentions_outside_universe(d.rationale):
            rev.dropped.append((d.symbol, "off_universe_text"))
            continue
        if d.action == "BUY":
            slots -= 1
            cash -= equity * d.target_pct
            held.add(d.symbol)
        else:
            held.discard(d.symbol)
        rev.approved.append(d)
    return rev


def _reject(d: Decision, tools: ToolBox, held: set[str], cash: float, equity: float, slots: int,
            equities_open: bool) -> str | None:
    if d.symbol not in UNIVERSE:
        return "symbol_not_in_universe"
    if not 0.0 <= d.confidence <= 1.0:
        return "confidence_out_of_range"
    if not is_crypto(d.symbol) and not equities_open:
        return "market_closed"
    if d.action == "BUY":
        if not 0.05 <= d.target_pct <= 0.10:
            return "target_pct_out_of_range"
        if d.symbol in held:
            return "already_holding"
        if slots <= 0:
            return "no_open_slots"
        if cash < equity * d.target_pct:
            return "insufficient_cash"
    elif d.symbol not in held:
        return "no_position_to_sell"
    if not d.evidence:
        return "unsupported_evidence"
    if not all(tools.supports(e.metric, e.value) for e in d.evidence):
        return "unsupported_evidence"
    return None


_ = CRYPTO
