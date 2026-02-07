# Codex rules for Bot Lino (lino_FINAL_20260203_182626)

- Never read/print/commit secrets (state/jup.env, .env*, keypair.json).
- Never modify runtime artifacts under state/ except when explicitly asked.
- Prefer minimal, high-confidence changes.
- Always create a git checkpoint commit before and after a task.
- After each change: run `python -m py_compile` (or `python -m compileall`) and show the result.
