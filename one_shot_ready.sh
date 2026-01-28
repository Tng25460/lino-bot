#!/usr/bin/env bash
set -euo pipefail

echo "== LINO: setup + fix + run =="

ts="$(date +%s)"

# --- 1) backup
cp -f core/trading.py "core/trading.py.bak.bad.$ts" 2>/dev/null || true
cp -f core/solana_client.py "core/solana_client.py.bak.$ts" 2>/dev/null || true

# --- 2) fix solana_client: never hardcode key
python3 - <<'PY'
import pathlib, re
p = pathlib.Path("core/solana_client.py")
s = p.read_text(encoding="utf-8")

if "import os" not in s:
    s = "import os\n" + s

# remove any hardcoded key like: self.jupiter_api_key = "...."
s = re.sub(r'self\.jupiter_api_key\s*=\s*".*?"',
           'self.jupiter_api_key = (os.getenv("JUPITER_API_KEY") or "").strip()',
           s)

# if no assignment exists at all, inject in __init__
if "self.jupiter_api_key" not in s:
    lines = s.splitlines(True)
    out = []
    injected = False
    for line in lines:
        out.append(line)
        if (not injected) and ("def __init__" in line):
            out.append('        self.jupiter_api_key = (os.getenv("JUPITER_API_KEY") or "").strip()\n')
            injected = True
    s = "".join(out)

p.write_text(s, encoding="utf-8")
print("✅ solana_client.py patched")
PY

python3 -m py_compile core/solana_client.py >/dev/null
echo "✅ solana_client.py compile OK"

# --- 3) fix trading.py if it doesn't compile (restore newest compiling backup)
if python3 -m py_compile core/trading.py >/dev/null 2>&1; then
  echo "✅ trading.py compile OK"
else
  echo "⚠️ trading.py broken -> searching newest compiling backup..."
  best=""
  while IFS= read -r f; do
    python3 -m py_compile "$f" >/dev/null 2>&1 || continue
    best="$f"
    break
  done < <(ls -1t core/trading.py.bak.* 2>/dev/null || true)

  if [ -z "$best" ]; then
    echo "❌ No compiling trading.py backup found."
    echo "Show me: nl -ba core/trading.py | sed -n '105,150p'"
    exit 1
  fi

  cp -f "$best" core/trading.py
  python3 -m py_compile core/trading.py >/dev/null
  echo "✅ trading.py restored from: $best"
fi

# --- 4) create/update .env.real and ask for key (hidden input)
touch .env.real
grep -q '^JUPITER_BASE_URL=' .env.real || echo 'JUPITER_BASE_URL="https://api.jup.ag"' >> .env.real
grep -q '^JUPITER_API_KEY=' .env.real || echo 'JUPITER_API_KEY=""' >> .env.real

current_key="$(grep -E '^JUPITER_API_KEY=' .env.real | tail -n1 | sed 's/^JUPITER_API_KEY=//')"
if [ "$current_key" = '""' ] || [ -z "$current_key" ]; then
  echo ""
  echo "🔑 Enter your Jupiter API key (input hidden), then press ENTER:"
  read -r -s JKEY
  echo ""
  if [ -z "${JKEY:-}" ]; then
    echo "❌ Empty key. Aborting."
    exit 1
  fi
  # replace line
  tmp="$(mktemp)"
  awk 'BEGIN{done=0} /^JUPITER_API_KEY=/{ if(!done){print "JUPITER_API_KEY=\""ENVIRON["JKEY"]"\""; done=1} else {print $0} ; next} {print $0} END{if(!done)print "JUPITER_API_KEY=\""ENVIRON["JKEY"]"\""}' .env.real > "$tmp"
  mv "$tmp" .env.real
  chmod 600 .env.real
  echo "✅ Saved to .env.real (chmod 600)"
else
  echo "✅ .env.real already has a key"
fi

# --- 5) run bot
set +u
source .venv/bin/activate
set -u
set +u
source .env.real
set -u

echo ""
echo "✅ Env loaded. Starting bot..."
python3 src/main.py
