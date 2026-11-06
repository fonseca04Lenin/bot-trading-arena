"""Kronos-small as the Analyst's forecaster.

Kronos (Shi et al., "Kronos: A Foundation Model for the Language of Financial Markets", arXiv 2508.02739) is an
open-source, MIT-licensed model pre-trained on candlesticks from 45 exchanges. It turns each candle into tokens
and then writes the next candles one token at a time, the way a language model writes the next words. Sampling
that process many times gives many plausible futures, which is what `forecast.summarise` boils down to a direction
and a confidence.

This module imports torch, so only `forecast.load_forecaster()` imports it, and only when a model is wanted. The
weights come from Hugging Face at pinned revisions: the Docker build downloads them once (`fetch_weights`), and
the running worker then loads them from disk.
"""

import logging
import os
import time
from collections.abc import Sequence

from ..common.clock import to_et
from ..common.models import Bar
from .forecast import CONTEXT_BARS, HORIZON_BARS, SAMPLE_PATHS, Outlook, summarise

log = logging.getLogger("strategies")

MODEL_REPO, MODEL_REVISION = "NeoQuasar/Kronos-small", "901c26c1332695a2a8f243eb2f37243a37bea320"
TOKENIZER_REPO, TOKENIZER_REVISION = "NeoQuasar/Kronos-Tokenizer-base", "0e0117387f39004a9016484a186a908917e22426"
MODEL_MAX_CONTEXT = 512  # the most candles Kronos-small can read
BAR_MINUTES = 5


def fetch_weights() -> None:
    """Download the pinned weights into the Hugging Face cache (run at image build time)."""
    from huggingface_hub import snapshot_download

    snapshot_download(TOKENIZER_REPO, revision=TOKENIZER_REVISION)
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION)


class KronosForecaster:
    def __init__(self, paths: int = SAMPLE_PATHS, horizon: int = HORIZON_BARS) -> None:
        import torch

        from ..vendor.kronos import Kronos, KronosPredictor, KronosTokenizer

        # Containers often expose many cores but only a few vCPUs of quota; extra threads then just fight each other.
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        started = time.monotonic()
        tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_REPO, revision=TOKENIZER_REVISION)
        model = Kronos.from_pretrained(MODEL_REPO, revision=MODEL_REVISION)
        tokenizer.eval()
        model.eval()
        self._predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=MODEL_MAX_CONTEXT)
        self.paths, self.horizon = paths, horizon
        log.info("kronos loaded in %.1fs (%s, %d paths, %d candles ahead)", time.monotonic() - started,
                 MODEL_REPO, paths, horizon)

    def outlook(self, symbol: str, bars: Sequence[Bar]) -> Outlook | None:
        if len(bars) < CONTEXT_BARS:
            return None
        import pandas as pd

        window = bars[-CONTEXT_BARS:]
        frame = pd.DataFrame({
            "open": [b.o for b in window], "high": [b.h for b in window],
            "low": [b.l for b in window], "close": [b.c for b in window], "volume": [b.v for b in window],
            # Kronos also reads turnover; like upstream's own default, take volume times the average of the OHLC prices.
            "amount": [b.v * (b.o + b.h + b.l + b.c) / 4 for b in window],
        })
        # Kronos was trained on exchange-local clock times, so give it New York time, not UTC.
        past = pd.Series(pd.to_datetime([to_et(b.ts).replace(tzinfo=None) for b in window]))
        future = pd.Series(pd.date_range(past.iloc[-1] + pd.Timedelta(minutes=BAR_MINUTES),
                                         periods=self.horizon, freq=f"{BAR_MINUTES}min"))
        # predict() averages its samples into one path and so hides the spread. Batching identical copies with one
        # sample each keeps every simulated future separate.
        out = self._predictor.predict_batch(
            [frame] * self.paths, [past] * self.paths, [future] * self.paths, pred_len=self.horizon,
            T=1.0, top_p=0.9, sample_count=1, verbose=False)
        return summarise(window[-1].c, [list(map(float, o["close"])) for o in out])
