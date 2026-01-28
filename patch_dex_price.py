from pathlib import Path
import re

p = Path("core/trading.py")
src = p.read_text(encoding="utf-8").splitlines(True)

def join():
    return "".join(src)

def has(rx: str) -> bool:
    return re.search(rx, join(), re.M) is not None

changed = []

# A) import requests
if not has(r'^\s*import\s+requests\s*$') and not has(r'^\s*from\s+requests\s+import'):
    ins = 0
    for i, ln in enumerate(src[:250]):
        if re.match(r'^\s*(import|from)\s+\S+', ln):
            ins = i
    src.insert(ins+1, "import requests\n")
    changed.append("import_requests")

# B) détecter l'indent des méthodes de classe
method_indent = None
for ln in src:
    m = re.match(r'^(\s*)def\s+_recent_sells_path\s*\(', ln)
    if m:
        method_indent = m.group(1)
        break
if method_indent is None:
    for ln in src:
        m = re.match(r'^(\s*)def\s+_[A-Za-z0-9_]+\s*\(', ln)
        if m:
            method_indent = m.group(1)
            break
if method_indent is None:
    raise SystemExit("❌ Impossible de détecter l'indent des méthodes.")

mi = method_indent
bi = method_indent + "    "

# C) helper _fetch_price_dexscreener
if not has(r'^\s*def\s+_fetch_price_dexscreener\s*\('):
    insert_at = None
    for i, ln in enumerate(src):
        if re.match(r'^\s*async\s+def\s+_manage_positions\s*\(', ln):
            insert_at = i
            break
    if insert_at is None:
        raise SystemExit("❌ _manage_positions introuvable.")

    helper = [
        "\n",
        f"{mi}def _fetch_price_dexscreener(self, mint: str) -> float:\n",
        f"{bi}\"\"\"Fallback price via DexScreener. Returns 0.0 if unavailable.\"\"\"\n",
        f"{bi}try:\n",
        f"{bi}    url = f\"https://api.dexscreener.com/latest/dex/tokens/{{mint}}\"\n",
        f"{bi}    r = requests.get(url, timeout=12)\n",
        f"{bi}    if r.status_code != 200:\n",
        f"{bi}        return 0.0\n",
        f"{bi}    j = r.json() or {{}}\n",
        f"{bi}    pairs = j.get('pairs') or []\n",
        f"{bi}    best_px = 0.0\n",
        f"{bi}    best_liq = 0.0\n",
        f"{bi}    for pr in pairs:\n",
        f"{bi}        try:\n",
        f"{bi}            liq = float(((pr.get('liquidity') or {{}}).get('usd')) or 0.0)\n",
        f"{bi}            pxs = pr.get('priceUsd')\n",
        f"{bi}            if pxs is None:\n",
        f"{bi}                continue\n",
        f"{bi}            px = float(pxs or 0.0)\n",
        f"{bi}            if px > 0 and liq >= best_liq:\n",
        f"{bi}                best_liq = liq\n",
        f"{bi}                best_px = px\n",
        f"{bi}        except Exception:\n",
        f"{bi}            continue\n",
        f"{bi}    return float(best_px or 0.0)\n",
        f"{bi}except Exception:\n",
        f"{bi}    return 0.0\n",
        "\n",
    ]
    src[insert_at:insert_at] = helper
    changed.append("add_helper")

# D) bloc fallback dans _manage_positions
if not has(r'^\s*#\s*\[PRICE\]\s*fallback\s*DexScreener'):
    manage_start = None
    target = None
    for i, ln in enumerate(src):
        if re.match(r'^\s*async\s+def\s+_manage_positions\s*\(', ln):
            manage_start = i
            continue
        if manage_start is not None:
            if re.match(r'^\s*(async\s+def|def)\s+\w+\s*\(', ln) and i > manage_start:
                break
            if "price = _safe_float(price_map.get(mint)" in ln:
                target = i
                break

    if target is None:
        raise SystemExit("❌ Ligne price = _safe_float(price_map.get(mint) introuvable.")

    ind = re.match(r'^(\s*)', src[target]).group(1)
    block = [
        f"{ind}# [PRICE] fallback DexScreener if no scanner/jupiter price\n",
        f"{ind}try:\n",
        f"{ind}    sm = str(mint)\n",
        f"{ind}    if float(price_map.get(sm) or 0.0) <= 0.0:\n",
        f"{ind}        px_ds = float(self._fetch_price_dexscreener(sm) or 0.0)\n",
        f"{ind}        if px_ds > 0:\n",
        f"{ind}            price_map[sm] = px_ds\n",
        f"{ind}            if getattr(self, 'logger', None):\n",
        f"{ind}                self.logger.info('[PRICE] fallback dexscreener mint=%s px=%s', sm, px_ds)\n",
        f"{ind}except Exception as e:\n",
        f"{ind}    if getattr(self, 'logger', None):\n",
        f"{ind}        self.logger.warning('[PRICE] fallback error mint=%s err=%s', mint, e)\n",
        "\n",
    ]
    src[target:target] = block
    changed.append("add_block")

p.write_text("".join(src), encoding="utf-8")
print("✅ Patch applied:", ", ".join(changed) if changed else "nothing_to_do")
