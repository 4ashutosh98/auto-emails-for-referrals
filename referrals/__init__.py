"""Referral mailer package."""

from .config import CONFIG, AppConfig
from .run import execute_mailer, run_precheck

__all__ = [
    "CONFIG",
    "AppConfig",
    "execute_mailer",
    "run_precheck",
]
