import os
import sys
import time as _time
import subprocess
import traceback
import time
import re

def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v == "":
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)

def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v == "":
        return int(default)
    try:
        return int(float(v))
    except Exception:
        return int(default)


class SellEngine:
    """
    Sell engine autonome (compatible DB actuelle):
    - lit qty_token (fallback qty)
    - exécute src/sell_exec_wrap.py (Jupiter)
    - TP1 / TP2 partiels + hard SL + time stop + trailing
    """

    def __init__(self, db, price_feed, trader=None):
        self._mint_cooldowns = {}  # mint -> unix_ts until when sells are paused
        try:
            import os
            self.SELL_COOLDOWN_JUP_CUSTOM_SEC = int(os.getenv('SELL_COOLDOWN_JUP_CUSTOM_SEC','21600'))
        except Exception:
            self.SELL_COOLDOWN_JUP_CUSTOM_SEC = 21600
        self.db = db
        self.price_feed = price_feed
        self.trader = trader  # ignored (compat)

        # Fractions (0.01 = 1%)
        self.TP1_PCT = float(os.getenv("SELL_TP1_PCT", "0.30"))
        self.TP1_SIZE = float(os.getenv("SELL_TP1_SIZE", "0.35"))
        self.TP2_PCT = float(os.getenv("SELL_TP2_PCT", "0.80"))
        self.TP2_SIZE = float(os.getenv("SELL_TP2_SIZE", "0.35"))

        self.HARD_SL_PCT = -abs(_env_float('HARD_SL_PCT', _env_float('SELL_HARD_SL_PCT', 0.25)))
        self.TRAIL_TIGHT = float(os.getenv("SELL_TRAIL_TIGHT", "0.10"))
        self.TRAIL_WIDE  = float(os.getenv("SELL_TRAIL_WIDE",  "0.20"))

        self.TIME_STOP_SEC = int(os.getenv("SELL_TIME_STOP_SEC", "900"))
        self.TIME_STOP_MIN_PNL = float(os.getenv("SELL_TIME_STOP_MIN_PNL", "0.05"))

        # 429 rate-limit handling (Jupiter lite-api)
        self.SELL_429_COOLDOWN_SEC = int(os.getenv("SELL_429_COOLDOWN_SEC", "90"))
        self.SELL_ROUTE_FAIL_COOLDOWN_SEC = int(os.getenv("SELL_ROUTE_FAIL_COOLDOWN_SEC", "2700"))  # 45min
        self._mint_sell_cooldown_until = {}
        self.SELL_429_MAX_RETRY = int(os.getenv("SELL_429_MAX_RETRY", "2"))
        self.SELL_429_BACKOFF_SEC = int(os.getenv("SELL_429_BACKOFF_SEC", "20"))
        self._cfg_logged = False
        self._blocked_until = {}  # mint -> ts until which we skip (e.g. no SOL)

    def _ui_qty(self, pos) -> float:
        try:
            return float(pos.get("qty_token") or pos.get("qty") or 0.0)
        except Exception:
            return 0.0

    def _entry(self, pos) -> float:
        try:
            return float(pos.get("entry_price") or pos.get("entry_price_usd") or 0.0)
        except Exception:
            return 0.0
    def _onchain_ui_balance_simple(self, mint: str) -> float:
        import os, json, requests
        pub = os.getenv("WALLET_PUBKEY", "").strip()
        if not pub:
            # fallback: try to read pubkey from keypair
            try:
                from solders.keypair import Keypair
                import json as _json
                kp_path = os.getenv("KEYPAIR_PATH", os.getenv("KEYPATH", "/home/tng25/lino/keypair.json"))
                kp = Keypair.from_bytes(bytes(_json.load(open(kp_path))))
                pub = str(kp.pubkey())
            except Exception:
                return 0.0
        rpc = os.getenv("SOLANA_RPC_URL", os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com"))
        payload = {
            "jsonrpc":"2.0","id":1,"method":"getTokenAccountsByOwner",
            "params":[pub, {"mint": mint}, {"encoding":"jsonParsed"}]
        }
        r = requests.post(rpc, json=payload, timeout=20)
        r.raise_for_status()
        j = r.json()
        vals = (j.get("result",{}) or {}).get("value",[]) or []
        tot = 0.0
        for it in vals:
            try:
                ta = it["account"]["data"]["parsed"]["info"]["tokenAmount"]
                tot += float(ta.get("uiAmount") or 0.0)
            except Exception:
                pass
        return float(tot)

    def _clamp_sell_ui(self, mint: str, ui_db: float) -> float:
        """
        Clamp sell ui to on-chain (prevents oversell -> Jupiter simulation 0x1788).
        """
        try:
            ui_on = float(self._onchain_ui_balance_simple(mint) or 0.0)
        except Exception:
            ui_on = 0.0

        if ui_on > 0:
            ui = min(float(ui_db or 0.0), ui_on)
            # safety epsilon (avoid exact dust/rounding)
            ui = ui * 0.995
            if ui < 0: ui = 0.0
            if ui != float(ui_db or 0.0):
                print(f"🧩 CLAMP_SELL_UI mint={mint} db={ui_db} onchain={ui_on} -> {ui}", flush=True)
            return ui

        return float(ui_db or 0.0)


    def _sell_exec(self, mint: str, ui_amount: float, reason: str) -> str:
        """Run src/sell_exec_wrap.py and return a marker or txsig."""

        # throttle swaps (best-effort)
        try:
            now = time.time()
            last = float(getattr(self, "_last_swap_ts", 0.0) or 0.0)
            min_iv = float(getattr(self, "SELL_SWAP_MIN_INTERVAL_SEC", 0) or 0)
            if min_iv > 0 and now - last < min_iv:
                time.sleep(max(0.0, min_iv - (now - last)))
            self._last_swap_ts = time.time()
        except Exception:
            pass

        cmd = [sys.executable, "-u", "src/sell_exec_wrap.py",
               "--mint", mint,
               "--ui", str(ui_amount),
               "--reason", reason]
        print(f"🧾 SELL cmd={' '.join(cmd)}", flush=True)

        timeout_s = int(getattr(self, "SELL_EXEC_TIMEOUT_SEC", 180) or 180)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return "__FAIL__"
        except Exception:
            return "__FAIL__"

        out = (proc.stdout or "")
        err = (proc.stderr or "")
        out_all = (out + "\n" + err).strip()
        lo = out_all.lower()
        rc = int(getattr(proc, "returncode", 0) or 0)

        # rc priority from sell_exec_wrap.py
        if rc in (42, 43, 44):
            return "__ROUTE_FAIL__"

        # marker priority
        if "route_fail_0x1788" in lo or "route_fail" in lo:
            return "__ROUTE_FAIL__"
        if "http=429" in lo or " 429 " in lo or "too many requests" in lo:
            return "__429__"
        if "jup_insufficient_funds" in lo or "insufficient_funds" in lo or "insufficient funds" in lo:
            return "__INSUF__"
        if "__dust__" in lo or "dust_untradeable" in lo or ("bad request" in lo and "amount=1" in lo):
            return "__DUST__"

        # extract txsig
        mm = re.search(r'\btxsig=([1-9A-HJ-NP-Za-km-z]{40,})\b', out_all)
        if mm:
            return mm.group(1)
        mm = re.search(r'\b(?:signature|sig)=([1-9A-HJ-NP-Za-km-z]{40,})\b', out_all)
        if mm:
            return mm.group(1)

        return "__FAIL__"
    def run_once(self):
        only_mint = (os.getenv("SELL_ONLY_MINT", "") or "").strip()
        if only_mint:
            print("🧪 SELL_ONLY_MINT=", only_mint, flush=True)

        # log SELL_* once
        if not self._cfg_logged:
            self._cfg_logged = True
            keys = sorted([k for k in os.environ.keys() if k.startswith("SELL_")])
            snap = {k: os.getenv(k) for k in keys}
            print("🧾 SELL_ENGINE_CFG " + " ".join([k + "=" + str(snap.get(k)) for k in keys]), flush=True)
            want = ("hard", "sl", "tp", "trail", "time_stop")
            for name in sorted(dir(self)):
                ln = name.lower()
                if any(w in ln for w in want):
                    try:
                        v = getattr(self, name)
                        if isinstance(v, (int, float, str, bool)):
                            print("🧾 SELL_ENGINE_ATTR " + name + "=" + str(v), flush=True)
                    except Exception:
                        pass

        now = _time.time()
        positions = self.db.get_open_positions() or []
        print(f"💰 sell_engine: open_positions={len(positions)}", flush=True)

        for pos in positions:
            mint = str(pos.get("mint") or "")
            if not mint:
                continue
            if only_mint and mint != only_mint:
                continue
            # cooldown if last attempt failed due to missing SOL fees/rent
            bu = float(self._blocked_until.get(mint, 0) or 0)
            if bu and _time.time() < bu:
                print(f"⏳ SKIP mint={mint} reason=insufficient_funds cooldown_left={int(bu-_time.time())}s", flush=True)
                continue
            try:
                self._handle_one(pos, now)
            except Exception as e:
                print(f"❌ sell_engine error mint={mint}: {e}", flush=True)
                print(traceback.format_exc(), flush=True)

    def _handle_one(self, pos, now: float):
        # MINT_COOLDOWN_SKIP
        mint = pos.get('mint') if isinstance(pos, dict) else getattr(pos, 'mint', None)
        # SELL_COOLDOWN_GUARD
        try:
            now = float(__import__("time").time())
            until = float(getattr(self, "_mint_sell_cooldown_until", {}).get(mint, 0.0) or 0.0)
            if until and now < until:
                left = int(until - now)
                print(f"⏳ SELL mint cooldown active left={left}s mint={mint}", flush=True)
                return
        except Exception:
            pass
        if mint and hasattr(self, '_mint_cooldowns'):
            until = self._mint_cooldowns.get(mint, 0)
            if until and now < until:
                print(f"⏸️ SELL_COOLDOWN skip mint={mint} for {int(until-now)}s")
                return
        mint = str(pos.get("mint") or "")
        entry = self._entry(pos)
        qty_total = self._ui_qty(pos)
        entry_ts = float(pos.get("entry_ts") or pos.get("opened_ts") or 0.0)

        price = float(self.price_feed.get_price(mint) or 0.0)
        if price <= 0:
            return

        if entry <= 0:
            entry = price
            try:
                self.db.update_position(mint, entry_price=entry, entry_price_usd=entry)
            except Exception:
                pass
            pos["entry_price"] = entry
            print(f"🧩 BOOTSTRAP_ENTRY_FROM_PRICE mint={mint} entry={entry}", flush=True)

        pnl = (price - entry) / entry

        # high water
        hw = float(pos.get("high_water") or pos.get("highest_price") or entry)
        if price > hw:
            hw = price
            try:
                self.db.update_position(mint, high_water=hw, highest_price=hw)
            except Exception:
                pass

        tp1 = bool(pos.get("tp1_done"))
        tp2 = bool(pos.get("tp2_done"))

        print(
            "📈 PRICE mint=%s entry=%s price=%s pnl=%.2f%% tp1=%s tp2=%s hw=%s"
            % (mint, entry, price, pnl * 100.0, int(tp1), int(tp2), hw),
            flush=True,
        )

        # HARD SL (sell ALL)
        if pnl <= self.HARD_SL_PCT:
            print(f"🔴 HARD_SL mint={mint} pnl={pnl:.2%}", flush=True)
            if os.getenv("SELL_DRY_RUN", "0") == "1":
                print("🧪 SELL_DRY_RUN=1 -> skip HARD_SL sell", flush=True)
                return
            sell_qty = qty_total
            txsig = self._sell_exec(mint, sell_qty, "hard_sl")
            # markers from _sell_exec / sell_exec_wrap.py
            if txsig == "__429__":
                print(f"[SELL] global cooldown {int(self.SELL_429_COOLDOWN_SEC)}s reason=429", flush=True)
                try:
                    self._global_block_until = float(time.time()) + float(self.SELL_429_COOLDOWN_SEC)
                except Exception:
                    pass
                return
            if txsig == "__INSUF__":
                print(f"[SELL] global cooldown {int(self.SELL_429_COOLDOWN_SEC)}s reason=insufficient_funds", flush=True)
                try:
                    self._global_block_until = float(time.time()) + float(self.SELL_429_COOLDOWN_SEC)
                except Exception:
                    pass
                return
            if txsig == "__ROUTE_FAIL__":
                print(f"[SELL] route_fail -> mint cooldown {int(self.SELL_ROUTE_FAIL_COOLDOWN_SEC)}s mint={mint}", flush=True)
                try:
                    if hasattr(self, "_rl_skip_add"):
                        self._rl_skip_add(mint, int(self.SELL_ROUTE_FAIL_COOLDOWN_SEC), reason="sell_route_fail")
                    elif hasattr(self, "_mint_sell_cooldown_until"):
                        self._mint_sell_cooldown_until[mint] = float(time.time()) + float(self.SELL_ROUTE_FAIL_COOLDOWN_SEC)
                except Exception:
                    pass
                return
            if txsig == "__DUST__":
                print(f"[SELL] dust_untradeable -> close in DB mint={mint}", flush=True)
                try:
                    self.db.close_position(mint, close_reason="dust_untradeable")
                except Exception:
                    try:
                        self.db.close_position(mint, reason="dust_untradeable")
                    except Exception:
                        pass
                return
            if txsig == '__DUST__':
                # mark closed in DB and continue
                try:
                    self.db.close_position(mint, now, 'dust_untradeable', 0.0)
                except Exception as e:
                    print(f"❌ close dust failed mint={mint} err={e}")
                return
            if _sell_cooldown_active():
                try:
                    print("[SELL] cooldown active after sell attempt -> stop run_once", flush=True)
                except Exception:
                    pass
                return

            if not txsig:
                return
            print(f"✅ SOLD HARD_SL txsig={txsig}", flush=True)
            try:
                self.db.close_position(mint, reason="hard_sl")
            except Exception:
                pass
            return

        # TIME STOP (sell ALL)  (condition: age > TIME_STOP_SEC AND pnl < TIME_STOP_MIN_PNL)
        if entry_ts > 0 and (now - entry_ts) > self.TIME_STOP_SEC and pnl < self.TIME_STOP_MIN_PNL:
            print(f"⏱️ TIME_STOP mint={mint} pnl={pnl:.2%}", flush=True)
            if os.getenv("SELL_DRY_RUN", "0") == "1":
                print("🧪 SELL_DRY_RUN=1 -> skip TIME_STOP sell", flush=True)
                return
            sell_qty = qty_total
            # TIME_STOP_GUARD: only sell if pnl >= min pnl
            if pnl < self.TIME_STOP_MIN_PNL:
                print(f"⏱️ TIME_STOP skip: pnl {pnl:.2%} < min {self.TIME_STOP_MIN_PNL:.2%}")
                return
            txsig = self._sell_exec(mint, sell_qty, "time_stop")
            if txsig == '__DUST__':
                # mark closed in DB and continue
                try:
                    self.db.close_position(mint, now, 'dust_untradeable', 0.0)
                except Exception as e:
                    print(f"❌ close dust failed mint={mint} err={e}")
                return
            if not txsig:
                return
            print(f"✅ SOLD TIME_STOP txsig={txsig}", flush=True)
            try:
                self.db.close_position(mint, reason="time_stop")
            except Exception:
                pass
            return

        # TP1
        if (not tp1) and pnl >= self.TP1_PCT:
            sell_qty = qty_total * float(self.TP1_SIZE)
            if sell_qty <= 0:
                print(f"⏭️ TP1 SKIP qty<=0 mint={mint}", flush=True)
                return
            print(f"🟢 TP1 mint={mint} qty={sell_qty}", flush=True)
            if os.getenv("SELL_DRY_RUN", "0") == "1":
                print("🧪 SELL_DRY_RUN=1 -> skip TP1 sell", flush=True)
                return
            txsig = self._sell_exec(mint, sell_qty, "tp1")
            if txsig == "__COOLDOWN__":
                return
            if txsig == "__COOLDOWN__":
                return
            if txsig == '__DUST__':
                # mark closed in DB and continue
                try:
                    self.db.close_position(mint, now, 'dust_untradeable', 0.0)
                except Exception as e:
                    print(f"❌ close dust failed mint={mint} err={e}")
                return
            if not txsig:
                return
            print(f"✅ SOLD TP1 txsig={txsig}", flush=True)
            try:
                self.db.mark_tp1(mint)
            except Exception:
                pass
            return

        # TP2
        if tp1 and (not tp2) and pnl >= self.TP2_PCT:
            sell_qty = qty_total * float(self.TP2_SIZE)
            if sell_qty <= 0:
                print(f"⏭️ TP2 SKIP qty<=0 mint={mint}", flush=True)
                return
            print(f"🟢 TP2 mint={mint} qty={sell_qty}", flush=True)
            if os.getenv("SELL_DRY_RUN", "0") == "1":
                print("🧪 SELL_DRY_RUN=1 -> skip TP2 sell", flush=True)
                return
            txsig = self._sell_exec(mint, sell_qty, "tp2")
            if txsig == "__COOLDOWN__":
                return
            if txsig == "__COOLDOWN__":
                return
            if txsig == '__DUST__':
                # mark closed in DB and continue
                try:
                    self.db.close_position(mint, now, 'dust_untradeable', 0.0)
                except Exception as e:
                    print(f"❌ close dust failed mint={mint} err={e}")
                return
            if not txsig:
                return
            print(f"✅ SOLD TP2 txsig={txsig}", flush=True)
            try:
                self.db.mark_tp2(mint)
            except Exception:
                pass
            return

        # TRAIL (sell ALL)
        trail = self.TRAIL_WIDE if tp2 else self.TRAIL_TIGHT
        stop_price = hw * (1 - trail)
        if hw > 0 and price <= stop_price:
            print(f"🟠 TRAIL_STOP mint={mint} price={price} stop={stop_price} hw={hw}", flush=True)
            if os.getenv("SELL_DRY_RUN", "0") == "1":
                print("🧪 SELL_DRY_RUN=1 -> skip TRAIL sell", flush=True)
                return
            sell_qty = qty_total
            txsig = self._sell_exec(mint, sell_qty, "trailing_stop")
            if txsig == '__DUST__':
                # mark closed in DB and continue
                try:
                    self.db.close_position(mint, now, 'dust_untradeable', 0.0)
                except Exception as e:
                    print(f"❌ close dust failed mint={mint} err={e}")
                return
            if not txsig:
                return
            print(f"✅ SOLD TRAIL txsig={txsig}", flush=True)
            try:
                self.db.close_position(mint, reason="trailing_stop")
            except Exception:
                pass
            return


# ---- Robust SELL exec controls (added by patch_sell_engine_safe.py)
SELL_SUBPROCESS_TIMEOUT_S = float(os.getenv("SELL_SUBPROCESS_TIMEOUT_S", "25"))
SELL_GLOBAL_COOLDOWN_S = float(os.getenv("SELL_GLOBAL_COOLDOWN_S", "180"))

# Global cooldown timestamp (unix seconds) to avoid hammering sells when SOL is low
_sell_cooldown_until = 0.0

def _now():
    return time.time()

def _sell_cooldown_active() -> bool:
    global _sell_cooldown_until
    return _now() < _sell_cooldown_until

def _sell_cooldown_set(reason: str):
    global _sell_cooldown_until
    _sell_cooldown_until = _now() + SELL_GLOBAL_COOLDOWN_S
    try:
        print(f"[SELL] global cooldown {SELL_GLOBAL_COOLDOWN_S:.0f}s reason={reason}")
    except Exception:
        pass

def _is_insufficient_funds_blob(blob: str) -> bool:
    if not blob:
            return ""
    b = blob.lower()
    # common markers: your own tag + typical simulation / custom program errors
    # 0x1788 observed in your logs -> treat as "insufficient SOL for fees/rent/ATA"
    hits = [
        "jup_insufficient_funds",
        "insufficient funds",
        "insufficient lamports",
        "insufficient balance",
        "custom program error: 0x1788",
        "0x1788",
        "insufficient funds for rent",
        "accountnotfound",
        "could not find account",
    ]
    return any(h in b for h in hits)
