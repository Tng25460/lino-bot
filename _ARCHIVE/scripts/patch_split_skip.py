import re
from pathlib import Path

def patch_file(path: Path, kind: str):
    s = path.read_text(encoding="utf-8")
    orig = s

    # Inject default skip env vars near the top (after imports) if not present
    if kind == "trader":
        if "TRADER_SKIP_MINTS_FILE" not in s:
            s = re.sub(
                r"(?m)^(import\s+os\s*)$",
                r"\1\n\n# skip_mints split (trader vs brain)\nTRADER_SKIP_MINTS_FILE = os.getenv('TRADER_SKIP_MINTS_FILE') or os.getenv('SKIP_MINTS_FILE') or 'state/skip_mints_trader.txt'\n",
                s,
                count=1
            )
        # Replace common patterns that read SKIP_MINTS_FILE
        s = s.replace("os.getenv('SKIP_MINTS_FILE',", "os.getenv('TRADER_SKIP_MINTS_FILE',")
        s = s.replace('os.getenv("SKIP_MINTS_FILE",', 'os.getenv("TRADER_SKIP_MINTS_FILE",')
        # If there is a literal default to state/skip_mints.txt, redirect to trader split file
        s = s.replace("state/skip_mints.txt", "state/skip_mints_trader.txt")

    if kind == "brain":
        if "BRAIN_SKIP_MINTS_FILE" not in s:
            s = re.sub(
                r"(?m)^(import\s+os\s*)$",
                r"\1\n\n# skip_mints split (trader vs brain)\nBRAIN_SKIP_MINTS_FILE = os.getenv('BRAIN_SKIP_MINTS_FILE') or os.getenv('SKIP_MINTS_FILE') or 'state/skip_mints_brain.txt'\n",
                s,
                count=1
            )
        s = s.replace("os.getenv('SKIP_MINTS_FILE',", "os.getenv('BRAIN_SKIP_MINTS_FILE',")
        s = s.replace('os.getenv("SKIP_MINTS_FILE",', 'os.getenv("BRAIN_SKIP_MINTS_FILE",')
        s = s.replace("state/skip_mints.txt", "state/skip_mints_brain.txt")

    if s != orig:
        path.write_text(s, encoding="utf-8")
        print(f"✅ patched {path}")
    else:
        print(f"ℹ️ no change {path}")

# paths (best effort)
root = Path(".")
trader = root / "src" / "trader_exec.py"
brain  = root / "src" / "brain" / "brain_loop.py"

if trader.exists():
    patch_file(trader, "trader")
else:
    print("⚠️ src/trader_exec.py not found")

if brain.exists():
    patch_file(brain, "brain")
else:
    print("⚠️ src/brain/brain_loop.py not found (ok si tu utilises brain_loop_v4 ailleurs)")
