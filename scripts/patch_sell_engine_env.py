import re
from pathlib import Path

p = Path("core/sell_engine.py")
s = p.read_text(encoding="utf-8")

# 1) ensure import os
if not re.search(r'(?m)^\s*import\s+os\s*$', s):
    m = re.search(r'(?ms)^(?:\s*(?:import|from)\s+[^\n]+\n)+', s)
    if m:
        s = s[:m.end()] + "import os\n" + s[m.end():]
    else:
        s = "import os\n" + s

# 2) inject helper functions once
if "def _env_float(" not in s:
    m = re.search(r'(?ms)^(?:\s*(?:import|from)\s+[^\n]+\n)+', s)
    helper = """
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

"""
    if m:
        s = s[:m.end()] + helper + s[m.end():]
    else:
        s = helper + s

# 3) patch assignments (both NAME= and self.NAME=)
settings = {
  "HARD_SL_PCT": ("float", "-0.25"),
  "TIME_STOP_MIN_PNL": ("float", "0.05"),
  "TIME_STOP_SEC": ("int", "900"),
  "TP1_PCT": ("float", "0.3"),
  "TP1_SIZE": ("float", "0.35"),
  "TP2_PCT": ("float", "0.8"),
  "TP2_SIZE": ("float", "0.35"),
  "TRAIL_TIGHT": ("float", "0.1"),
  "TRAIL_WIDE": ("float", "0.2"),
}

patched_count = 0

for name, (typ, default) in settings.items():
    fn = "_env_int" if typ == "int" else "_env_float"

    # NAME = 0.123
    pat1 = re.compile(rf'(?m)^(\s*{re.escape(name)}\s*=\s*)(-?\d+(?:\.\d+)?)(\s*(?:#.*)?)$')
    def r1(m):
        nonlocal_patched[0] += 1
        return f"{m.group(1)}{fn}('{name}', {default}){m.group(3)}"
    nonlocal_patched = [0]
    s2, n = pat1.subn(lambda m: (nonlocal_patched.__setitem__(0, nonlocal_patched[0]+1)) or f"{m.group(1)}{fn}('{name}', {default}){m.group(3)}", s)
    if n:
        patched_count += n
        s = s2

    # self.NAME = 0.123
    pat2 = re.compile(rf'(?m)^(\s*self\.{re.escape(name)}\s*=\s*)(-?\d+(?:\.\d+)?)(\s*(?:#.*)?)$')
    s2, n = pat2.subn(lambda m: f"{m.group(1)}{fn}('{name}', {default}){m.group(3)}", s)
    if n:
        patched_count += n
        s = s2

p.write_text(s, encoding="utf-8")
print(f"✅ patched {p} assignments={patched_count}")
