-- migrate:up
-- Orders and signals gain two sides: SHORT opens a short position and COVER closes it.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conrelid::regclass AS tbl, conname FROM pg_constraint
           WHERE contype = 'c' AND conrelid IN ('signals'::regclass, 'orders'::regclass)
             AND pg_get_constraintdef(oid) LIKE '%(side = ANY%'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', c.tbl, c.conname);
  END LOOP;
END $$;
ALTER TABLE signals ADD CONSTRAINT signals_side_check CHECK (side IN ('BUY','SELL','SHORT','COVER'));
ALTER TABLE orders ADD CONSTRAINT orders_side_check CHECK (side IN ('BUY','SELL','SHORT','COVER'));

-- migrate:down
ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_side_check;
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_side_check;
ALTER TABLE signals ADD CONSTRAINT signals_side_check CHECK (side IN ('BUY','SELL'));
ALTER TABLE orders ADD CONSTRAINT orders_side_check CHECK (side IN ('BUY','SELL'));
