from __future__ import annotations

import time
from typing import Optional

from googleapiclient.discovery import Resource

from .config import AppConfig
from . import log_utils
from .emailer import create_message_with_attachment, send_message


def send_alert_email(service: Optional[Resource], config: AppConfig, subject_suffix: str = "") -> None:
    if not log_utils.should_send_alert(config.alert):
        return
    if service is None:
        # Last resort: print log output so at least something surfaces.
        print("Unable to send alert email: Gmail service unavailable.")
        print(log_utils.render_run_log_text())
        return

    subject_core = "Run errors" if log_utils.ERROR_COUNT > 0 else "Run report"
    subject_suffix = f" - {subject_suffix}" if subject_suffix else ""
    subject = f"{config.alert.subject_prefix} {subject_core}{subject_suffix}".strip()
    summary = (
        f"Run summary: errors={log_utils.ERROR_COUNT}, entries={len(log_utils.RUN_LOG)}.\n"
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
    )
    body = summary + log_utils.render_run_log_text()
    attachment = {
        "bytes": body.encode("utf-8"),
        "filename": "run.log.txt",
        "mimeType": "text/plain",
    }
    message = create_message_with_attachment(
        to=config.alert.email,
        subject=subject,
        body=body,
        attachment=attachment,
        headers={
            "X-Referrals-Bot": "1",
            "X-Referrals-Alert": "1",
        },
    )
    try:
        send_message(service, "me", message)
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"ERROR: failed to send alert email to {config.alert.email}: {exc}")
