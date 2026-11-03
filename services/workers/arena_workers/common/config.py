import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    env: str
    database_url: str
    arena_key: str
    execution_url: str
    alpaca_key: str
    alpaca_secret: str
    alpaca_trading_url: str
    alpaca_data_url: str
    data_source: str
    anthropic_key: str
    agent_model: str
    agent_max_calls: int


def load_settings() -> Settings:
    e = os.environ.get
    return Settings(
        env=e("ARENA_ENV", "development"),
        database_url=e("DATABASE_URL", "postgresql://arena@localhost:5433/arena"),
        arena_key=e("ARENA_KEY", "change-me"),
        execution_url=e("EXECUTION_URL", "http://localhost:8081"),
        alpaca_key=e("ALPACA_API_KEY", ""),
        alpaca_secret=e("ALPACA_API_SECRET", ""),
        alpaca_trading_url=e("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets"),
        alpaca_data_url=e("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
        data_source=e("MARKET_DATA_SOURCE", "synthetic"),
        anthropic_key=e("ANTHROPIC_API_KEY", ""),
        agent_model=e("AGENT_MODEL", "claude-sonnet-5-5"),
        agent_max_calls=int(e("AGENT_MAX_CALLS_PER_DAY", "30")),
    )
