#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[RESYNC] running scripts/resync_buy_qty.py"
python -u scripts/resync_buy_qty.py || true

echo "[RESYNC] filling entry_price for OPEN positions with qty_token>0 and entry_price=0"
cat > /tmp/fix_entry_price.sql <<'SQL'
BEGIN;

WITH buy_totals AS (
  SELECT mint, SUM(COALESCE(qty,0)) AS sol_spent
  FROM trades
  WHERE side='BUY'
  GROUP BY mint
),
targets AS (
  SELECT p.id, p.mint, p.qty_token, bt.sol_spent
  FROM positions p
  JOIN buy_totals bt ON bt.mint = p.mint
  WHERE p.status='OPEN'
    AND COALESCE(p.entry_price,0)=0
    AND COALESCE(p.qty_token,0) > 0
    AND COALESCE(bt.sol_spent,0) > 0
)
UPDATE positions
SET entry_price = (
  SELECT (t.sol_spent / t.qty_token)
  FROM targets t
  WHERE t.id = positions.id
)
WHERE id IN (SELECT id FROM targets);

COMMIT;
SQL

sqlite3 state/trades.sqlite < /tmp/fix_entry_price.sql || true
echo "[RESYNC] done"
