set -euo pipefail
cd ~/lino
mkdir -p state

# pubkey
PUB="$(python - <<'PY'
import os, json
from solders.keypair import Keypair
kp_path=os.getenv("KEYPAIR_PATH","/home/tng25/lino/keypair.json")
kp=Keypair.from_bytes(bytes(json.load(open(kp_path))))
print(str(kp.pubkey()))
PY
)"
export WALLET_PUBKEY="${WALLET_PUBKEY:-$PUB}"
export TRADER_USER_PUBLIC_KEY="${TRADER_USER_PUBLIC_KEY:-$PUB}"
export SELL_OWNER_PUBKEY="${SELL_OWNER_PUBKEY:-$PUB}"

# defaults
export JUP_BASE_URL="${JUP_BASE_URL:-https://lite-api.jup.ag}"
export RPC_HTTP="${RPC_HTTP:-https://api.mainnet-beta.solana.com}"
export TRADER_DRY_RUN="${TRADER_DRY_RUN:-1}"
export ONE_SHOT="${ONE_SHOT:-1}"

echo "[CFG] JUP_BASE_URL=$JUP_BASE_URL"
echo "[CFG] RPC_HTTP=$RPC_HTTP"
echo "[CFG] WALLET=$WALLET_PUBKEY"

# 1) universe from tokenlist
UNIVERSE_TOKENLIST_MAX="${UNIVERSE_TOKENLIST_MAX:-2500}" \
READY_FILE="${READY_FILE:-state/ready_to_trade.jsonl}" \
python scripts/universe_from_tokenlist.py

# 2) enrich + score (DexScreener)
python scripts/enrich_ready.py
python scripts/score_ready_v2.py

# 3) build holdings drop list (token + token2022)
DROP_OUT="state/drop_mints_onchain.txt" python scripts/build_drop_mints_onchain.py >/dev/null

# 4) pick best ready input file
READY_IN=""
for f in \
  state/ready_to_trade_ranked_v4_orca.jsonl \
  state/ready_to_trade_scored.jsonl \
  state/ready_to_trade_scored_v2.jsonl \
  state/ready_to_trade.jsonl
do
  [ -f "$f" ] && READY_IN="$f" && break
done

if [ -z "$READY_IN" ]; then
  echo "[ERR] no ready file found in state/"
  ls -1 state | sed 's/^/  - /'
  exit 2
fi

echo "[OK] READY_IN=$READY_IN"

# 5) filter out current holdings
READY_IN="$READY_IN" READY_OUT="state/ready_universe.filtered.jsonl" DROP_MINTS_FILE="state/drop_mints_onchain.txt" \
python scripts/filter_ready_jsonl.py

echo "[OK] READY_OUT=state/ready_universe.filtered.jsonl"
wc -l "$READY_IN" state/ready_universe.filtered.jsonl || true
head -n 5 state/ready_universe.filtered.jsonl || true

# 6) run trader_exec (uses READY_FILE)
READY_FILE="${READY_FILE:-state/ready_universe.filtered.jsonl}" scripts/run_trader_wallet_ready.sh
