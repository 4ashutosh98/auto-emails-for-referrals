from __future__ import annotations

from typing import List, MutableSequence

from .config import AlertConfig

RUN_LOG: List[dict] = []
ERROR_COUNT: int = 0


def reset():
    RUN_LOG.clear()
    global ERROR_COUNT
    ERROR_COUNT = 0


def _log_event(level: str, msg: str) -> None:
    import time

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    RUN_LOG.append({
        "ts": ts,
        "level": level.upper(),
        "msg": msg,
    })


def log_info(msg: str, verbose: bool = False) -> None:
    if verbose:
        print(msg)
    _log_event("info", msg)


def log_warn(msg: str, verbose: bool = False) -> None:
    if verbose:
        print(f"WARN: {msg}")
    _log_event("warn", msg)


def log_error(msg: str) -> None:
    global ERROR_COUNT
    ERROR_COUNT += 1
    print(f"ERROR: {msg}")
    _log_event("error", msg)


def render_run_log_text(entries: MutableSequence[dict] | None = None) -> str:
    log_entries = entries if entries is not None else RUN_LOG
    return "\n".join(f"{e['ts']} [{e['level']}] {e['msg']}" for e in log_entries)


def should_send_alert(alert: AlertConfig) -> bool:
    if not alert.email or alert.mode == "never":
        return False
    if alert.mode == "always":
        return True
    return ERROR_COUNT > 0
