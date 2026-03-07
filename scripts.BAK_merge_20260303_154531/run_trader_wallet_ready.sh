
# READY_FILE priority: argv($1) > env(READY_FILE) > default
READY_FILE="${1:-${READY_FILE:-state/ready_wallet_scored.jsonl}}"
export READY_FILE
echo "[RUN] READY_FILE=$READY_FILE"
set -euo pipefail

cd ~/lino
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

# safe defaults
export TRADER_DRY_RUN="${TRADER_DRY_RUN:-1}"
export ONE_SHOT="${ONE_SHOT:-1}"

echo "[RUN] WALLET_PUBKEY=$WALLET_PUBKEY"
echo "[RUN] TRADER_DRY_RUN=$TRADER_DRY_RUN ONE_SHOT=$ONE_SHOT"

PYTHONUNBUFFERED=1 python -u src/trader_exec.py
