from __future__ import annotations

import pandas as pd

from .config import AppConfig
from . import google_clients, log_utils


def _normalize_col(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data.columns = [_normalize_col(c) for c in data.columns]

    if "personalized_note" not in data.columns and "personalizednote" in data.columns:
        data["personalized_note"] = data["personalizednote"]
    if "personalized_note" not in data.columns and "personalized_no" in data.columns:
        data["personalized_note"] = data["personalized_no"]
    if "resume_flag" not in data.columns and "resume" in data.columns:
        data["resume_flag"] = data["resume"]
    if "job_id" not in data.columns and "jobid" in data.columns:
        data["job_id"] = data["jobid"]
    if "job_link" not in data.columns and "job_url" in data.columns:
        data["job_link"] = data["job_url"]
    if "job_link" not in data.columns and "joburl" in data.columns:
        data["job_link"] = data["joburl"]
    if "status" not in data.columns and "email_sent" in data.columns:
        data["status"] = data["email_sent"]
    return data


def load_contacts_df(config: AppConfig) -> pd.DataFrame:
    spreadsheet_id = config.sheets.spreadsheet_id
    if spreadsheet_id:
        sheets_service = google_clients.get_sheets_service(config)
        if sheets_service is None:
            raise RuntimeError("Unable to load Google Sheets data: Sheets service unavailable.")
        return _load_from_sheet(config, sheets_service)

    df = pd.read_csv(config.contacts_csv).fillna("")
    return _normalize_df_columns(df)


def _load_from_sheet(config: AppConfig, sheets_service) -> pd.DataFrame:
    rng = config.sheets.sheet_range
    has_header = config.sheets.has_header
    response = sheets_service.spreadsheets().values().get(spreadsheetId=config.sheets.spreadsheet_id, range=rng).execute()
    values = response.get("values", [])
    if not values:
        return pd.DataFrame(columns=["name", "email", "company", "role", "personalized_note", "template", "resume_flag"])

    if has_header:
        headers = values[0]
        rows = values[1:]
    else:
        headers = ["name", "email", "company", "role", "personalized_note", "template", "resume"]
        rows = values

    norm_headers = [_normalize_col(h) for h in headers]
    records = []
    for idx, row in enumerate(rows):
        entry = {}
        for pos, header in enumerate(norm_headers):
            entry[header] = row[pos] if pos < len(row) else ""
        entry["sheet_row"] = (2 + idx) if has_header else (1 + idx)
        records.append(entry)

    df = pd.DataFrame.from_records(records).fillna("")
    return _normalize_df_columns(df)


def _parse_sheet_name(rng: str) -> str | None:
    if "!" in rng:
        return rng.split("!", 1)[0] or None
    return None


def _get_sheet_headers(config: AppConfig, sheets_service) -> list[str]:
    rng = config.sheets.sheet_range
    result = sheets_service.spreadsheets().values().get(spreadsheetId=config.sheets.spreadsheet_id, range=rng).execute()
    values = result.get("values", [])
    if not values:
        return []
    headers = values[0]
    return [_normalize_col(h) for h in headers]


def _col_index_by_name(headers: list[str], name: str) -> int | None:
    name = _normalize_col(name)
    try:
        return headers.index(name)
    except ValueError:
        return None


def _num_to_col(num: int) -> str:
    out = ""
    n = num
    while True:
        n, rem = divmod(n, 26)
        out = chr(rem + 65) + out
        if n == 0:
            break
        n -= 1
    return out


def _col_to_num(col: str) -> int:
    col = (col or "").strip().upper()
    if not col:
        return 0
    num = 0
    for ch in col:
        if "A" <= ch <= "Z":
            num = num * 26 + (ord(ch) - 64)
    return max(0, num - 1)


def _a1_start_col_index(rng: str) -> int:
    target = rng.split("!", 1)[1] if "!" in rng else rng
    start = target.split(":", 1)[0]
    letters = "".join(ch for ch in start if ch.isalpha())
    if not letters:
        return 0
    return _col_to_num(letters)


def mark_sheet_row_sent(config: AppConfig, sheets_service, row_number: int, status_value: str = "SENT") -> None:
    if not config.sheets.spreadsheet_id or not row_number:
        return

    headers = _get_sheet_headers(config, sheets_service)
    if not headers:
        return

    status_override = config.sheets.status_column
    sent_at_override = config.sheets.sent_at_column

    status_idx = _col_index_by_name(headers, "status")
    if status_idx is None:
        status_idx = _col_index_by_name(headers, "email_sent")
    sent_at_idx = _col_index_by_name(headers, "sent_at")

    offset = _a1_start_col_index(config.sheets.sheet_range)

    status_col = status_override or (_num_to_col(offset + status_idx) if status_idx is not None else None)
    sent_at_col = sent_at_override or (_num_to_col(offset + sent_at_idx) if sent_at_idx is not None else None)

    if not status_col and not sent_at_col:
        return

    iso_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    sheet_name = _parse_sheet_name(config.sheets.sheet_range)

    updates = []
    if status_col:
        ref = f"{status_col}{row_number}"
        updates.append({
            "range": f"{sheet_name + '!' if sheet_name else ''}{ref}",
            "values": [[status_value]],
        })
    if sent_at_col:
        ref = f"{sent_at_col}{row_number}"
        updates.append({
            "range": f"{sheet_name + '!' if sheet_name else ''}{ref}",
            "values": [[iso_ts]],
        })

    body = {"data": updates, "valueInputOption": "RAW"}
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=config.sheets.spreadsheet_id,
        body=body,
    ).execute()


def ensure_status_column(config: AppConfig, sheets_service) -> bool:
    if not config.sheets.spreadsheet_id:
        return True

    headers = _get_sheet_headers(config, sheets_service)
    if not headers:
        return False

    status_idx = _col_index_by_name(headers, "status")
    if status_idx is None:
        status_idx = _col_index_by_name(headers, "email_sent")

    if status_idx is None and not config.sheets.status_column:
        log_utils.log_error(
            "No 'status' or 'email_sent' column found in the first row of the configured SHEETS_RANGE. "
            "Update the range to include a status column and try again."
        )
        return False
    return True
