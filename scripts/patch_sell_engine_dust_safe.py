import re
from pathlib import Path

p = Path("core/sell_engine.py")
s = p.read_text(encoding="utf-8")

# ensure import os
if not re.search(r'(?m)^\s*import\s+os\s*$', s):
    m = re.search(r'(?ms)^(?:\s*(?:import|from)\s+[^\n]+\n)+', s)
    s = (s[:m.end()] + "import os\n" + s[m.end():]) if m else ("import os\n" + s)

# insert guard just before the RuntimeError raise inside _sell_exec
needle = 'raise RuntimeError(f"sell_exec failed rc={proc.returncode} txsig={txsig}")'
if needle not in s:
    raise SystemExit("FATAL: could not find RuntimeError line in _sell_exec")

guard = (
"        # --- DUST guard: Jupiter can return 400 Bad Request for tiny amount=1\n"
"        def _to_str(x):\n"
"            return x.decode(errors='ignore') if isinstance(x, (bytes, bytearray)) else (x or '')\n"
"        out_all = (_to_str(getattr(proc, 'stdout', '')) + \"\\\\n\" + _to_str(getattr(proc, 'stderr', ''))).strip()\n"
"        if ('400 Client Error' in out_all and 'Bad Request' in out_all and 'amount=1' in out_all):\n"
"            print(f\"🧹 DUST_UNTRADEABLE mint={mint} (amount=1) -> close locally\")\n"
"            return '__DUST__'\n"
)

s = s.replace(needle, guard + "        " + needle)

p.write_text(s, encoding="utf-8")
print("✅ patched: _sell_exec dust guard inserted")
