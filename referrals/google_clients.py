from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .config import AppConfig, SCOPES
from . import log_utils


class CredentialError(RuntimeError):
    """Raised when OAuth credentials are missing or invalid."""


def _credentials_path() -> Path:
    return Path("credentials.json")


def _token_path() -> Path:
    return Path("token.json")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def preflight_validate_credentials(config: AppConfig) -> None:
    missing = []
    cred_path = _credentials_path()
    token_path = _token_path()
    if not cred_path.exists():
        missing.append("credentials.json")
    if not token_path.exists():
        missing.append("token.json")
    if missing:
        raise CredentialError(f"Missing credential file(s): {', '.join(missing)}")

    try:
        _load_json(cred_path)
    except Exception as exc:
        raise CredentialError(f"credentials.json invalid JSON: {exc}") from exc

    try:
        token_doc = _load_json(token_path)
    except Exception as exc:
        raise CredentialError(f"token.json invalid JSON: {exc}") from exc

    try:
        creds = Credentials.from_authorized_user_info(token_doc, config.scopes)
    except Exception as exc:
        raise CredentialError(f"token.json could not be loaded as Google credentials: {exc}") from exc

    if not creds:
        raise CredentialError("token.json did not contain usable OAuth credentials.")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
            except Exception as exc:
                raise CredentialError(f"Google OAuth token refresh failed: {exc}") from exc
        else:
            raise CredentialError(
                "Google OAuth token is invalid or missing a refresh token; "
                "recreate token.json locally and update the secret."
            )

    if not creds.valid:
        raise CredentialError("Google OAuth token is still invalid after refresh; regenerate token.json and update the secret.")

    _validate_scopes(token_doc)


def _validate_scopes(token_doc: dict) -> None:
    scopes = token_doc.get("scopes") or token_doc.get("scope", "").split()
    normalized = {str(scope).strip() for scope in scopes if str(scope).strip()}
    missing_scopes = set(SCOPES) - normalized if normalized else set(SCOPES)
    if missing_scopes:
        raise CredentialError(f"token.json missing required scopes: {missing_scopes}")
    if "https://www.googleapis.com/auth/gmail.send" not in normalized:
        raise CredentialError("token.json missing gmail.send scope (required). Recreate the token with required permissions.")


def _build_credentials(config: AppConfig, interactive: bool = True) -> Credentials:
    creds: Optional[Credentials] = None
    token_path = _token_path()
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), config.scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            if config.refresh_debug:
                log_utils.log_info("Attempting Gmail token refresh...", verbose=config.verbose)
            creds.refresh(Request())
            if config.refresh_debug:
                log_utils.log_info("Gmail token refresh succeeded.", verbose=config.verbose)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as exc:
            log_utils.log_error(f"Gmail token refresh failed: {exc}")

    if not interactive:
        raise CredentialError(
            "Google OAuth token.json missing or invalid in CI. "
            "Generate it locally with required scopes and store the JSON in the secret GOOGLE_TOKEN_JSON."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(_credentials_path()), config.scopes)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service(config: AppConfig) -> Optional[object]:
    try:
        creds = _build_credentials(config, interactive=not (os.getenv("CI") or os.getenv("GITHUB_ACTIONS")))
        return build("gmail", "v1", credentials=creds)
    except CredentialError as exc:
        log_utils.log_error(str(exc))
        return None


def get_drive_service(config: AppConfig) -> Optional[object]:
    try:
        creds = _build_credentials(config, interactive=not (os.getenv("CI") or os.getenv("GITHUB_ACTIONS")))
        return build("drive", "v3", credentials=creds)
    except CredentialError as exc:
        log_utils.log_error(str(exc))
        return None


def get_sheets_service(config: AppConfig) -> Optional[object]:
    try:
        creds = _build_credentials(config, interactive=not (os.getenv("CI") or os.getenv("GITHUB_ACTIONS")))
        return build("sheets", "v4", credentials=creds)
    except CredentialError as exc:
        log_utils.log_error(str(exc))
        return None
