#!/usr/bin/env bash

# --- COMBINED_INPUTS_V1 ---
READY_PUMP_FILE="${READY_PUMP_FILE:-state/ready_pump_only.jsonl}"
READY_SAFE_FILE="${READY_SAFE_FILE:-state/ready_safe_tradable.jsonl}"
READY_COMBINED_FILE="${READY_COMBINED_FILE:-state/ready_combined.jsonl}"
# --- /COMBINED_INPUTS_V1 ---
set -u

cd /home/tng25/lino_FINAL_20260203_182626
source .venv/bin/activate

# --- build combined ready (PUMP first + SAFE second, dedup) ---
export READY_PUMP_FILE READY_SAFE_FILE READY_COMBINED_FILE
python - <<'PY'
import json
from pathlib import Path
import os

pump = Path(os.getenv("READY_PUMP_FILE","state/ready_pump_only.jsonl"))
safe = Path(os.getenv("READY_SAFE_FILE","state/ready_safe_tradable.jsonl"))
out  = Path(os.getenv("READY_COMBINED_FILE","state/ready_combined.jsonl"))

def load_jsonl(p):
    rows=[]
    if not p.exists():
        return rows
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln=ln.strip()
        if not ln: 
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass
    return rows

pump_rows = load_jsonl(pump)
safe_rows = load_jsonl(safe)

seen=set()
merged=[]

def get_mint(o):
    for k in ("mint","outputMint","output_mint","outputMint","tokenMint"):
        v=o.get(k)
        if isinstance(v,str) and v:
            return v
    return None

for o in pump_rows:
    m=get_mint(o)
    if not m or m in seen: 
        continue
    seen.add(m)
    o.setdefault("profile","PUMP")
    merged.append(o)

for o in safe_rows:
    m=get_mint(o)
    if not m or m in seen: 
        continue
    seen.add(m)
    o.setdefault("profile","SAFE")
    merged.append(o)

out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in merged) + ("\n" if merged else ""), encoding="utf-8")
print(f"[READY] pump_in={len(pump_rows)} safe_in={len(safe_rows)} merged_out={len(merged)} file={out}")
PY

# --- core env ---
export MODE=FULL
if [ -n "${READY_FILE:-}" ] && [ -s "${READY_FILE}" ]; then
  echo "[READY] external READY_FILE=${READY_FILE}"
else
  if [ -n "${READY_FILE:-}" ] && [ -s "${READY_FILE}" ]; then
  echo "[READY] external READY_FILE=${READY_FILE}"
else
  export READY_FILE="${READY_COMBINED_FILE}"
fi
fi

# IMPORTANT: union labels (PUMP+SAFE)
export STRICT_ONLY="${STRICT_ONLY:-1}"
export ROUTE_GATE_MODE="${ROUTE_GATE_MODE:-all}"
export ALLOWED_ROUTE_LABELS="${ALLOWED_ROUTE_LABELS:-meteora,dlmm,raydium,cp,orca,whirlpool,clmm,amm}"
export DENY_ROUTE_LABELS="${DENY_ROUTE_LABELS:-}"

# wallet pubkey auto if missing (needs solana-cli)
if [ -z "${WALLET_PUBKEY:-}" ] && [ -z "${TRADER_USER_PUBLIC_KEY:-}" ]; then
  if command -v solana >/dev/null 2>&1 && [ -f "keypair.json" ]; then
    PK="$(solana address -k keypair.json 2>/dev/null || true)"
    if [ -n "$PK" ]; then
      export WALLET_PUBKEY="$PK"
      export TRADER_USER_PUBLIC_KEY="$PK"
      echo "[WALLET] WALLET_PUBKEY=$PK"
    fi
  fi
fi

# logs
TS="$(date +%Y%m%d_%H%M%S)"
export RUNLIVE_LOG="state/run_live_COMBINED_${TS}.log"
export BRAIN_LOG="state/brain_COMBINED_${TS}.log"

echo "🚀 COMBINED: brain + run_live"
echo "   READY_FILE=$READY_FILE"
echo "   STRICT_ONLY=$STRICT_ONLY ROUTE_GATE_MODE=$ROUTE_GATE_MODE"
echo "   ALLOWED_ROUTE_LABELS=$ALLOWED_ROUTE_LABELS"
echo "   RUNLIVE_LOG=$RUNLIVE_LOG"
echo "   BRAIN_LOG=$BRAIN_LOG"

# brain in background (soft loop)
bash scripts/run_brain_soft.sh 2>&1 | tee "$BRAIN_LOG" &
BRAIN_PID=$!

# run_live in foreground
python -u src/run_live.py 2>&1 | tee "$RUNLIVE_LOG"

# if run_live exits, stop brain
kill "$BRAIN_PID" 2>/dev/null || true
wait "$BRAIN_PID" 2>/dev/null || true
