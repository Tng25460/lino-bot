#!/usr/bin/env python3
from __future__ import annotations
import os, re, sys, runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "src" / "trader_exec_real.py"
LOGDIR = ROOT / "logs"

def _env_int(*names: str, default: int = 0) -> int:
    for n in names:
        v = os.getenv(n)
        if v is None or str(v).strip() == "":
            continue
        try:
            return int(float(str(v).strip()))
        except Exception:
            pass
    return default

def _latest_log() -> Path | None:
    logs = sorted(LOGDIR.glob("run_live_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None

def _sell_engine_open_count() -> tuple[int, str]:
    log = _latest_log()
    if not log:
        return -1, "no_log"

    txt = log.read_text(errors="ignore")
    lines = txt.splitlines()

    last_idx = -1
    last_n = -1
    for i, line in enumerate(lines):
        m = re.search(r"\[DBG\] fetched positions: n=(\d+)", line)
        if m:
            last_idx = i
            last_n = int(m.group(1))

    if last_idx < 0:
        return -1, f"log_without_sell_engine:{log.name}"

    mints = []
    for line in lines[last_idx + 1:last_idx + 60]:
        m = re.search(r"\[DBG\] loop item mint=([A-Za-z0-9]+)\s+qty=([0-9.eE+-]+)", line)
        if m:
            mint = m.group(1)
            if mint not in mints:
                mints.append(mint)
            continue
        if "[DBG]" not in line:
            break

    if last_n >= 0:
        return last_n, log.name
    return len(mints), log.name

def main() -> int:
    max_open = _env_int(
        "TRADER_MAX_OPEN_POSITIONS",
        "MAX_OPEN_POSITIONS",
        "MAX_ACTIVE_POSITIONS",
        default=6,
    )

    sell_count, src = _sell_engine_open_count()

    # GATE ROBUSTE : si sell_engine voit deja max_open positions, on bloque ici.
    if sell_count >= 0:
        if sell_count >= max_open:
            print(
                f"🛑 MAX_OPEN_POSITIONS: {sell_count}/{max_open} active "
                f"[active_file={sell_count}, sell_engine_log={sell_count}, src={src}] "
                f"→ skip BUY (wrapper)",
                flush=True,
            )
            return 0
        else:
            print(
                f"📊 MAX_OPEN_POSITIONS: {sell_count}/{max_open} active "
                f"[active_file={sell_count}, sell_engine_log={sell_count}, src={src}] "
                f"(OK wrapper)",
                flush=True,
            )

    if not REAL.exists():
        print(f"FATAL: missing {REAL}", flush=True)
        return 1

    runpy.run_path(str(REAL), run_name="__main__")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
