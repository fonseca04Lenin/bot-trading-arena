-- migrate:up
CREATE TABLE bots (
  id SERIAL PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  strategy_kind TEXT NOT NULL,
  params JSONB NOT NULL DEFAULT '{}',
  silks JSONB NOT NULL DEFAULT '{}',
  starting_cash NUMERIC NOT NULL,
  broker TEXT NOT NULL CHECK (broker IN ('sim','alpaca_paper')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE bars (
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL CHECK (timeframe IN ('1Min','5Min','1Day')),
  ts TIMESTAMPTZ NOT NULL,
  o NUMERIC NOT NULL, h NUMERIC NOT NULL, l NUMERIC NOT NULL, c NUMERIC NOT NULL,
  v NUMERIC NOT NULL DEFAULT 0,
  PRIMARY KEY (symbol, timeframe, ts)
);
CREATE TABLE signals (
  id UUID PRIMARY KEY,
  bot_id INT NOT NULL REFERENCES bots(id),
  symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  target_pct NUMERIC NOT NULL,
  rationale TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '[]',
  bar_ts TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX signals_bot_idx ON signals (bot_id, created_at DESC);
CREATE TABLE orders (
  id UUID PRIMARY KEY,
  signal_id UUID NOT NULL UNIQUE REFERENCES signals(id),
  bot_id INT NOT NULL REFERENCES bots(id),
  symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  qty NUMERIC NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  broker TEXT NOT NULL,
  broker_order_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('submitted','filled','rejected','canceled')),
  reject_reason TEXT,
  latency_ms INT,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX orders_bot_idx ON orders (bot_id, submitted_at DESC);
CREATE INDEX orders_symbol_idx ON orders (symbol, submitted_at DESC);
CREATE TABLE fills (
  id UUID PRIMARY KEY,
  order_id UUID NOT NULL REFERENCES orders(id),
  qty NUMERIC NOT NULL,
  price NUMERIC NOT NULL,
  filled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX fills_order_idx ON fills (order_id);
CREATE TABLE positions (
  bot_id INT NOT NULL REFERENCES bots(id),
  symbol TEXT NOT NULL,
  qty NUMERIC NOT NULL,
  avg_cost NUMERIC NOT NULL,
  PRIMARY KEY (bot_id, symbol)
);
CREATE TABLE cash (
  bot_id INT PRIMARY KEY REFERENCES bots(id),
  amount NUMERIC NOT NULL
);
CREATE TABLE equity_snapshots (
  bot_id INT NOT NULL REFERENCES bots(id),
  ts TIMESTAMPTZ NOT NULL,
  equity NUMERIC NOT NULL,
  PRIMARY KEY (bot_id, ts)
);
CREATE TABLE agent_runs (
  id UUID PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  model TEXT NOT NULL,
  prompt_version TEXT,
  input JSONB,
  output JSONB,
  valid BOOLEAN NOT NULL,
  error TEXT,
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  latency_ms INT NOT NULL DEFAULT 0
);
CREATE INDEX agent_runs_started_idx ON agent_runs (started_at DESC);
CREATE TABLE heartbeats (
  service TEXT PRIMARY KEY,
  last_seen TIMESTAMPTZ NOT NULL,
  info JSONB NOT NULL DEFAULT '{}'
);
CREATE TABLE heartbeat_log (
  service TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (service, ts)
);
CREATE TABLE headlines (
  date DATE PRIMARY KEY,
  headline TEXT NOT NULL,
  deck TEXT NOT NULL
);
CREATE TABLE market_notes (
  id SERIAL PRIMARY KEY,
  note TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION notify_trade() RETURNS trigger AS $$
BEGIN
  IF NEW.status IN ('filled','rejected') THEN
    PERFORM pg_notify('trade_filled', NEW.id::text);
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER orders_notify AFTER INSERT OR UPDATE OF status ON orders
  FOR EACH ROW EXECUTE FUNCTION notify_trade();

-- migrate:down
DROP TABLE IF EXISTS market_notes, headlines, heartbeat_log, heartbeats, agent_runs,
  equity_snapshots, cash, positions, fills, orders, signals, bars, bots CASCADE;
DROP FUNCTION IF EXISTS notify_trade();
