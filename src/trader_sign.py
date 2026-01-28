import base64
import json
import os
from pathlib import Path

# Inputs
IN_TX_B64_PATH = Path(os.getenv("TRADER_LAST_TX_B64_PATH", "last_swap_tx.b64"))
KEYPAIR_PATH = Path(os.getenv("TRADER_KEYPAIR_PATH", "keypair.json"))

# Outputs
OUT_SIGNED_TX_B64_PATH = Path(os.getenv("TRADER_SIGNED_TX_B64_PATH", "last_swap_tx.signed.b64"))

def load_keypair_bytes(path: Path) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) < 64:
        raise ValueError("keypair.json invalide: attendu une liste de 64 ints")
    return bytes(int(x) & 0xFF for x in data[:64])

def main() -> None:
    if not IN_TX_B64_PATH.exists():
        raise SystemExit(f"❌ input tx missing: {IN_TX_B64_PATH}")
    if not KEYPAIR_PATH.exists():
        raise SystemExit(f"❌ keypair missing: {KEYPAIR_PATH}")

    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
    except Exception as e:
        raise SystemExit(
            "❌ solders manquant. Fais:\n"
            "   pip install -U solders\n"
            f"   err={e}"
        )

    tx_b64 = IN_TX_B64_PATH.read_text(encoding="utf-8").strip()
    raw = base64.b64decode(tx_b64)

    kp = Keypair.from_bytes(load_keypair_bytes(KEYPAIR_PATH))

    # Parse unsigned tx
    tx = VersionedTransaction.from_bytes(raw)

    # ✅ SIGN PROPERLY: rebuild a new VersionedTransaction using the same message + signer
    # This ensures signatures array length matches numRequiredSignatures.
    signed_tx = VersionedTransaction(tx.message, [kp])

    signed_raw = bytes(signed_tx)
    signed_b64 = base64.b64encode(signed_raw).decode("utf-8")

    OUT_SIGNED_TX_B64_PATH.write_text(signed_b64, encoding="utf-8")

    # txid = first signature (base58)
    import base58
    sig0 = base58.b58encode(bytes(signed_tx.signatures[0])).decode("utf-8")

    print("✅ SIGN OK")
    print("   in :", str(IN_TX_B64_PATH))
    print("   out:", str(OUT_SIGNED_TX_B64_PATH))
    print("   tx_bytes:", len(raw))
    print("   signed_bytes:", len(signed_raw))
    print("   txid(sig0):", sig0)
    print("   signer pubkey:", str(kp.pubkey()))

if __name__ == "__main__":
    main()
