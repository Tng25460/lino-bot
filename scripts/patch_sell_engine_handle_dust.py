import re
from pathlib import Path

p = Path("core/sell_engine.py")
lines = p.read_text(encoding="utf-8").splitlines(True)

out = []
patched = 0

for line in lines:
    out.append(line)
    # patch every call pattern: txsig = self._sell_exec(...)
    if re.search(r'^\s*txsig\s*=\s*self\._sell_exec\(', line):
        indent = re.match(r'^(\s*)', line).group(1)
        out.append(
            f"{indent}if txsig == '__DUST__':\n"
            f"{indent}    # mark closed in DB and continue\n"
            f"{indent}    try:\n"
            f"{indent}        self.db.close_position(mint, now, 'dust_untradeable', 0.0)\n"
            f"{indent}    except Exception as e:\n"
            f"{indent}        print(f\"❌ close dust failed mint={{mint}} err={{e}}\")\n"
            f"{indent}    return\n"
        )
        patched += 1

if patched == 0:
    raise SystemExit("FATAL: did not find any txsig = self._sell_exec(...) line to patch")

p.write_text("".join(out), encoding="utf-8")
print(f"✅ patched: handle __DUST__ after _sell_exec (count={patched})")
