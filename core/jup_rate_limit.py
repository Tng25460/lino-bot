import os, time
import fcntl

# Base interval (seconds)
BASE_INTERVAL = float(os.getenv("JUP_MIN_QUOTE_INTERVAL_S", "3.5"))

# Adaptive bounds
MIN_INTERVAL = float(os.getenv("JUP_MIN_QUOTE_INTERVAL_MIN_S", str(BASE_INTERVAL)))
MAX_INTERVAL = float(os.getenv("JUP_MIN_QUOTE_INTERVAL_MAX_S", "12.0"))

# Adaptive tuning
# - on 429: interval *= UP_FACTOR (capped)
# - on success: interval -= DOWN_STEP (floored)
UP_FACTOR = float(os.getenv("JUP_RL_UP_FACTOR", "1.25"))
DOWN_STEP = float(os.getenv("JUP_RL_DOWN_STEP", "0.10") or "0.10")
if DOWN_STEP <= 0:
    DOWN_STEP = 0.10

# lock+state file shared across processes
LOCK_PATH = os.getenv("JUP_RL_LOCK_PATH", "/tmp/lino_jup_rl.lock")
JUP_RL_DEBUG = int(os.getenv("JUP_RL_DEBUG", "0"))

def _open_lock():
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
    return fd

def _read_state(fd):
    """
    File format: "<last_ts> <cur_interval>\n"
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, 128) or b""
        s = data.decode("utf-8", "ignore").strip()
        if not s:
            return 0.0, BASE_INTERVAL
        parts = s.split()
        last_ts = float(parts[0]) if len(parts) >= 1 else 0.0
        cur_itv = float(parts[1]) if len(parts) >= 2 else BASE_INTERVAL
        return last_ts, cur_itv
    except Exception:
        return 0.0, BASE_INTERVAL

def _write_state(fd, last_ts: float, cur_itv: float):
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, (f"{last_ts:.6f} {cur_itv:.6f}\n").encode("utf-8"))
    os.ftruncate(fd, os.lseek(fd, 0, os.SEEK_CUR))

def wait_for_slot() -> None:
    fd = _open_lock()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        last_ts, cur_itv = _read_state(fd)
        # clamp
        cur_itv = max(MIN_INTERVAL, min(MAX_INTERVAL, cur_itv))
        if JUP_RL_DEBUG:
            try:
                print(f"[jup_rl] rl_debug CONST base={BASE_INTERVAL:.3f} min={MIN_INTERVAL:.3f} max={MAX_INTERVAL:.3f} up={UP_FACTOR:.3f} down={DOWN_STEP:.3f}", flush=True)
            except Exception:
                pass
        now = time.time()
        # fix fresh lock state (last_ts=0) to avoid huge negative waits
        if last_ts <= 0:
            last_ts = now

        wait = cur_itv - (now - last_ts)
        if JUP_RL_DEBUG:
            try:
                print(f"[jup_rl] rl_debug cur_itv={cur_itv:.3f} wait={wait:.3f} now={now:.3f} last_ts={last_ts:.3f}", flush=True)
            except Exception:
                pass

        if wait > 0:
            if JUP_RL_DEBUG:
                try:
                    # interval might be named differently; best-effort
                    _ival = locals().get('interval', None)
                    if isinstance(_ival, (int, float)):
                        print(f"[jup_rl] interval={{_ival:.3f}}", flush=True)
                    else:
                        pass  # removed noisy interval log
                except Exception:
                    pass
            time.sleep(wait)
        # update last_ts only (keep cur_itv)
        _write_state(fd, time.time(), cur_itv)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)

def note_result(ok: bool, was_429: bool = False) -> None:
    """
    Feedback loop for adaptive interval (IPC).
    """
    fd = _open_lock()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        last_ts, cur_itv = _read_state(fd)
        cur_itv = max(MIN_INTERVAL, min(MAX_INTERVAL, cur_itv))

        if was_429 or (not ok):
            cur_itv = min(MAX_INTERVAL, max(cur_itv, MIN_INTERVAL) * UP_FACTOR)
        else:
            cur_itv = max(MIN_INTERVAL, cur_itv - DOWN_STEP)

        _write_state(fd, last_ts, cur_itv)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
