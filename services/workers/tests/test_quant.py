import math

from conftest import make_bars

from arena_workers.common.models import Position
from arena_workers.strategies.quant import StatArb
from arena_workers.strategies.rules import build_strategy


def _noise(i: int, salt: int) -> float:
    return math.sin(i * 12.9898 + salt * 78.233) * 0.5 + math.sin(i * 3.7 + salt) * 0.5  # deterministic, in [-1, 1]


def _pair(n: int = 80, beta: float = 1.4, shock: float = 0.0) -> tuple[list[float], list[float]]:
    """A market and a stock that is `beta` times the market plus a mean-reverting residual."""
    market, stock, lm, resid = [], [], math.log(500.0), 0.0
    for i in range(n):
        lm += _noise(i, 1) * 0.006
        resid = 0.5 * resid + _noise(i, 2) * 0.002
        market.append(math.exp(lm))
        stock.append(100.0 * math.exp(beta * (lm - math.log(500.0)) + resid + (shock if i == n - 1 else 0.0)))
    return market, stock


def test_buys_when_stock_is_cheap_against_the_market() -> None:
    market, stock = _pair(shock=-0.02)
    sig = StatArb().on_bar("AAPL", make_bars(stock), None, benchmark=make_bars(market))
    assert sig is not None and sig.side == "BUY" and sig.bot_slug == "quant"
    metrics = {e["metric"]: e["value"] for e in sig.evidence}
    assert metrics["S_SCORE"] <= -1.25 and 1.0 < metrics["BETA"] < 1.8
    assert 0.0 < sig.target_pct <= 0.10 and "AAPL" in sig.rationale


def test_no_signal_when_stock_is_expensive_or_fair() -> None:
    market, stock = _pair(shock=0.02)
    assert StatArb().on_bar("AAPL", make_bars(stock), None, benchmark=make_bars(market)) is None


def test_sells_once_the_gap_closes() -> None:
    market, stock = _pair(shock=0.0)
    held = Position("AAPL", 10, stock[-1])
    sig = StatArb().on_bar("AAPL", make_bars(stock), held, benchmark=make_bars(market))
    assert sig is not None and sig.side == "SELL"


def test_stop_loss_exits_a_broken_trade() -> None:
    market, stock = _pair(shock=-0.02)
    held = Position("AAPL", 10, stock[-1] * 1.10)
    sig = StatArb().on_bar("AAPL", make_bars(stock), held, benchmark=make_bars(market))
    assert sig is not None and sig.side == "SELL" and "broken" in sig.rationale


def test_higher_volatility_gets_a_smaller_position() -> None:
    market, calm = _pair(shock=-0.02)
    a = StatArb().on_bar("AAPL", make_bars(calm), None, benchmark=make_bars(market))
    b = StatArb(target_vol=0.05).on_bar("AAPL", make_bars(calm), None, benchmark=make_bars(market))
    assert a is not None and b is not None and b.target_pct < a.target_pct


def test_skips_benchmark_crypto_missing_data_and_warmup() -> None:
    market, stock = _pair(shock=-0.02)
    s, m = make_bars(stock), make_bars(market)
    assert StatArb().on_bar("SPY", m, None, benchmark=m) is None
    assert StatArb().on_bar("BTC/USD", s, None, benchmark=m) is None
    assert StatArb().on_bar("AAPL", s, None, benchmark=None) is None
    assert StatArb().on_bar("AAPL", s[:30], None, benchmark=m[:30]) is None


def test_pure_trend_without_reversion_is_ignored() -> None:
    market, _ = _pair()
    trend = [100.0 * (1.001 ** i) for i in range(80)]
    assert StatArb().on_bar("AAPL", make_bars(trend), None, benchmark=make_bars(market)) is None


def test_build_strategy_knows_stat_arb() -> None:
    assert isinstance(build_strategy("stat-arb", {"window": 40}), StatArb)


def test_short_leg_sells_a_rich_stock_and_covers_when_the_gap_closes() -> None:
    market, rich = _pair(shock=0.02)
    s, m = make_bars(rich), make_bars(market)
    assert StatArb().on_bar("AAPL", s, None, benchmark=m) is None  # long-only by default
    sig = StatArb(allow_short=True).on_bar("AAPL", s, None, benchmark=m)
    assert sig is not None and sig.side == "SHORT" and 0.0 < sig.target_pct <= 0.10
    assert {e["metric"]: e["value"] for e in sig.evidence}["S_SCORE"] >= 1.25

    market, fair = _pair(shock=-0.004)  # back below its norm, so the short has nothing left to earn
    held = Position("AAPL", -10, fair[-1])
    sig = StatArb(allow_short=True).on_bar("AAPL", make_bars(fair), held, benchmark=make_bars(market))
    assert sig is not None and sig.side == "COVER"


def test_a_short_is_stopped_out_when_the_stock_keeps_rising() -> None:
    market, rich = _pair(shock=0.02)
    held = Position("AAPL", -10, rich[-1] * 0.90)
    sig = StatArb(allow_short=True).on_bar("AAPL", make_bars(rich), held, benchmark=make_bars(market))
    assert sig is not None and sig.side == "COVER" and "broken" in sig.rationale


def test_a_long_waits_for_full_reversion_when_exit_is_zero() -> None:
    market, cheap = _pair(shock=-0.004)  # a little below its norm: past -0.5, short of 0
    s, m = make_bars(cheap), make_bars(market)
    held = Position("AAPL", 10, cheap[-1])
    early = StatArb(exit_=3.0).on_bar("AAPL", s, held, benchmark=m)
    assert early is not None and early.side == "SELL"
    score = {e["metric"]: e["value"] for e in early.evidence}["S_SCORE"]
    assert score < 0
    assert StatArb(exit_=0.0).on_bar("AAPL", s, held, benchmark=m) is None


def test_the_seeded_quant_waits_for_a_big_stretch_and_loads_enough_history() -> None:
    from arena_workers.common.db import BOT_SEED
    params = next(b["params"] for b in BOT_SEED if b["slug"] == "quant")
    strat = build_strategy("stat-arb", params)
    assert isinstance(strat, StatArb) and not strat.allow_short and strat.window == 120 and strat.entry == 2.0
    assert strat.exit == 0.0
    assert strat.history_bars >= strat.window + 2
