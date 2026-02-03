#!/usr/bin/env bash
set +e
cd ~/lino || exit 1
mkdir -p state scripts

echo "[CFG] JUP_BASE_URL=${JUP_BASE_URL:-https://lite-api.jup.ag}"
echo "[CFG] RPC_HTTP=${RPC_HTTP:-https://api.mainnet-beta.solana.com}"
echo "[CFG] DRY_RUN=${TRADER_DRY_RUN:-1} ONE_SHOT=${ONE_SHOT:-1}"
echo

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
export RPC_HTTP="${RPC_HTTP:-https://api.mainnet-beta.solana.com}"

echo "[STEP] tokenlist -> state/ready_from_tokenlist.jsonl"
UNIVERSE_TOKENLIST_MAX="${UNIVERSE_TOKENLIST_MAX:-1200}" \
UNIVERSE_OUT="state/ready_from_tokenlist.jsonl" \
python -u scripts/universe_from_tokenlist.py
head -n 200 state/ready_from_tokenlist.jsonl > state/ready_from_tokenlist_200.jsonl

echo
echo "[STEP] pre-filter base/stables on tokenlist (before enrich)"
INP="state/ready_from_tokenlist_200.jsonl" OUT="state/ready_from_tokenlist_200.nobase.jsonl" \
python -u scripts/filter_exclude_mints.py || true
wc -l state/ready_from_tokenlist_200.jsonl state/ready_from_tokenlist_200.nobase.jsonl 2>/dev/null || true


echo
echo "[OK] tokenlist counts:"
wc -l state/ready_from_tokenlist.jsonl state/ready_from_tokenlist_200.jsonl

echo
echo "[STEP] enrich_ready (200)"
rm -f state/ready_enriched.jsonl
READY_IN="state/ready_from_tokenlist_200.nobase.jsonl" READY_OUT="state/ready_enriched.jsonl" \
python -u scripts/enrich_ready.py
echo "[OK] enriched lines:"
wc -l state/ready_enriched.jsonl

echo
echo "[STEP] filter ds_ok"
ENRICH_IN="state/ready_enriched.jsonl" ENRICH_OUT="state/ready_enriched.dsok.jsonl" \
python -u scripts/filter_ds_ok.py
wc -l state/ready_enriched.dsok.jsonl || true

echo
echo "[STEP] score (workaround hardcoded filenames)"
cp -f state/ready_enriched.dsok.jsonl ready_to_trade_enriched.jsonl
python -u scripts/score_ready_v2.py
mv -f ready_to_trade_scored.jsonl state/ready_ranked.jsonl
wc -l state/ready_ranked.jsonl

echo
echo "[STEP] sort by score_used desc -> state/ready_ranked.sorted.jsonl"
python - <<'PY'
import json
inp="state/ready_ranked.jsonl"
out="state/ready_ranked.sorted.jsonl"
rows=[]
for line in open(inp,"r",encoding="utf-8"):
    line=line.strip()
    if not line: continue
    try: j=json.loads(line)
    except: continue
    rows.append(j)
rows.sort(key=lambda x: float(x.get("score_used",0.0)), reverse=True)
with open(out,"w",encoding="utf-8") as f:
    for j in rows:
        f.write(json.dumps(j,separators=(",",":"))+"\n")
print("[OK] wrote",len(rows),"->",out," top_score=", (rows[0].get("score_used") if rows else None))
PY

echo
echo "[STEP] drop holdings onchain + filter"
RPC_HTTP="$RPC_HTTP" WALLET_PUBKEY="$WALLET_PUBKEY" DROP_OUT="state/drop_mints_onchain.txt" \
python -u scripts/build_drop_mints_onchain.py >/dev/null

READY_IN="state/ready_ranked.sorted.jsonl" \
READY_OUT="state/ready_final.jsonl" \
DROP_MINTS_FILE="state/drop_mints_onchain.txt" \
python -u scripts/filter_ready_jsonl.py

echo "[OK] final counts:"
wc -l state/ready_ranked.sorted.jsonl state/ready_final.jsonl || true
head -n 3 state/ready_final.jsonl 2>/dev/null || true


echo
echo "[STEP] exclude base/stables -> state/ready_final.nobase.jsonl"
INP="state/ready_final.jsonl" OUT="state/ready_final.nobase.jsonl" \
python -u scripts/filter_exclude_mints.py || true
echo "[OK] nobase counts:"
wc -l state/ready_final.jsonl state/ready_final.nobase.jsonl 2>/dev/null || true

echo

echo
echo "[STEP] cap mcap/fdv -> state/ready_final.capped.jsonl"
INP="state/ready_final.nobase.jsonl" OUT="state/ready_final.capped.jsonl" \
MAX_MCAP="${MAX_MCAP:-2000000}" MAX_FDV="${MAX_FDV:-5000000}" \
python -u scripts/filter_cap_mcap.py || true
echo "[OK] capped counts:"
wc -l state/ready_final.nobase.jsonl state/ready_final.capped.jsonl 2>/dev/null || true

echo
echo "[STEP] brain_score -> state/ready_brain.jsonl"
INP="state/ready_final.capped.jsonl" OUT="state/ready_brain.jsonl" \
python -u src/brain/score_ready_brain.py || true
echo "[OK] brain counts:"
wc -l state/ready_final.capped.jsonl state/ready_brain.jsonl 2>/dev/null || true

# choose READY_FILE: brain if non-empty, else capped, else nobase
READY_FILE="state/ready_brain.jsonl"
if [ ! -s "$READY_FILE" ]; then
  echo "[WARN] brain empty -> fallback to state/ready_final.capped.jsonl"
  READY_FILE="state/ready_final.capped.jsonl"
fi
if [ ! -s "$READY_FILE" ]; then
  echo "[WARN] capped empty -> fallback to state/ready_final.nobase.jsonl"
  READY_FILE="state/ready_final.nobase.jsonl"
fi


# choose READY_FILE: capped if non-empty, else nobase
READY_FILE="state/ready_final.capped.jsonl"
if [ ! -s "$READY_FILE" ]; then
  echo "[WARN] capped empty -> fallback to state/ready_final.nobase.jsonl"
  READY_FILE="state/ready_final.nobase.jsonl"
fi

echo "[STEP] trader_exec (uses $READY_FILE)"
TRADER_DRY_RUN="${TRADER_DRY_RUN:-1}" ONE_SHOT="${ONE_SHOT:-1}" \
scripts/run_trader_wallet_ready_autoskip.sh "$READY_FILE"
echo
echo "[DONE] pipeline finished (terminal stays open)."
