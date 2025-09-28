from __future__ import annotations

from pathlib import Path
from typing import Dict

from jinja2 import Template

from .config import AppConfig


def _resolve_template_path(name: str, templates: Dict[str, str]) -> Path:
    key = (name or "cold").lower()
    filename = templates.get(key, templates["cold"])
    return Path(filename)


def load_template(config: AppConfig, kind: str) -> Template:
    path = _resolve_template_path(kind, config.templates)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return Template(handle.read())
    except Exception:
        fallback = Path(config.templates["cold"])
        with fallback.open("r", encoding="utf-8") as handle:
            return Template(handle.read())


def load_template_text(config: AppConfig, kind: str) -> str:
    path = _resolve_template_path(kind, config.templates)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        fallback = Path(config.templates["cold"])
        with fallback.open("r", encoding="utf-8") as handle:
            return handle.read()
