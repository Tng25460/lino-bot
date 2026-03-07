import os, json, sqlite3, time

DB  = os.getenv("BRAIN_DB", "state/brain.sqlite")
INP = os.getenv("READY_FILE", "state/ready_tradable.jsonl")
OUT = os.getenv("READY_SCORED_OUT", "state/ready_scored.jsonl")
MIN_SCORE = float(os.getenv("READY_MIN_SCORE", "-999"))

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

scores = {r["mint"]: r for r in con.execute("SELECT mint, score, ts, reason FROM token_scores_v1").fetchall()}

items = []
with open(INP, "r", errors="ignore") as f:
    for line in f:
        line=line.strip()
        if not line: 
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        mint = o.get("mint") or o.get("output_mint") or o.get("address")
        if not mint:
            continue
        s = scores.get(mint)
        sc = float(s["score"]) if s else -1e9
        if sc < MIN_SCORE:
            continue
        o["brain_score_v1"] = sc
        if s:
            o["brain_score_ts"] = int(s["ts"])
            o["brain_score_reason"] = s["reason"]
        items.append(o)

items.sort(key=lambda x: x.get("brain_score_v1",-1e9), reverse=True)

with open(OUT, "w") as w:
    for o in items:
        w.write(json.dumps(o, separators=(",",":"))+"\n")

print(f"[export] IN={INP} OUT={OUT} kept={len(items)} scores={len(scores)}")
if items:
    print("[export] top5:")
    for o in items[:5]:
        print(" ", o.get("mint"), o.get("brain_score_v1"))
