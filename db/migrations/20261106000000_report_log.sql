-- migrate:up
CREATE TABLE IF NOT EXISTS report_log (
  day DATE PRIMARY KEY,
  sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- migrate:down
DROP TABLE IF EXISTS report_log;
