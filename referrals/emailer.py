from __future__ import annotations
from __future__ import annotations

import base64
import io
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Optional, Tuple

from googleapiclient.discovery import Resource
from googleapiclient.http import MediaIoBaseDownload

from .config import AppConfig
from . import log_utils


def create_message_with_attachment(
    to: str,
    subject: str,
    body: str,
    attachment: Optional[Dict[str, object]] = None,
    attachment_path: Optional[Path] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject

    if headers:
        for key, value in headers.items():
            try:
                msg[key] = value
            except Exception:  # pragma: no cover - safeguard for invalid header content
                pass

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment and attachment.get("bytes"):
        data = attachment["bytes"]
        filename = attachment.get("filename", "resume.pdf")
        mime = attachment.get("mimeType", "application/pdf")
        subtype = "pdf" if str(mime).endswith("/pdf") or mime == "application/pdf" else "octet-stream"
        part = MIMEApplication(data, _subtype=subtype)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    elif attachment_path and attachment_path.exists():
        with attachment_path.open("rb") as handle:
            part = MIMEApplication(handle.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=attachment_path.name)
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_message(service: Resource, user_id: str, message: Dict[str, str]) -> Dict:
    return service.users().messages().send(userId=user_id, body=message).execute()


def fetch_drive_file(drive_service, file_id: str) -> Tuple[bytes, str, str]:
    meta = drive_service.files().get(fileId=file_id, fields="name,mimeType").execute()
    filename = meta.get("name", "resume.pdf")
    mime_type = meta.get("mimeType", "application/pdf")
    request = drive_service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue(), filename, mime_type


def find_drive_file_by_name(
    drive_service,
    filename: str,
    folder_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not filename:
        return None, None, None
    safe_name = filename.replace("'", "\\'")
    query_parts = [f"name = '{safe_name}'", "trashed = false"]
    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")
    query = " and ".join(query_parts)
    try:
        response = drive_service.files().list(
            q=query,
            spaces="drive",
            orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,modifiedTime)",
            pageSize=10,
        ).execute()
        files = response.get("files", [])
        if not files:
            return None, None, None
        entry = files[0]
        return entry.get("id"), entry.get("name"), entry.get("mimeType")
    except Exception:
        return None, None, None


def _lookup_by_name_or_id(config: AppConfig, drive_service, file_id: Optional[str]) -> Optional[Dict[str, object]]:
    folder_id = config.resume.folder_id

    if file_id and file_id.lower().startswith("name:") and drive_service is not None:
        desired_name = file_id.split(":", 1)[1].strip()
        match_id, match_name, match_mime = find_drive_file_by_name(drive_service, desired_name, folder_id=folder_id)
        if match_id:
            data, name, mime = fetch_drive_file(drive_service, match_id)
            return {"bytes": data, "filename": name, "mimeType": mime}
        file_id = None

    if file_id and drive_service is not None:
        data, name, mime = fetch_drive_file(drive_service, file_id)
        return {"bytes": data, "filename": name, "mimeType": mime}

    if config.resume.default_name and drive_service is not None:
        match_id, match_name, match_mime = find_drive_file_by_name(
            drive_service, config.resume.default_name, folder_id=folder_id
        )
        if match_id:
            data, name, mime = fetch_drive_file(drive_service, match_id)
            return {"bytes": data, "filename": name, "mimeType": mime}

    if config.resume.default_id and drive_service is not None:
        try:
            data, name, mime = fetch_drive_file(drive_service, config.resume.default_id)
            return {"bytes": data, "filename": name, "mimeType": mime}
        except Exception as exc:  # pragma: no cover - external API failures
            log_utils.log_warn(f"Failed to fetch default resume by ID '{config.resume.default_id}': {exc}")

    local_path = config.resume.local_path
    if local_path.exists():
        with local_path.open("rb") as handle:
            data = handle.read()
        return {"bytes": data, "filename": local_path.name, "mimeType": "application/pdf"}

    return None


def get_resume_attachment(config: AppConfig, drive_service, resume_flag: str | None) -> Optional[Dict[str, object]]:
    flag = (resume_flag or "").strip().lower()
    file_id = config.resume.resume_map.get(flag) if flag else None
    return _lookup_by_name_or_id(config, drive_service, file_id)