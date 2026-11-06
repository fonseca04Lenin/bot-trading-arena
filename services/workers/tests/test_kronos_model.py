"""These run the real Kronos model, so they need the optional `forecast` install and its cached weights.

CI installs neither, so the whole file is skipped there. To run it locally:
    pip install -e "services/workers[forecast]" && pytest tests/test_kronos_model.py
"""

import random
import time
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("torch")
pytest.importorskip("pandas")

from arena_workers.common.models import Bar  # noqa: E402
from arena_workers.strategies import forecast  # noqa: E402
from arena_workers.strategies.forecast import CONTEXT_BARS, HORIZON_BARS, SAMPLE_PATHS  # noqa: E402
from arena_workers.strategies.forecast_trader import ForecastTrader  # noqa: E402
from arena_workers.strategies.kronos_model import KronosForecaster  # noqa: E402


def walk(n: int, vol: float = 0.0008, volume: float = 5000.0, seed: int = 7) -> list[Bar]:
    rng = random.Random(seed)
    px, t, out = 100.0, datetime(2026, 1, 5, 14, 30, tzinfo=UTC), []
    for _ in range(n):
        c = px * (1 + rng.gauss(0, vol))
        out.append(Bar(t, px, max(px, c) * 1.0004, min(px, c) * 0.9996, c, volume * rng.uniform(0.5, 1.5)))
        px, t = c, t + timedelta(minutes=5)
    return out


@pytest.fixture(scope="module")
def model() -> KronosForecaster:
    return KronosForecaster()


def test_forecasts_a_plausible_outlook_and_fast_enough(model: KronosForecaster) -> None:
    started = time.monotonic()
    out = model.outlook("AAPL", walk(CONTEXT_BARS + 20))
    elapsed = time.monotonic() - started
    assert out is not None and out.paths == SAMPLE_PATHS and out.horizon == HORIZON_BARS
    assert 0.0 <= out.p_up <= 1.0 and out.sd > 0 and abs(out.exp_ret) < 0.05
    assert elapsed < 20, f"one forecast took {elapsed:.1f}s; the worker handles ten symbols per candle"


def test_the_paths_are_separate_futures_not_one_averaged_line(model: KronosForecaster) -> None:
    out = model.outlook("AAPL", walk(CONTEXT_BARS))
    assert out is not None and out.sd > 0  # an averaged path would have no spread at all


def test_too_little_history_gives_no_forecast(model: KronosForecaster) -> None:
    assert model.outlook("AAPL", walk(CONTEXT_BARS - 1)) is None


def test_awkward_inputs_do_not_crash(model: KronosForecaster) -> None:
    flat = [Bar(b.ts, 50.0, 50.0, 50.0, 50.0, 0.0) for b in walk(CONTEXT_BARS)]  # no movement, no volume (crypto-like)
    out = model.outlook("BTC/USD", flat)
    assert out is None or (0.0 <= out.p_up <= 1.0 and abs(out.exp_ret) < 0.5)


def test_the_trader_runs_end_to_end_on_the_real_model(model: KronosForecaster) -> None:
    bars = walk(CONTEXT_BARS + 30, vol=0.004)  # a jumpy symbol, 24/7 so no session rules apply
    sig = ForecastTrader(model, allow_short=False).on_bar("BTC/USD", bars, None)
    assert sig is None or (sig.side == "BUY" and {e["metric"] for e in sig.evidence} >= {"P_UP", "EXP_RET_PCT"})


def test_load_forecaster_returns_the_real_model() -> None:
    assert isinstance(forecast.load_forecaster(), KronosForecaster)
