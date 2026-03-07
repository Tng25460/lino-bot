#!/usr/bin/env bash
set -euo pipefail

# --- Jupiter ---
export JUP_BASE_URL="${JUP_BASE_URL:-https://lite-api.jup.ag}"

# Cache quote (évite spam)
export JUP_QUOTE_CACHE_TTL_S="${JUP_QUOTE_CACHE_TTL_S:-8}"
export JUP_QUOTE_CACHE_MAX="${JUP_QUOTE_CACHE_MAX:-512}"
export JUP_QUOTE_CACHE_DEBUG="${JUP_QUOTE_CACHE_DEBUG:-0}"

# Rate limit IPC (tous process)
export JUP_RL_LOCK_PATH="${JUP_RL_LOCK_PATH:-/tmp/lino_jup_rl.lock}"

# Base interval (mets 2.5-4s pour réduire 429)
export JUP_MIN_QUOTE_INTERVAL_S="${JUP_MIN_QUOTE_INTERVAL_S:-3.0}"

# Adaptive bounds
export JUP_MIN_QUOTE_INTERVAL_MIN_S="${JUP_MIN_QUOTE_INTERVAL_MIN_S:-2.0}"
export JUP_MIN_QUOTE_INTERVAL_MAX_S="${JUP_MIN_QUOTE_INTERVAL_MAX_S:-10.0}"

# Adaptive tuning
export JUP_RL_UP_FACTOR="${JUP_RL_UP_FACTOR:-1.35}"
export JUP_RL_DOWN_STEP="${JUP_RL_DOWN_STEP:-0.10}"

# Backoff 429 (déjà dans jupiter_exec)
export JUP_429_BACKOFF_BASE_S="${JUP_429_BACKOFF_BASE_S:-4}"
export JUP_429_BACKOFF_MAX_S="${JUP_429_BACKOFF_MAX_S:-30}"
export JUP_429_MAX_RETRIES="${JUP_429_MAX_RETRIES:-5}"

# --- RPC ---
# Sépare read vs write (write doit accepter sendTransaction)
export RPC_HTTP_WRITE="${RPC_HTTP_WRITE:-https://api.mainnet-beta.solana.com}"
export RPC_HTTP_READ="${RPC_HTTP_READ:-https://api.mainnet-beta.solana.com,https://rpc.ankr.com/solana}"

echo "✅ env_perf loaded"
env | grep -E '^(JUP_|RPC_HTTP_)' | sort
export TIME_STOP_MIN_PNL="${TIME_STOP_MIN_PNL:-0.05}"
export TIME_STOP_SEC="${TIME_STOP_SEC:-900}"
