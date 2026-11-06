"""What a sampling forecaster hands the Analyst: many simulated futures boiled down to three numbers.

A forecaster looks at the recent five-minute candles of one symbol and simulates `paths` possible next
`horizon` candles. We only keep where each simulated path ends up, as a return from the last close:

- `exp_ret`: the average of those end points.
- `p_up`: the share of paths that end above the last close. This is the model's confidence in direction.
- `sd`: how widely the end points spread, i.e. how unsure the model is.

Nothing here knows about any particular model. `KronosForecaster` (strategies/kronos_model.py) is the live one;
tests use a stub. If no model can be loaded, `load_forecaster` returns None and the Analyst keeps its old rules.
"""

import importlib
import logging
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from ..common.models import Bar

log = logging.getLogger("strategies")

HORIZON_BARS = 6  # 30 minutes of five-minute candles: long enough to beat costs, short enough to be a day trade
SAMPLE_PATHS = 16  # simulated futures per decision
CONTEXT_BARS = 100  # regular-session candles the model reads (about a day and a quarter)


@dataclass(frozen=True, slots=True)
class Outlook:
    exp_ret: float  # mean return from the last close to the end of the horizon, as a fraction (0.002 is +0.2%)
    p_up: float  # share of simulated paths that end above the last close
    sd: float  # standard deviation of the end-of-horizon returns
    horizon: int  # candles looked ahead
    paths: int  # simulated paths behind the numbers


class Forecaster(Protocol):
    def outlook(self, symbol: str, bars: Sequence[Bar]) -> Outlook | None:
        """Simulate the next candles for `symbol` from `bars` (oldest first). None means no usable forecast."""
        ...


def summarise(last_close: float, paths: Sequence[Sequence[float]]) -> Outlook | None:
    """Boil simulated close-price paths (each ordered from the first future candle) into an Outlook."""
    if last_close <= 0:
        return None
    ends = [p[-1] / last_close - 1.0 for p in paths if p and math.isfinite(p[-1]) and p[-1] > 0]
    if len(ends) < 2:
        return None
    mean = sum(ends) / len(ends)
    sd = math.sqrt(sum((e - mean) ** 2 for e in ends) / (len(ends) - 1))
    horizon = max(len(p) for p in paths)
    return Outlook(mean, sum(e > 0 for e in ends) / len(ends), sd, horizon, len(ends))


def load_forecaster() -> Forecaster | None:
    """The live forecaster, or None when the model is unavailable. Never raises.

    Set KRONOS_DISABLED=1 to switch the model off without redeploying code: the Analyst then runs its old rules.
    """
    if os.environ.get("KRONOS_DISABLED") == "1":
        log.warning("KRONOS_DISABLED=1: the Analyst runs its scorecard rules")
        return None
    try:
        # Imported by name so a deploy without the optional torch install still starts and falls back cleanly.
        module = importlib.import_module(f"{__package__}.kronos_model")
        return cast(Forecaster, module.KronosForecaster())
    except Exception as exc:  # missing torch, missing weights, a broken install: all mean "no model"
        log.warning("forecast model unavailable (%s: %s); the Analyst runs its scorecard rules",
                    type(exc).__name__, exc)
        return None
