#!/usr/bin/env python3
import os, sys, inspect, traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

DB_PATH = os.getenv("TRADES_DB", "state/trades.sqlite")
KEYPAIR_PATH = os.getenv("KEYPAIR_PATH", "keypair.json")
RPCW = (os.getenv("RPC_HTTP_WRITE") or os.getenv("RPC_HTTP") or "https://api.mainnet-beta.solana.com").split(",")[0].strip()

def main():
    print("----- diag_sellengine_ctor -----")
    print("[cwd]", os.getcwd())
    print("[db ]", DB_PATH)
    print("[rpc]", RPCW)
    print("[keypair]", KEYPAIR_PATH)

    try:
        from core.sell_engine import SellEngine
    except Exception as e:
        print("[IMPORT_FAIL] core.sell_engine:", repr(e))
        traceback.print_exc()
        return 0

    try:
        sig = inspect.signature(SellEngine.__init__)
        print("[SellEngine.__init__ signature]", sig)
        params = list(sig.parameters.values())[1:]  # drop self
        req = [p for p in params if p.default is inspect._empty and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
        print("[required params]", [p.name for p in req] if req else "(none)")
    except Exception as e:
        print("[SIG_FAIL]", repr(e))
        traceback.print_exc()

    # tentative construction ultra-safe (aucun exit, tout catch)
    print("\n-- try construct variants (safe) --")

    # helpers optionnels
    wallet = None
    try:
        import json
        from solders.keypair import Keypair
        kp = KEYPAIR_PATH if os.path.isabs(KEYPAIR_PATH) else os.path.join(REPO, KEYPAIR_PATH)
        b = json.loads(open(kp, "r", encoding="utf-8").read())
        wallet = Keypair.from_bytes(bytes(b))
        print("[wallet] loaded solders.Keypair")
    except Exception as e:
        print("[wallet] not loaded:", repr(e))

    db_adapter = None
    try:
        from core.positions_db_adapter import PositionsDBAdapter
        db_adapter = PositionsDBAdapter(DB_PATH)
        print("[db_adapter] PositionsDBAdapter OK")
    except Exception as e:
        print("[db_adapter] not created:", repr(e))

    variants = []

    # kwargs candidates (common names)
    variants.append(("kwargs: db_path", dict(db_path=DB_PATH)))
    variants.append(("kwargs: db_path+rpc", dict(db_path=DB_PATH, rpc=RPCW)))
    if wallet is not None:
        variants.append(("kwargs: db_path+wallet", dict(db_path=DB_PATH, wallet=wallet)))
        variants.append(("kwargs: db_path+wallet+rpc", dict(db_path=DB_PATH, wallet=wallet, rpc=RPCW)))
    if db_adapter is not None:
        variants.append(("kwargs: db_adapter", dict(db=db_adapter)))
        variants.append(("kwargs: db_adapter+rpc", dict(db=db_adapter, rpc=RPCW)))
        if wallet is not None:
            variants.append(("kwargs: db_adapter+wallet", dict(db=db_adapter, wallet=wallet)))
            variants.append(("kwargs: db_adapter+wallet+rpc", dict(db=db_adapter, wallet=wallet, rpc=RPCW)))

    # positional candidates
    variants.append(("positional: (db_path)", (DB_PATH,)))
    variants.append(("positional: (db_path, rpc)", (DB_PATH, RPCW)))
    if wallet is not None:
        variants.append(("positional: (wallet)", (wallet,)))
        variants.append(("positional: (wallet, db_path)", (wallet, DB_PATH)))
        variants.append(("positional: (db_path, wallet)", (DB_PATH, wallet)))
        variants.append(("positional: (wallet, db_path, rpc)", (wallet, DB_PATH, RPCW)))
        variants.append(("positional: (db_path, wallet, rpc)", (DB_PATH, wallet, RPCW)))
    if db_adapter is not None:
        variants.append(("positional: (db_adapter)", (db_adapter,)))
        variants.append(("positional: (db_adapter, rpc)", (db_adapter, RPCW)))
        if wallet is not None:
            variants.append(("positional: (wallet, db_adapter)", (wallet, db_adapter)))
            variants.append(("positional: (db_adapter, wallet)", (db_adapter, wallet)))
            variants.append(("positional: (wallet, db_adapter, rpc)", (wallet, db_adapter, RPCW)))
            variants.append(("positional: (db_adapter, wallet, rpc)", (db_adapter, wallet, RPCW)))

    ok = 0
    for name, payload in variants:
        try:
            if isinstance(payload, dict):
                obj = SellEngine(**payload)
            else:
                obj = SellEngine(*payload)
            print("[OK]", name, "->", type(obj))
            ok += 1
            break
        except Exception as e:
            print("[FAIL]", name, "->", repr(e))

    if ok == 0:
        print("\n[RESULT] Cannot construct SellEngine with common variants.")
        print("=> Copy-paste me the signature line + the FIRST FAIL that looks most informative.")
    else:
        print("\n[RESULT] SellEngine constructed OK with variant above.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("[UNHANDLED]", repr(e))
        traceback.print_exc()
        raise SystemExit(0)
