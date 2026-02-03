#!/usr/bin/env bash
set +e  # IMPORTANT: ne ferme pas le terminal si une commande échoue
cd ~/lino || exit 1
mkdir -p state

LOG="state/universe_pipe_$(date +%Y%m%d_%H%M%S).log"
echo "[RUN] log=$LOG"
echo "[RUN] start $(date)" > "$LOG"

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
export RPC_HTTP="${RPC_HTTP:-https://api.mainnet-beta.solana.com}"
export JUP_BASE_URL="${JUP_BASE_URL:-https://lite-api.jup.ag}"
export TRADER_DRY_RUN="${TRADER_DRY_RUN:-1}"
export ONE_SHOT="${ONE_SHOT:-1}"
export UNIVERSE_TOKENLIST_MAX="${UNIVERSE_TOKENLIST_MAX:-1200}"

echo "[CFG] JUP_BASE_URL=$JUP_BASE_URL" >> "$LOG"
echo "[CFG] RPC_HTTP=$RPC_HTTP" >> "$LOG"
echo "[CFG] WALLET=$WALLET_PUBKEY" >> "$LOG"
echo "[CFG] DRY_RUN=$TRADER_DRY_RUN ONE_SHOT=$ONE_SHOT" >> "$LOG"
echo "[CFG] UNIVERSE_TOKENLIST_MAX=$UNIVERSE_TOKENLIST_MAX" >> "$LOG"
echo "" >> "$LOG"

# Step 1: holdings drop list (Token + Token2022)
echo "[STEP] build_drop_mints_onchain" >> "$LOG"
DROP_OUT="state/drop_mints_onchain.txt" RPC_HTTP="$RPC_HTTP" WALLET_PUBKEY="$WALLET_PUBKEY" \
  python -u scripts/build_drop_mints_onchain.py >> "$LOG" 2>&1
echo "[RC] build_drop_mints_onchain=$?" >> "$LOG"
echo "" >> "$LOG"

# Step 2: universe from tokenlist (fallback multi-url)
echo "[STEP] universe_from_tokenlist" >> "$LOG"
UNIVERSE_OUT="state/ready_from_tokenlist.jsonl" UNIVERSE_TOKENLIST_MAX="$UNIVERSE_TOKENLIST_MAX" \
  python -u scripts/universe_from_tokenlist.py >> "$LOG" 2>&1
echo "[RC] universe_from_tokenlist=$?" >> "$LOG"
echo "" >> "$LOG"

# Step 3: enrich (DexScreener)
echo "[STEP] enrich_ready" >> "$LOG"
READY_IN="state/ready_from_tokenlist.jsonl" READY_OUT="state/ready_enriched.jsonl" \
  python -u scripts/enrich_ready.py >> "$LOG" 2>&1
echo "[RC] enrich_ready=$?" >> "$LOG"
echo "" >> "$LOG"

# Step 4: score
echo "[STEP] score_ready_v2" >> "$LOG"
READY_IN="state/ready_enriched.jsonl" READY_OUT="state/ready_scored.jsonl" \
  python -u scripts/score_ready_v2.py >> "$LOG" 2>&1
echo "[RC] score_ready_v2=$?" >> "$LOG"
echo "" >> "$LOG"

# Step 5: filter holdings out
echo "[STEP] filter_ready_jsonl (drop holdings)" >> "$LOG"
READY_IN="state/ready_scored.jsonl" READY_OUT="state/ready_scored.filtered.jsonl" DROP_MINTS_FILE="state/drop_mints_onchain.txt" \
  python -u scripts/filter_ready_jsonl.py >> "$LOG" 2>&1
echo "[RC] filter_ready_jsonl=$?" >> "$LOG"
echo "" >> "$LOG"

# Step 6: trader_exec (uses filtered)
echo "[STEP] trader_exec" >> "$LOG"
READY_FILE="state/ready_scored.filtered.jsonl" \
WALLET_PUBKEY="$WALLET_PUBKEY" TRADER_USER_PUBLIC_KEY="$WALLET_PUBKEY" SELL_OWNER_PUBKEY="$WALLET_PUBKEY" \
JUP_BASE_URL="$JUP_BASE_URL" RPC_HTTP="$RPC_HTTP" \
TRADER_DRY_RUN="$TRADER_DRY_RUN" ONE_SHOT="$ONE_SHOT" \
python -u src/trader_exec.py >> "$LOG" 2>&1
echo "[RC] trader_exec=$?" >> "$LOG"
echo "" >> "$LOG"

echo "[DONE] $(date)" >> "$LOG"
echo "[OK] finished (even if errors)."
echo "[TIP] tail -n 220 $LOG"
