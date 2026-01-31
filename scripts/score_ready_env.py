import os, json, math, argparse, time

def f(x, d=0.0):
    try:
        if x is None: return d
        return float(x)
    except Exception:
        return d

def envf(name, default):
    v = os.environ.get(name)
    if v is None or v == "":
        return float(default)
    return float(v)

def gate(row, cfg):
    liq = f(row.get("liquidity_usd") or row.get("liquidity"))
    v24 = f(row.get("vol_24h") or row.get("volume24h"))
    v5  = f(row.get("vol_5m") or row.get("volume5m"))
    tx5 = f(row.get("txns_5m") or row.get("tx5m"))
    tx1 = f(row.get("txns_1h") or row.get("tx1h"))
    ch5 = f(row.get("chg_5m"))
    ch1 = f(row.get("chg_1h"))
    fdv = f(row.get("fdv"))
    mcap = f(row.get("market_cap") or row.get("mcap"))

    if liq < cfg["MIN_LIQ"]: return False, "min_liq"
    if v24 < cfg["MIN_VOL24"]: return False, "min_vol24"
    if v5  < cfg["MIN_VOL5M"]: return False, "min_vol5m"
    if tx5 < cfg["MIN_TX5M"]: return False, "min_tx5m"
    if tx1 < cfg["MIN_TX1H"]: return False, "min_tx1h"
    if ch1 < cfg["MIN_CHG1H"]: return False, "min_chg1h"
    if ch5 < cfg["MIN_CHG5M"]: return False, "min_chg5m"
    if cfg["MAX_FDV"] > 0 and fdv > cfg["MAX_FDV"]: return False, "max_fdv"
    if cfg["MAX_MCAP"] > 0 and mcap > cfg["MAX_MCAP"]: return False, "max_mcap"
    return True, "ok"

def score(row):
    liq = f(row.get("liquidity_usd") or row.get("liquidity"))
    v24 = f(row.get("vol_24h") or row.get("volume24h"))
    v5  = f(row.get("vol_5m") or row.get("volume5m"))
    tx5 = f(row.get("txns_5m") or row.get("tx5m"))
    ch5 = f(row.get("chg_5m"))
    ch1 = f(row.get("chg_1h"))
    fdv = f(row.get("fdv"))
    mcap = f(row.get("market_cap") or row.get("mcap"))

    # score stable (0..1.2 environ)
    s_liq = min(1.0, math.log10(max(liq, 1.0)) / 6.0)          # 0..~1
    s_v5  = min(1.0, math.log10(max(v5,  1.0)) / 5.0)
    s_tx  = min(1.0, math.log10(max(tx5, 1.0)) / 2.2)
    s_ch  = max(-0.5, min(1.0, (ch5/20.0) + (ch1/40.0)))       # pump favor, clamp

    # pénalité FDV/MCAP (optionnel)
    pen = 0.0
    if fdv > 0:
        pen += min(0.4, math.log10(fdv) / 20.0)
    if mcap > 0:
        pen += min(0.4, math.log10(mcap) / 20.0)

    sc = (0.35*s_liq + 0.35*s_v5 + 0.2*s_tx + 0.25*s_ch) - pen
    return max(-1.0, min(2.0, sc))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="ready_to_trade_enriched.jsonl")
    ap.add_argument("--out", dest="out", default="ready_to_trade_scored.jsonl")
    args = ap.parse_args()

    cfg = dict(
        MIN_LIQ    = envf("SCORE_MIN_LIQ", 12000),
        MIN_VOL24  = envf("SCORE_MIN_VOL24", 15000),
        MIN_VOL5M  = envf("SCORE_MIN_VOL5M", 600),
        MIN_TX5M   = envf("SCORE_MIN_TX5M", 1),
        MIN_TX1H   = envf("SCORE_MIN_TX1H", 10),
        MIN_CHG5M  = envf("SCORE_MIN_CHG5M", -5.0),
        MIN_CHG1H  = envf("SCORE_MIN_CHG1H", -10.0),
        MAX_FDV    = envf("SCORE_MAX_FDV",  60000000),
        MAX_MCAP   = envf("SCORE_MAX_MCAP", 40000000),
        SCORE_MIN  = envf("SCORE_MIN", 2.0),
        TOP_N      = int(envf("SCORE_TOP_N", 200)),
    )

    total = kept = 0
    reasons = {}

    out_rows = []
    with open(args.inp, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            total += 1
            row = json.loads(line)

            ok, reason = gate(row, cfg)
            reasons[reason] = reasons.get(reason, 0) + 1
            if not ok:
                continue

            sc = score(row)
            row["score_env"] = sc
            row["score_v4"] = sc  # compatible trader_exec pick_best_candidate
            row["score_reason"] = "ok_env"
            out_rows.append(row)

    # sort + top N
    out_rows.sort(key=lambda r: float(r.get("score_env", -999)), reverse=True)
    out_rows = out_rows[: cfg["TOP_N"]]

    with open(args.out, "w", encoding="utf-8") as w:
        for row in out_rows:
            kept += 1
            w.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"scored_env: kept={kept} total={total} out={args.out}")
    # print top reasons
    for k in sorted(reasons, key=lambda x: (-reasons[x], x))[:12]:
        print(f"reason {k}: {reasons[k]}")

if __name__ == "__main__":
    main()
