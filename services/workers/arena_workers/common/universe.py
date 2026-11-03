"""The single source of truth for tradable symbols."""

EQUITIES: tuple[str, ...] = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM")
CRYPTO: tuple[str, ...] = ("BTC/USD", "ETH/USD")
UNIVERSE: tuple[str, ...] = EQUITIES + CRYPTO
BENCHMARK_SYMBOL = "SPY"


def is_crypto(symbol: str) -> bool:
    return symbol in CRYPTO
