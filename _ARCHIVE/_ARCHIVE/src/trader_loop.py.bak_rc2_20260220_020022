import argparse, json
import random
import json
import asyncio
import os
import sys
import time
import subprocess
from pathlib import Path


# --- BUY_429_ADAPTIVE_V1 ---
_BUY429_STATE_PATH = os.getenv("BUY_429_STATE_PATH", "/tmp/lino_buy429_state.json")



def _buy429_state_load():
    """Load adaptive BUY 429 state from JSON file."""
    try:
        import json, os
        path = os.getenv("BUY_429_STATE_PATH", _BUY429_STATE_PATH)
        if not path:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return obj if isinstance(obj, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            return {}
    except Exception:
        return {}

def _buy429_state_save(st: dict):
    """Persist adaptive BUY 429 state to JSON file (atomic write)."""
    try:
        import json, os, tempfile
        path = os.getenv("BUY_429_STATE_PATH", _BUY429_STATE_PATH)
        if not path:
            return
        if not isinstance(st, dict):
            return
        # keep only simple JSON-serializable keys we care about
        keep = ("sleep_s", "cooldown_sec", "breaker_k", "breaker_t0")
        out = {}
        for k in keep:
            try:
                v = st.get(k)
            except Exception:
                v = None
            if v is None:
                continue
            # coerce numeric fields to float/int-safe
            if k in ("sleep_s", "cooldown_sec", "breaker_t0"):
                try:
                    out[k] = float(v)
                except Exception:
                    continue
            elif k == "breaker_k":
                try:
                    out[k] = int(v)
                except Exception:
                    continue
            else:
                out[k] = v

        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)

        fd, tmp = tempfile.mkstemp(prefix=".buy429_", suffix=".json", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass
    except Exception:
        return

def _buy429_load_state():
    # compat wrapper: use unified state loader
    try:
        return _buy429_state_load()
    except Exception:
        return {}

def _buy429_save_state(st: dict):
    # compat wrapper: use unified state saver
    try:
        _buy429_state_save(st)
    except Exception:
        pass

def _buy429_get_sleep():
    st = _buy429_load_state()
    cur = float(st.get("sleep_s", os.getenv("BUY_429_COOLDOWN_SEC", "25")))
    mn = float(os.getenv("BUY_429_MIN_COOLDOWN_SEC", "3"))
    mx = float(os.getenv("BUY_429_MAX_COOLDOWN_SEC", "180"))
    if cur < mn: cur = mn
    if cur > mx: cur = mx
    return cur, mn, mx, st

def _buy429_on_rc42():
    cur, mn, mx, st = _buy429_get_sleep()
    mult = float(os.getenv("BUY_429_BACKOFF_MULT", "1.8"))
    jitter = float(os.getenv("BUY_429_JITTER_FRAC", "0.15"))
    nxt = cur * mult
    # jitter +/- %
    j = 1.0 + (random.random() * 2 - 1) * jitter
    nxt = nxt * j
    if nxt < mn: nxt = mn
    if nxt > mx: nxt = mx
    st["sleep_s"] = round(nxt, 3)
    st["last_rc"] = 42
    st["ts"] = int(time.time())
    _buy429_save_state(st)
    return nxt

def _buy429_on_success():
    cur, mn, mx, st = _buy429_get_sleep()
    decay = float(os.getenv("BUY_429_SUCCESS_DECAY", "0.85"))
    nxt = cur * decay
    if nxt < mn: nxt = mn
    st["sleep_s"] = round(nxt, 3)
    st["last_rc"] = 0
    st["ts"] = int(time.time())
    _buy429_save_state(st)
    return nxt
# --- /BUY_429_ADAPTIVE_V1 ---

def _parse_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sell-json", default=None)
    ap.add_argument("--buy-json", default=None)
    return ap.parse_args()
async def trader_loop():
    sleep_s = float(os.getenv("LOOP_SLEEP_S", os.getenv("SCAN_INTERVAL_SECONDS", "12")))
    max_trades_per_hour = int(os.getenv("LOOP_MAX_TRADES_PER_HOUR", "6"))
    cooldown_s = int(os.getenv("LOOP_COOLDOWN_MINT_S", "1800"))
    one_shot = (os.getenv("TRADER_ONE_SHOT","").strip().lower() in ("1","true","yes","on")) or (os.getenv("ONE_SHOT","").strip().lower() in ("1","true","yes","on"))  # ONE_SHOT_RC2_ONLY_V1

    print("🧠 trader_loop (universe_builder -> exec -> sign -> send)", flush=True)
    print("   sleep_s=", sleep_s, "max_trades/h=", max_trades_per_hour, "cooldown_s=", cooldown_s, flush=True)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH","")

    while True:
        try:
            print(f"TRADER_LOOP_PYTHON={sys.executable}")
            rc = subprocess.run(

                [sys.executable, "-u", "src/trader_exec.py"],

                check=False,

                env=env,

            ).returncode

            print(f"TRADER_EXEC_RC={rc}", flush=True)


            # strict rc: if trader_exec failed, propagate non-zero exit code

            import os as _os

            if str(_os.getenv('STRICT_TRADER_RC','')).strip() in ('1','true','True','yes','YES'):

                if isinstance(rc, int) and rc != 0:

                    raise SystemExit(rc)

            return rc

            # --- BUY_429_ADAPTIVE_HOOK_V1 (after TRADER_EXEC_RC print) ---
            # ensure adaptive state dict is available in both rc==42 and rc==0 branches
            try:
                _st = _buy429_state_load()
            except Exception:
                _st = {}
            if rc == 42:
                # --- BUY_429_BREAKER_V1 ---
                try:
                    _breaker_strikes = int(float(os.getenv('BUY_429_BREAKER_STRIKES', '3')))
                except Exception:
                    _breaker_strikes = 3
                try:
                    _breaker_window = float(os.getenv('BUY_429_BREAKER_WINDOW_SEC', '120'))
                except Exception:
                    _breaker_window = 120.0
                try:
                    _breaker_sleep = float(os.getenv('BUY_429_BREAKER_SLEEP_SEC', '300'))
                except Exception:
                    _breaker_sleep = 300.0
                # update breaker counters
                try:
                    import time as _t
                    now = float(_t.time())
                    t0 = float(_st.get('breaker_t0', 0.0) or 0.0)
                    if (not t0) or (now - t0 > _breaker_window):
                        _st['breaker_t0'] = now
                        _st['breaker_k'] = 0
                    _st['breaker_k'] = int(_st.get('breaker_k', 0) or 0) + 1
                except Exception:
                    pass
                _k = int(_st.get('breaker_k', 0) or 0)
                # adaptive backoff (writes sleep_s)
                _sleep = float(_buy429_on_rc42())
                # breaker trip => override sleep, reset k but keep t0
                if _k >= _breaker_strikes:
                    try:
                        _st['breaker_k'] = 0
                    except Exception:
                        pass
                    try:
                        _buy429_state_save(_st)
                    except Exception:
                        pass
                    print(f"🧱 BUY_429_BREAKER hit k={_k}/{_breaker_strikes} window_s={_breaker_window:.0f} -> sleep_s={_breaker_sleep:.0f}", flush=True)
                    await asyncio.sleep(float(_breaker_sleep))
                else:
                    try:
                        _buy429_state_save(_st)
                    except Exception:
                        pass
                    print(f"⏸️ BUY_429_COOLDOWN(adaptive) sleep_s={_sleep:.3f}", flush=True)
                    await asyncio.sleep(float(_sleep))
            elif rc == 0:
                # decay sleep_s but DO NOT overwrite with stale _st afterwards
                _new = float(_buy429_on_success())
                try:
                    import time as _t
                    now = float(_t.time())
                    _st2 = _buy429_state_load()
                    if not isinstance(_st2, dict):
                        _st2 = {}
                    _st2['sleep_s'] = round(_new, 3)
                    _st2['last_rc'] = 0
                    _st2['ts'] = int(now)
                    _st2['breaker_k'] = 0
                    if 'breaker_t0' not in _st2:
                        _st2['breaker_t0'] = now
                    _buy429_state_save(_st2)
                except Exception:
                    pass
                print(f"✅ BUY_429_COOLDOWN(adaptive) decay_to={_new:.3f}", flush=True)
            # --- /BUY_429_ADAPTIVE_HOOK_V1 ---

            # --- BUY_429_SLEEP_V1 (legacy removed – adaptive hook handles it) ---


            # --- LOW_SOL_COOLDOWN_V1 ---
            try:
                _cool_s = int(float(os.getenv("LOW_SOL_COOLDOWN_SEC", "900")))
            except Exception:
                _cool_s = 900
            try:
                _out = None
                try:
                    _out = locals().get("out_all")
                except Exception:
                    _out = None
                if isinstance(_out, str) and "LOW_SOL_GUARD SKIP" in _out:
                    print(f"⏸️ LOW_SOL_COOLDOWN sleep_s={_cool_s} (LOW_SOL_GUARD)", flush=True)
                    import time as _t
                    _t.sleep(_cool_s)
            except Exception:
                pass
            # --- /LOW_SOL_COOLDOWN_V1 ---
            # RESYNC_BUY_QTY_AFTER_RC2_V1: after BUY sent (rc=2), resync on-chain qty into DB (avoid OPEN qty=0)
            if rc == 2:
                try:
                    subprocess.run([sys.executable, '-u', 'scripts/resync_buy_qty.py'], check=False, env=env)
                except Exception as _e:
                    print('⚠️ RESYNC_BUY_QTY_AFTER_RC2_V1 failed:', _e, flush=True)
            # ONE_SHOT_STOP_AFTER_RC23_V1: stop if trader_exec exited rc=2 (sent) or rc=3 (built tx)
            if one_shot and rc in (2,3):
                print("🛑 ONE_SHOT_STOP_AFTER_RC23_V1 rc=" + str(rc) + " -> stop trader_loop", flush=True)
                return

            # ONE_SHOT_RC2_V1: stop ONLY if trader_exec exited with rc=2 (sent swap)

            if one_shot and int(rc or 0) == 2:

                print("🛑 ONE_SHOT_RC2_V1 rc=2 (sent) -> stop trader_loop", flush=True)

                return


            if one_shot:
                return
        except Exception as e:
            print("❌ trader_loop cannot run trader_exec:", e, flush=True)
        await asyncio.sleep(sleep_s)
def main():
    _env = os.environ.copy()
    if _env.get("ONE_SHOT") in ("1","true","yes","on") and "TRADER_ONE_SHOT" not in _env:
        _env["TRADER_ONE_SHOT"] = "1"
    args = _parse_cli()
    if args.sell_json:
        req = json.loads(args.sell_json)
        if "run_sell" in globals():
            return globals()["run_sell"](req)
        if "handle_sell" in globals():
            return globals()["handle_sell"](req)
        print("[trader_loop] SELL request:", req)
        return 0
    if args.buy_json:
        req = json.loads(args.buy_json)
        if "run_buy" in globals():
            return globals()["run_buy"](req)
        if "handle_buy" in globals():
            return globals()["handle_buy"](req)
        print("[trader_loop] BUY request:", req)
        return 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
