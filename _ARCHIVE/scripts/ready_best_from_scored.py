import os, json, time
from pathlib import Path

INP = os.getenv("READY_SCORED_IN", "state/ready_scored.jsonl")
OUT = os.getenv("READY_BEST_OUT", "state/ready_best.jsonl")

# scoring field name used by brain_export_ready_scored.py
SCORE_KEY = os.getenv("READY_SCORE_KEY", "brain_score_v1")

# keep only candidates with score >= min
MIN_SCORE = float(os.getenv("READY_MIN_SCORE", "0.0"))

# choose from top N (random pick within topN to avoid always same mint)
TOPN = int(os.getenv("READY_TOPN", "5"))
MODE = os.getenv("READY_PICK_MODE", "top1").lower()  # top1 | random_topn

def read_jsonl(p):
    out = []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def main():
    if not Path(INP).exists():
        print(f"[ready_best] missing INP={INP}")
        return 2

    rows = read_jsonl(INP)
    cand = []
    for r in rows:
        mint = r.get("mint")
        if not mint:
            continue
        sc = r.get(SCORE_KEY)
        try:
            sc = float(sc)
        except Exception:
            sc = None
        if sc is None:
            continue
        if sc < MIN_SCORE:
            continue
        cand.append((sc, r))

    if not cand:
        print(f"[ready_best] no candidates (min_score={MIN_SCORE}) INP={INP}")
        # still write empty file so trader_exec doesn't accidentally use old one
        Path(OUT).write_text("", encoding="utf-8")
        return 0

    cand.sort(key=lambda x: x[0], reverse=True)
    top = cand[:max(1, TOPN)]

    if MODE == "random_topn":
        import random
        sc, best = random.choice(top)
        picked = "random_topn"
    else:
        sc, best = top[0]
        picked = "top1"

    # Keep only what trader_exec needs (mint + optional src/ts)
    out_row = {
        "mint": best.get("mint"),
        "src": best.get("src", "ready_scored"),
        "ts": int(time.time()),
        SCORE_KEY: sc,
        "reason": best.get("brain_score_reason") or best.get("brain_score_reason_v1") or best.get("brain_score_reason", ""),
    }

    Path(OUT).write_text(json.dumps(out_row, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[ready_best] picked={picked} mint={out_row['mint']} {SCORE_KEY}={sc:.6g} OUT={OUT} topN={len(top)} min_score={MIN_SCORE}")

    # show small top list
    for i, (s, r) in enumerate(top[:5], 1):
        print(f"  top{i}: {r.get('mint')} score={s:.6g}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
