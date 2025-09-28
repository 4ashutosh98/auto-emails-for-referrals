from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

SENT_LOG_PATH = Path("sent_log.json")


def load_sent_log() -> Dict:
    if SENT_LOG_PATH.exists():
        with SENT_LOG_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def save_sent_log(log: Dict) -> None:
    with SENT_LOG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=2)


def already_sent(log: Dict, name: str, email: str, role: str, company: str) -> bool:
    key = f"{name.lower()}::{role.lower()}::{company.lower()}"
    legacy_key = f"{email.lower()}::{role.lower()}::{company.lower()}"
    return key in log or legacy_key in log


def mark_sent(log: Dict, name: str, email: str, role: str, company: str, msg_id: str) -> None:
    key = f"{name.lower()}::{role.lower()}::{company.lower()}"
    legacy_key = f"{email.lower()}::{role.lower()}::{company.lower()}"
    log[key] = {"msg_id": msg_id, "ts": int(time.time())}
    if legacy_key in log:
        try:
            del log[legacy_key]
        except Exception:
            pass
