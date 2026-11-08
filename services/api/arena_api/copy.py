"""Plain-English copy for each bot and the glossary (spec 2, 11.7)."""

BOT_COPY: dict[str, str] = {
    "crossover": "Buys when a short-term average price rises above a long-term one, and sells when it falls back below. "
                 "It watches the 20-bar and 50-bar moving averages† on 5-minute bars. This bot routes its orders to Alpaca's paper-trading broker.",
    "rubber-band": "Buys after a sharp drop, betting the price snaps back. It reads the 14-bar RSI†: "
                   "below 30 it buys, above 70 it sells.",
    "breakout": "Buys when price breaks above its recent range: a close above the highest high of the previous 20 bars. "
                "It sells on a close below the lowest low of the previous 10 bars.",
    "index": "Buys the market once and holds. It puts all its cash in SPY on the first open bar and never sells. "
             "It is the benchmark every other bot has to beat.",
    "quant": "Strips the market's move out of a stock, then bets the leftover snaps back. When a stock is unusually cheap "
             "against SPY it buys, sized smaller the more the stock swings, and sells once the gap has closed. "
             "This is the single-factor form of statistical arbitrage.",
    "orb": "A day trader that only bets on falls. It watches the first five minutes of the session: if that candle closes "
           "down it sells short, with a stop at the other end of the candle, and if it closes up it stays out. It closes "
           "everything before the bell and never holds overnight.",
    "analyst": "A day trader run by a forecasting model. Every five minutes it asks Kronos†, an open-source AI trained on "
               "candlestick charts, to simulate the next 30 minutes 16 times. It buys when most simulations end higher and "
               "sells short when most end lower, then closes when the forecast turns, on a stop-loss, or before the bell. "
               "It never holds shares overnight.",
}

GLOSSARY: list[dict[str, str]] = [
    {"term": "sharpe", "label": "Sharpe ratio", "definition": "Average daily return divided by how much those returns swing, scaled to a year; higher means steadier gains per unit of risk."},
    {"term": "drawdown", "label": "Max drawdown", "definition": "The largest fall from a peak in a bot's equity to a later low, as a percentage."},
    {"term": "win-rate", "label": "Win rate", "definition": "The share of closed round trips (a buy followed by a sell) that made money."},
    {"term": "moving-average", "label": "Moving average", "definition": "The average closing price over the last N bars, recomputed on every new bar."},
    {"term": "golden-cross", "label": "Golden cross", "definition": "The moment a short-term moving average climbs above a long-term one, read as a sign of rising momentum."},
    {"term": "rsi", "label": "RSI", "definition": "Relative Strength Index: a 0-100 gauge of recent gains against recent losses; under 30 is called oversold, over 70 overbought."},
    {"term": "equity", "label": "Equity", "definition": "A bot's cash plus the current market value of everything it holds."},
    {"term": "slippage", "label": "Slippage", "definition": "The small gap between the last price and the price a market order actually fills at; here it is 0.02% against the bot."},
    {"term": "paper-trading", "label": "Paper trading", "definition": "Trading with pretend money at real prices, so nothing is at risk."},
    {"term": "benchmark", "label": "Benchmark", "definition": "A plain buy-and-hold of the market (SPY) that active strategies are measured against."},
    {"term": "kronos", "label": "Kronos", "definition": "An open-source AI model trained on candlestick charts from 45 exchanges. Like a language model writing the next words, it writes the next candles; running it many times gives many possible futures."},
    {"term": "short-selling", "label": "Short selling", "definition": "Borrowing shares to sell now and buying them back later. It profits if the price falls and loses if it rises."},
    {"term": "bar", "label": "Bar", "definition": "A summary of a time slice of trading: open, high, low and close prices and volume. Here a bar is five minutes."},
]
