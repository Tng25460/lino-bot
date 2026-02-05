#!/usr/bin/env bash
set -euo pipefail

# ====== CONFIG ======
LINUX_SRC="${LINUX_SRC:-$HOME/lino}"

# Windows Desktop auto-detect (tu peux override: WIN_SRC=/mnt/c/Users/XXX/Desktop/lino-bot-win)
if [[ -z "${WIN_SRC:-}" ]]; then
  # Essaye de détecter un dossier "lino" / "lino-bot" sur le Desktop Windows
  WIN_SRC=""
  for u in /mnt/c/Users/*; do
    for cand in "$u/Desktop/lino" "$u/Desktop/lino-bot" "$u/Desktop/lino-bot-win" "$u/Desktop/BotLino" "$u/Desktop/BotLino_Win" "$u/Desktop/lino-bot-main"; do
      if [[ -d "$cand" ]]; then WIN_SRC="$cand"; break; fi
    done
    [[ -n "$WIN_SRC" ]] && break
  done
else
  WIN_SRC="$WIN_SRC"
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_BASE="${OUT_BASE:-$HOME/state/FROZEN_MERGE_$STAMP}"
FROZEN="$OUT_BASE/frozen"          # base figée (LINUX prioritaire)
AUDIT="$OUT_BASE/audit"            # rapports + diffs + copies windows
DIFFS="$AUDIT/diffs"
WIN_COPIES="$AUDIT/windows_copies"
META="$AUDIT/meta"

mkdir -p "$FROZEN" "$DIFFS" "$WIN_COPIES" "$META"

echo "[INFO] LINUX_SRC=$LINUX_SRC"
echo "[INFO] WIN_SRC=${WIN_SRC:-<not found>}"
echo "[INFO] OUT_BASE=$OUT_BASE"

# ====== EXCLUDES (évite state/logs/.venv/artefacts) ======
EXC=(
  "--exclude=.git"
  "--exclude=.venv"
  "--exclude=__pycache__"
  "--exclude=*.pyc"
  "--exclude=state"
  "--exclude=logs"
  "--exclude=last_swap_*.json"
  "--exclude=last_swap_*.b64"
  "--exclude=*.log"
  "--exclude=brain.sqlite"
  "--exclude=trades.sqlite"
  "--exclude=*.sqlite"
  "--exclude=config/local_secrets.py"
  "--exclude=.env"
  "--exclude=.env.*"
)

# ====== 1) COPY LINUX -> FROZEN ======
echo "[STEP] Copy Linux -> frozen"
rsync -a --delete "${EXC[@]}" "$LINUX_SRC/" "$FROZEN/"

# ====== 2) SNAPSHOT META ======
echo "[STEP] Meta snapshot"
{
  echo "===== FROZEN MERGE META ====="
  echo "stamp=$STAMP"
  echo "linux_src=$LINUX_SRC"
  echo "win_src=${WIN_SRC:-}"
  echo "host=$(hostname)"
  echo "whoami=$(whoami)"
  echo "date=$(date -Is)"
  echo "python=$(command -v python || true)"
  python -V 2>/dev/null || true
} > "$META/meta.txt"

# git info (linux src)
if [[ -d "$LINUX_SRC/.git" ]]; then
  (cd "$LINUX_SRC" && {
    echo "===== GIT (LINUX_SRC) ====="
    git rev-parse --is-inside-work-tree || true
    git branch --show-current || true
    git rev-parse HEAD || true
    echo "----- status porcelain -----"
    git status --porcelain || true
    echo "----- last 15 commits -----"
    git --no-pager log --oneline -n 15 || true
  }) > "$META/git_linux.txt" 2>&1 || true
fi

# ====== 3) IF WINDOWS EXISTS: diff + copy missing + save conflicts ======
if [[ -n "${WIN_SRC:-}" && -d "$WIN_SRC" ]]; then
  echo "[STEP] Windows diff + import missing + save conflicts"

  # full tree lists
  (cd "$LINUX_SRC" && find . -type f | sed 's|^\./||' | sort) > "$META/files_linux.txt"
  (cd "$WIN_SRC"   && find . -type f | sed 's|^\./||' | sort) > "$META/files_windows.txt"

  # quick dir diff (names + size/mtime differences)
  diff -qr "$LINUX_SRC" "$WIN_SRC" > "$AUDIT/diff_qr_linux_vs_windows.txt" || true

  # build a union file list (excluding junk)
  awk '
    {print}
  ' "$META/files_linux.txt" "$META/files_windows.txt" \
  | sort -u \
  | grep -Ev '(^state/|^logs/|^\.git/|^\.venv/|__pycache__|\.pyc$|\.log$|brain\.sqlite|trades\.sqlite|\.sqlite$|^last_swap_|^config/local_secrets\.py$|^\.env)' \
  > "$META/files_union.txt"

  # For each file in union:
  # - if only in Windows -> copy into frozen
  # - if in both and different -> keep Linux in frozen, store Windows copy + unified diff
  n_only_win=0
  n_conflict=0
  n_same=0

  while IFS= read -r rel; do
    l="$LINUX_SRC/$rel"
    w="$WIN_SRC/$rel"
    f="$FROZEN/$rel"

    if [[ -f "$w" && ! -f "$l" ]]; then
      mkdir -p "$(dirname "$f")"
      rsync -a "$w" "$f"
      n_only_win=$((n_only_win+1))
      continue
    fi

    if [[ -f "$l" && -f "$w" ]]; then
      if cmp -s "$l" "$w"; then
        n_same=$((n_same+1))
        continue
      fi
      # conflict: keep Linux in frozen (already copied), save Windows + diff
      mkdir -p "$WIN_COPIES/$(dirname "$rel")" "$DIFFS/$(dirname "$rel")"
      rsync -a "$w" "$WIN_COPIES/$rel.win"
      diff -u "$l" "$w" > "$DIFFS/$rel.diff" || true
      n_conflict=$((n_conflict+1))
    fi
  done < "$META/files_union.txt"

  {
    echo "only_in_windows_copied=$n_only_win"
    echo "conflicts_saved=$n_conflict"
    echo "same_files=$n_same"
  } > "$META/merge_stats.txt"

else
  echo "[WARN] WIN_SRC not found. Set it manually then rerun:"
  echo "  WIN_SRC=/mnt/c/Users/<YOU>/Desktop/<WindowsBotLinoFolder> bash scripts/freeze_merge_linux_windows.sh"
fi

# ====== 4) Sanity compile (frozen) ======
echo "[STEP] Python compile sanity (frozen)"
PYBAD=0
python - <<'PY' || PYBAD=1
import os, py_compile, sys
root = os.environ.get("FROZEN_DIR")
if not root:
    print("missing FROZEN_DIR env"); sys.exit(2)
bad=0
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in (".git",".venv","__pycache__","state","logs")]
    for fn in filenames:
        if fn.endswith(".py"):
            p=os.path.join(dirpath, fn)
            try:
                py_compile.compile(p, doraise=True)
            except Exception as e:
                bad += 1
                print("[PY_COMPILE_BAD]", p, "->", e)
print("PY_COMPILE_BAD=", bad)
sys.exit(0 if bad==0 else 1)
PY

echo "FROZEN_DIR=$FROZEN" >> "$META/meta.txt"
echo "AUDIT_DIR=$AUDIT"   >> "$META/meta.txt"

echo
echo "✅ DONE"
echo "OUT_BASE=$OUT_BASE"
echo "FROZEN=$FROZEN"
echo "AUDIT=$AUDIT"
if [[ -f "$META/merge_stats.txt" ]]; then
  echo "--- merge_stats ---"
  cat "$META/merge_stats.txt"
fi
