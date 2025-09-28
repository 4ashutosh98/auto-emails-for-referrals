from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _parse_resume_map(raw: str | None) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return {str(k).lower(): str(v) for k, v in obj.items()}
    except json.JSONDecodeError:
        pass

    mapping: Dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            key, value = pair.split(":", 1)
            mapping[key.strip().lower()] = value.strip()
    return mapping


SCOPES: Tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
)

DEFAULT_TEMPLATES: Dict[str, str] = {
    "cold": "template_cold.txt",
    "warm": "template_warm.txt",
    "coffee": "template_coffee.txt",
    "direct": "template_direct.txt",
}


@dataclass(frozen=True)
class SheetConfig:
    spreadsheet_id: str
    sheet_range: str
    has_header: bool
    status_column: str | None
    sent_at_column: str | None


@dataclass(frozen=True)
class AlertConfig:
    email: str
    mode: str
    subject_prefix: str


@dataclass(frozen=True)
class ResumeConfig:
    default_name: str
    default_id: str | None
    folder_id: str | None
    resume_map: Dict[str, str]
    local_path: Path


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    model: str
    github_model: str | None
    github_endpoint: str | None
    github_token: str | None
    openai_api_key: str | None
    azure_api_key: str | None
    azure_endpoint: str | None
    azure_api_version: str | None
    azure_deployment: str | None


@dataclass(frozen=True)
class AppConfig:
    scopes: Tuple[str, ...]
    contacts_csv: str
    templates: Dict[str, str]
    daily_limit: int
    dry_run: bool
    verbose: bool
    alert: AlertConfig
    refresh_debug: bool
    use_sent_log: bool
    llm: LLMConfig
    sheets: SheetConfig
    resume: ResumeConfig


def load_config() -> AppConfig:
    contacts_csv = os.getenv("CONTACTS_CSV", "leads.csv")
    daily_limit = _env_int("DAILY_LIMIT", 0)
    dry_run = _env_bool("DRY_RUN", False)
    verbose = _env_bool("VERBOSE", False)

    alert = AlertConfig(
        email=os.getenv("ALERT_EMAIL", "").strip(),
        mode=os.getenv("ALERT_ON", "error").strip().lower(),
        subject_prefix=os.getenv("ALERT_SUBJECT_PREFIX", "[Referrals Bot]").strip(),
    )

    llm_provider = os.getenv("LLM_PROVIDER", "github").strip().lower()
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    llm_config = LLMConfig(
        enabled=_env_bool("USE_LLM", True),
        provider=llm_provider,
        model=llm_model,
        github_model=os.getenv("LLM_GITHUB_MODEL"),
        github_endpoint=os.getenv("LLM_GITHUB_MODELS_ENDPOINT"),
        github_token=os.getenv("LLM_GITHUB_TOKEN"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    )

    sheets = SheetConfig(
        spreadsheet_id=os.getenv("SHEETS_SPREADSHEET_ID", "").strip(),
        sheet_range=os.getenv("SHEETS_RANGE", "Contacts!A:F"),
        has_header=_env_bool("SHEETS_HAS_HEADER", True),
        status_column=os.getenv("SHEETS_STATUS_COLUMN", "").strip() or None,
        sent_at_column=os.getenv("SHEETS_SENT_AT_COLUMN", "").strip() or None,
    )

    resume = ResumeConfig(
        default_name=os.getenv("RESUME_DEFAULT_NAME", "").strip(),
        default_id=os.getenv("RESUME_DEFAULT_ID", "").strip() or None,
        folder_id=os.getenv("RESUME_FOLDER_ID", "").strip() or None,
        resume_map=_parse_resume_map(os.getenv("RESUME_MAP")),
        local_path=Path(os.getenv("RESUME_PATH", "Ashutosh_Choudhari_Resume.pdf")),
    )

    return AppConfig(
        scopes=SCOPES,
        contacts_csv=contacts_csv,
        templates=DEFAULT_TEMPLATES,
        daily_limit=daily_limit,
        dry_run=dry_run,
        verbose=verbose,
        alert=alert,
        refresh_debug=_env_bool("GOOGLE_REFRESH_DEBUG", False),
        use_sent_log=_env_bool("USE_SENT_LOG", False),
        llm=llm_config,
        sheets=sheets,
        resume=resume,
    )


CONFIG = load_config()
