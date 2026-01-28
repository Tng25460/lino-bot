import os
from dataclasses import dataclass
from pathlib import Path

def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip() in ("1", "true", "TRUE", "yes", "YES", "on", "ON")

def _mask(s: str, keep: int = 6) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) <= keep:
        return s
    return s[:keep] + "..."


@dataclass(frozen=True)
class Settings:
    mints_found_path: Path
    ready_path: Path
    db_path: Path

    jup_base: str
    jup_api_key: str
    rpc_http: str

    input_mint: str
    amount: int
    slippage_bps: int
    max_price_impact_pct: float

    dry_run: bool
    one_shot: bool
    confirm_send: bool

    poll_s: float

    def safe_summary(self) -> str:
        return (
            f"paths: mints_found={self.mints_found_path} ready={self.ready_path} db={self.db_path}\n"
            f"jup_base={self.jup_base} api_key={_mask(self.jup_api_key)}\n"
            f"rpc_http={self.rpc_http}\n"
            f"input_mint={self.input_mint}\n"
            f"amount={self.amount} slippage_bps={self.slippage_bps} max_pi={self.max_price_impact_pct}\n"
            f"dry_run={self.dry_run} one_shot={self.one_shot} confirm_send={self.confirm_send}\n"
            f"poll_s={self.poll_s}"
        )


def get_settings() -> Settings:
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    mints_found = Path(os.getenv("MINTS_FOUND_PATH", "mints_found.json"))
    ready_path = Path(os.getenv("READY_PATH", "ready_to_trade.jsonl"))
    db_path = Path(os.getenv("TRADER_DB_PATH", "state/trades.sqlite"))

    jup_base = (os.getenv("JUPITER_BASE_URL") or "https://api.jup.ag").rstrip("/")
    jup_api_key = (os.getenv("JUPITER_API_KEY") or "").strip()
    rpc_http = (os.getenv("SOLANA_RPC_HTTP") or "https://api.mainnet-beta.solana.com").strip()

    input_mint = (os.getenv("TRADER_INPUT_MINT") or usdc).strip()
    amount = int(os.getenv("TRADER_AMOUNT", "1000000"))        # 1 USDC (base units)
    slippage_bps = int(os.getenv("TRADER_SLIPPAGE_BPS", "50")) # 0.50%
    max_pi = float(os.getenv("TRADER_MAX_PRICE_IMPACT_PCT", "5.0"))

    dry_run = _env_bool("TRADER_DRY_RUN", "1")
    one_shot = _env_bool("TRADER_ONE_SHOT", "0")

    confirm_send = (os.getenv("TRADER_CONFIRM") or "").strip().upper() == "YES"
    poll_s = float(os.getenv("TRADER_POLL_S", "1.0"))

    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        mints_found_path=mints_found,
        ready_path=ready_path,
        db_path=db_path,
        jup_base=jup_base,
        jup_api_key=jup_api_key,
        rpc_http=rpc_http,
        input_mint=input_mint,
        amount=amount,
        slippage_bps=slippage_bps,
        max_price_impact_pct=max_pi,
        dry_run=dry_run,
        one_shot=one_shot,
        confirm_send=confirm_send,
        poll_s=poll_s,
    )
