import base64, json, os, time, io
import pandas as pd
from jinja2 import Template
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import requests
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]
CONTACTS_CSV = 'leads.csv'
SENT_LOG = 'sent_log.json'
TEMPLATES = {
    'cold': 'template_cold.txt',
    'warm': 'template_warm.txt',
    'coffee': 'template_coffee.txt',
    'direct': 'template_direct.txt',
}
DAILY_LIMIT = int(os.getenv('DAILY_LIMIT', '0'))
DRY_RUN = (os.getenv('DRY_RUN', 'false').strip().lower() in ('1','true','yes','y'))

# LLM configuration (supports OpenAI, Azure OpenAI, or GitHub Models)
USE_LLM = (os.getenv('USE_LLM', 'true').strip().lower() in ('1','true','yes','y'))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()  # openai|azure|github
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# OpenAI (api.openai.com)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Azure OpenAI
# Required envs when LLM_PROVIDER=azure:
#   AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
#   AZURE_OPENAI_API_KEY=...
#   AZURE_OPENAI_API_VERSION=2024-02-15-preview (or later)
#   AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# GitHub Models (models.github.ai)
# Required envs when LLM_PROVIDER=github:
#   GITHUB_TOKEN=ghp_...
# Optionally override base url or model via envs.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_MODELS_ENDPOINT = os.getenv("GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference")

def get_llm_client_and_model():
    """Return (client, model_name) for the selected provider using OpenAI SDK."""
    provider = LLM_PROVIDER
    if provider == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set; cannot use OpenAI provider")
        client = OpenAI(api_key=OPENAI_API_KEY)
        model_name = LLM_MODEL
        return client, model_name
    elif provider == "azure":
        # Azure OpenAI uses deployments as model name and requires api-version.
        if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
            raise RuntimeError("AZURE provider requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT")
        client = OpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            # Point base_url at the deployments path
            base_url=f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}",
        )
        # For Azure, 'model' is the deployment name; api-version will be added at call time
        model_name = AZURE_OPENAI_DEPLOYMENT
        return client, model_name
    elif provider == "github":
        if not GITHUB_TOKEN:
            raise RuntimeError("GITHUB_TOKEN not set; cannot use GitHub Models provider")
        client = OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=GITHUB_TOKEN)
        # Example model: "openai/gpt-4o-mini"
        model_name = os.getenv("GITHUB_MODEL", LLM_MODEL if "/" in LLM_MODEL else f"openai/{LLM_MODEL}")
        return client, model_name
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")

# Optional resume attachment (can be overridden via env)
RESUME_PATH = os.getenv('RESUME_PATH', "Ashutosh_Choudhari_Resume.pdf")

def get_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # type: ignore
            except Exception:
                pass
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def get_drive_service():
    # Reuse token.json with drive.readonly scope
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # type: ignore
            except Exception:
                pass
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def get_sheets_service():
    # Use same token.json with spreadsheets.readonly
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # type: ignore
            except Exception:
                pass
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('sheets', 'v4', credentials=creds)

def _normalize_col(name: str) -> str:
    return name.strip().lower().replace(' ', '_').replace('-', '_')

def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_col(c) for c in df.columns]
    # Common synonyms
    if 'personalized_note' not in df.columns and 'personalizednote' in df.columns:
        df['personalized_note'] = df['personalizednote']
    # Handle common typo variant from sheet: 'personalized_no' -> 'personalized_note'
    if 'personalized_note' not in df.columns and 'personalized_no' in df.columns:
        df['personalized_note'] = df['personalized_no']
    if 'resume_flag' not in df.columns and 'resume' in df.columns:
        df['resume_flag'] = df['resume']
    # Job metadata synonyms
    if 'job_id' not in df.columns and 'jobid' in df.columns:
        df['job_id'] = df['jobid']
    if 'job_link' not in df.columns and 'job_url' in df.columns:
        df['job_link'] = df['job_url']
    if 'job_link' not in df.columns and 'joburl' in df.columns:
        df['job_link'] = df['joburl']
    # Treat 'email_sent' as a status column alias
    if 'status' not in df.columns and 'email_sent' in df.columns:
        df['status'] = df['email_sent']
    return df

def load_contacts_df() -> pd.DataFrame:
    """Load contacts from Google Sheets if configured; otherwise from CSV."""
    spreadsheet_id = os.getenv('SHEETS_SPREADSHEET_ID', '').strip()
    if spreadsheet_id:
        rng = os.getenv('SHEETS_RANGE', 'Contacts!A:F')
        has_header = os.getenv('SHEETS_HAS_HEADER', 'true').strip().lower() in ('1','true','yes','y')
        sheets = get_sheets_service()
        resp = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
        values = resp.get('values', [])
        if not values:
            return pd.DataFrame(columns=['name','email','company','role','personalized_note','template','resume_flag'])
        if has_header:
            headers = values[0]
            rows = values[1:]
        else:
            # Fallback default headers if no header row
            headers = ['name','email','company','role','personalized_note','template','resume']
            rows = values
        # pad rows to headers length
        norm_headers = [_normalize_col(h) for h in headers]
        records = []
        for idx, r in enumerate(rows):
            row = {}
            for i, h in enumerate(norm_headers):
                row[h] = r[i] if i < len(r) else ''
            # keep track of the absolute sheet row number for write-back
            row['sheet_row'] = (2 + idx) if has_header else (1 + idx)
            records.append(row)
        df = pd.DataFrame.from_records(records).fillna('')
        df = _normalize_df_columns(df)
        return df
    # CSV path fallback (env override or contacts/leads auto-detect is handled earlier)
    df = pd.read_csv(CONTACTS_CSV).fillna('')
    df = _normalize_df_columns(df)
    return df

def _parse_sheet_name_from_range(rng: str) -> str | None:
    if '!' in rng:
        return rng.split('!', 1)[0] or None
    return None

def _get_sheet_headers(spreadsheet_id: str) -> list[str]:
    rng = os.getenv('SHEETS_RANGE', 'Contacts!A:F')
    sheets = get_sheets_service()
    # Always read the first row of the provided range as headers (even if user sets HAS_HEADER=false, we still use it for locating columns)
    header_range = rng
    res = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=header_range).execute()
    vals = res.get('values', [])
    if not vals:
        return []
    headers = vals[0]
    return [_normalize_col(h) for h in headers]

def _col_index_by_name(headers_norm: list[str], name: str) -> int | None:
    name = _normalize_col(name)
    try:
        return headers_norm.index(name)
    except ValueError:
        return None

def _num_to_col(n: int) -> str:
    # 0 -> A, 25 -> Z, 26 -> AA
    s = ""
    n0 = n
    while True:
        n, r = divmod(n, 26)
        s = chr(r + 65) + s
        if n == 0:
            break
        n -= 1
    return s

def mark_sheet_row_sent(spreadsheet_id: str, row_number: int, status_value: str = 'SENT'):
    if not spreadsheet_id or not row_number:
        return
    rng = os.getenv('SHEETS_RANGE', 'Contacts!A:F')
    sheet_name = _parse_sheet_name_from_range(rng)
    headers_norm = _get_sheet_headers(spreadsheet_id)
    if not headers_norm:
        return

    # Column selection: allow explicit overrides, else infer by header names
    status_col_override = os.getenv('SHEETS_STATUS_COLUMN', '').strip().upper() or None
    sent_at_col_override = os.getenv('SHEETS_SENT_AT_COLUMN', '').strip().upper() or None

    status_idx = _col_index_by_name(headers_norm, 'status')
    if status_idx is None:
        status_idx = _col_index_by_name(headers_norm, 'email_sent')
    sent_at_idx = _col_index_by_name(headers_norm, 'sent_at')

    status_col = status_col_override or (_num_to_col(status_idx) if status_idx is not None else None)
    sent_at_col = sent_at_col_override or (_num_to_col(sent_at_idx) if sent_at_idx is not None else None)

    if not status_col and not sent_at_col:
        # Nothing to write back
        return

    iso_ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    updates = []
    if status_col:
        a1 = f"{status_col}{row_number}"
        updates.append({"range": f"{sheet_name+'!' if sheet_name else ''}{a1}", "values": [[status_value]]})
    if sent_at_col:
        a1 = f"{sent_at_col}{row_number}"
        updates.append({"range": f"{sheet_name+'!' if sheet_name else ''}{a1}", "values": [[iso_ts]]})

    body = {"data": updates, "valueInputOption": "RAW"}
    sheets = get_sheets_service()
    sheets.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

def load_template(kind):
    path = TEMPLATES.get((kind or 'cold').lower(), TEMPLATES['cold'])
    with open(path, 'r', encoding='utf-8') as f:
        return Template(f.read())

def load_template_text(kind):
    """Load the raw text of a template for style inspiration (no Jinja rendering)."""
    path = TEMPLATES.get((kind or 'cold').lower(), TEMPLATES['cold'])
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def create_message_with_attachment(to, subject, body, attachment=None, attachment_path=None):
    # Multipart message with optional PDF attachment
    msg = MIMEMultipart()
    msg['To'] = to
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    if attachment and isinstance(attachment, dict) and attachment.get('bytes'):
        data = attachment['bytes']
        filename = attachment.get('filename', 'resume.pdf')
        mime = attachment.get('mimeType', 'application/pdf')
        subtype = 'pdf' if mime.endswith('/pdf') or mime == 'application/pdf' else 'octet-stream'
        part = MIMEApplication(data, _subtype=subtype)
        part.add_header('Content-Disposition', 'attachment', filename=filename)
        msg.attach(part)
    elif attachment_path and Path(attachment_path).exists():
        with open(attachment_path, 'rb') as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header('Content-Disposition', 'attachment', filename=Path(attachment_path).name)
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
    return {'raw': raw}

def send_message(service, user_id, message):
    return service.users().messages().send(userId=user_id, body=message).execute()

def load_sent_log():
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_sent_log(log):
    with open(SENT_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=2)

def already_sent(log, email, role, company):
    k = f'{email.lower()}::{role.lower()}::{company.lower()}'
    return k in log

def mark_sent(log, email, role, company, msg_id):
    k = f'{email.lower()}::{role.lower()}::{company.lower()}'
    log[k] = {'msg_id': msg_id, 'ts': int(time.time())}

def parse_resume_map():
    raw = os.getenv('RESUME_MAP', '').strip()
    mapping = {}
    if not raw:
        return mapping
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return {str(k).lower(): str(v) for k, v in obj.items()}
    except Exception:
        pass
    for pair in raw.split(','):
        if ':' in pair:
            k, v = pair.split(':', 1)
            mapping[k.strip().lower()] = v.strip()
    return mapping

def fetch_drive_file(drive_service, file_id):
    meta = drive_service.files().get(fileId=file_id, fields='name,mimeType').execute()
    filename = meta.get('name', 'resume.pdf')
    mimeType = meta.get('mimeType', 'application/pdf')
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return fh.getvalue(), filename, mimeType

def find_drive_file_by_name(drive_service, filename: str, folder_id: str | None = None):
    """Find the most recently modified Drive file by exact name, optionally within a folder.
    Returns (file_id, name, mimeType) or (None, None, None) if not found.
    """
    if not filename:
        return None, None, None
    # Escape single quotes for Drive query
    safe_name = filename.replace("'", "\\'")
    q_parts = [f"name = '{safe_name}'", "trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    q = " and ".join(q_parts)
    try:
        resp = drive_service.files().list(
            q=q,
            spaces='drive',
            orderBy='modifiedTime desc',
            fields='files(id,name,mimeType,modifiedTime)',
            pageSize=10,
        ).execute()
        files = resp.get('files', [])
        if not files:
            return None, None, None
        f = files[0]
        return f.get('id'), f.get('name'), f.get('mimeType')
    except Exception:
        return None, None, None

def get_resume_attachment(drive_service, resume_flag):
    mapping = parse_resume_map()
    file_id = None
    if resume_flag:
        file_id = mapping.get(str(resume_flag).lower())
    # Support mapping by name via prefix 'name:' (e.g., ds -> name:Ash_Resume_DS.pdf)
    resume_folder_id = os.getenv('RESUME_FOLDER_ID', '').strip() or None
    if file_id and isinstance(file_id, str) and file_id.lower().startswith('name:') and drive_service is not None:
        fname = file_id.split(':', 1)[1].strip()
        fid, name, mime = find_drive_file_by_name(drive_service, fname, folder_id=resume_folder_id)
        if fid:
            data, filename, mime = fetch_drive_file(drive_service, fid)
            return {'bytes': data, 'filename': filename, 'mimeType': mime}
        file_id = None  # fallback to defaults below if name not found
    if not file_id:
        # Default by ID or by name
        default_name = os.getenv('RESUME_DEFAULT_NAME', '').strip()
        if default_name and drive_service is not None:
            fid, name, mime = find_drive_file_by_name(drive_service, default_name, folder_id=resume_folder_id)
            if fid:
                data, filename, mime = fetch_drive_file(drive_service, fid)
                return {'bytes': data, 'filename': filename, 'mimeType': mime}
        file_id = os.getenv('RESUME_DEFAULT_ID')
    if file_id and drive_service is not None:
        data, filename, mime = fetch_drive_file(drive_service, file_id)
        return {'bytes': data, 'filename': filename, 'mimeType': mime}
    if RESUME_PATH and Path(RESUME_PATH).exists():
        with open(RESUME_PATH, 'rb') as f:
            data = f.read()
        return {'bytes': data, 'filename': Path(RESUME_PATH).name, 'mimeType': 'application/pdf'}
    return None

def generate_email_with_llm(row_dict, inspiration_kind: str | None = None, intent: str | None = None):
    """Generate subject and body using the selected provider via OpenAI SDK.
    If inspiration_kind is provided (e.g., 'cold' or 'warm'), the corresponding
    template text is included as a style guide for tone/structure only.
    """
    client, model_name = get_llm_client_and_model()

    name = row_dict.get('name', '')
    company = row_dict.get('company', '')
    role = row_dict.get('role', '')
    note = row_dict.get('personalized_note', '')
    job_link = row_dict.get('job_link', '')
    job_id = row_dict.get('job_id', '')

    style_text = None
    if inspiration_kind in ('cold', 'warm'):
        try:
            style_text = load_template_text(inspiration_kind)
        except Exception:
            style_text = None

    sys = (
        "You are an assistant that drafts short, respectful, high-signal referral request emails. "
        "Target length: 120–170 words. One clear ask. Professional and warm. "
        "Include a concise 'why me' line tailored to the company/role. Use the provided personalization if present. "
        "Write in plain text (no markdown). Return ONLY JSON with keys 'subject' and 'body'."
    )

    # Include template style inspiration if available (do not copy verbatim)
    style_block = ""
    if style_text:
        style_block = (
            "Style inspiration (do not copy verbatim; emulate tone, pacing, and structure):\n" +
            style_text +
            "\nNotes: Ignore any variable markers like {{...}} or Subject: lines in the sample; generate fresh content.\n"
        )

    # Encode intent for clearer guidance
    intent_line = ""
    if intent == 'coffee':
        intent_line = (
            "Email intent: Coffee chat — Avoid a direct referral ask; propose a brief 15–20 minute chat to learn about their experience. "
            "It's okay to subtly indicate interest in a referral if the conversation goes well.\n"
        )
    elif intent == 'direct':
        intent_line = (
            "Email intent: Direct referral — Be concise and polite; clearly ask for a referral and acknowledge their time. "
            "You may mention that a resume is attached.\n"
        )

    usr = f"""{style_block}{intent_line}
Recipient: {name}
Company: {company}
Role: {role}
Personalization: {note or '(none)'}
Job Link: {job_link or '(not provided)'}
Job ID: {job_id or '(not provided)'}
Candidate: Ashutosh Choudhari — DS/ML/AI engineer. Portfolio: https://4ashutosh98.github.io
Return JSON only."""

    # Azure requires api-version query parameter
    if LLM_PROVIDER == "azure":
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ],
            temperature=0.6,
            max_tokens=600,
            extra_query={"api-version": AZURE_OPENAI_API_VERSION},
        )
    else:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ],
            temperature=0.6,
            max_tokens=600,
        )

    content = resp.choices[0].message.content
    try:
        j = json.loads(content)
        return j.get("subject", "Referral request"), j.get("body", content)
    except Exception:
        # Fallback: first line as subject
        lines = content.splitlines()
        subject = lines[0].replace("Subject:", "").strip() if lines else "Referral request"
        body = "\n".join(lines[1:]).strip()
        return subject, body

def main():
    df = load_contacts_df()
    service = get_service()
    drive_service = get_drive_service()
    sent_log = load_sent_log()
    spreadsheet_id = os.getenv('SHEETS_SPREADSHEET_ID', '').strip()

    sent_count = 0
    for _, row in df.iterrows():
        name = row['name'].strip()
        email = row['email'].strip()
        company = row['company'].strip()
        role = row['role'].strip()
        note = row['personalized_note'].strip()
        job_link = (row.get('job_link') or '').strip()
        job_id = (row.get('job_id') or '').strip()
        template_kind = (row.get('template', 'cold') or 'cold').lower()
        sheet_row = int(row.get('sheet_row', 0) or 0)

        # If the sheet includes a status column, skip rows already marked as SENT
        raw_status = (row.get('status') or row.get('email_sent') or '').strip()
        status_val = raw_status.upper()
        # Consider various truthy forms as already sent
        if status_val in {'SENT', 'YES', 'TRUE', '1', 'DONE'}:
            print(f'SKIP (sheet marked SENT) -> {email} ({role} @ {company})')
            continue

        # Required field enforcement
        missing = []
        if not name: missing.append('name')
        if not email: missing.append('email')
        if not company: missing.append('company')
        if not role: missing.append('role')
        if not (row.get('template') or ''): missing.append('template')
        # 'resume' is required as a flag; allow either resume_flag or resume
        resume_flag_val = (row.get('resume_flag') or row.get('resume') or '').strip()
        if not resume_flag_val: missing.append('resume')
        if missing:
            print(f"REQUIRED FIELD MISSING {missing} -> {email or '(no email)'} ({role or '(no role)'} @ {company or '(no company)'})")
            # Write back 'required_field_missing' to status/email_sent
            if spreadsheet_id and sheet_row:
                try:
                    mark_sheet_row_sent(spreadsheet_id, sheet_row, status_value='required_field_missing')
                except Exception as e:
                    print(f'WARN: failed to mark sheet row {sheet_row} (missing fields): {e}')
            continue

        if already_sent(sent_log, email, role, company):
            print(f'SKIP already sent -> {email} ({role} @ {company})')
            continue

        # If DAILY_LIMIT<=0, treat as unlimited
        if DAILY_LIMIT > 0 and sent_count >= DAILY_LIMIT:
            print('Daily limit reached. Stopping.')
            break

        row_dict = row.to_dict()

        # LLM mode when template column is 'llm', else use Jinja template
        tval = (row_dict.get('template', '') or '').lower()
        if tval.startswith('llm') and USE_LLM:
            try:
                # Parse explicit style hint from template value, e.g., 'llm-coffee', 'llm-direct', 'llm-warm', 'llm-cold'
                explicit = tval.split('-', 1)[1] if '-' in tval else None
                if explicit in {'coffee', 'direct', 'warm', 'cold'}:
                    inspiration = explicit
                else:
                    inspiration = 'warm' if (note and note.strip()) else 'cold'
                intent = 'coffee' if inspiration == 'coffee' else ('direct' if inspiration == 'direct' else None)
                print(f"LLM mode -> provider={LLM_PROVIDER}, model={LLM_MODEL or os.getenv('GITHUB_MODEL','')}; style inspiration={inspiration}; intent={intent or 'auto'}")
                subject, body = generate_email_with_llm(row_dict, inspiration_kind=inspiration, intent=intent)
            except Exception as e:
                print(f"LLM error for {email}: {e} -> falling back to template '{template_kind}'")
                tpl = load_template(template_kind)
                rendered = tpl.render(name=name, company=company, role=role, personalized_note=note, job_link=job_link, job_id=job_id)
                lines = rendered.splitlines()
                if lines and lines[0].lower().startswith('subject:'):
                    subject = lines[0].split(':', 1)[1].strip()
                    body = '\n'.join(lines[1:]).lstrip()
                else:
                    subject = 'Hello'
                    body = rendered
        else:
            # Map new template types
            tk = template_kind
            if tk not in {'cold','warm','coffee','direct'}:
                tk = 'cold'
            tpl = load_template(tk)
            rendered = tpl.render(name=name, company=company, role=role, personalized_note=note, job_link=job_link, job_id=job_id)
            # Extract subject from first line, rest is body
            lines = rendered.splitlines()
            if lines and lines[0].lower().startswith('subject:'):
                subject = lines[0].split(':', 1)[1].strip()
                body = '\n'.join(lines[1:]).lstrip()
            else:
                subject = 'Hello'
                body = rendered

        resume_flag = (row.get('resume_flag') or row.get('resume') or '').strip().lower()
        attachment = None
        try:
            attachment = get_resume_attachment(drive_service, resume_flag)
        except Exception as e:
            print(f'WARN: Failed to fetch resume for flag "{resume_flag}": {e}')

        if DRY_RUN:
            att_info = f"yes ({attachment.get('filename')})" if attachment else (f"yes ({Path(RESUME_PATH).name})" if Path(RESUME_PATH).exists() else 'no')
            print(f'-- DRY RUN -- To: {email}\nSubject: {subject}\n{body}\n(attached: {att_info})\n---')
            mark_sent(sent_log, email, role, company, 'DRY_RUN')
            if spreadsheet_id and sheet_row:
                try:
                    mark_sheet_row_sent(spreadsheet_id, sheet_row, status_value='DRY_RUN')
                except Exception as e:
                    print(f'WARN: failed to mark sheet row {sheet_row} (dry run): {e}')
            continue

        try:
            message = create_message_with_attachment(email, subject, body, attachment=attachment, attachment_path=None)
            resp = send_message(service, 'me', message)
            msg_id = resp.get('id', 'UNKNOWN')
            mark_sent(sent_log, email, role, company, msg_id)
            sent_count += 1
            print(f'SENT -> {email} (id={msg_id})')
            save_sent_log(sent_log)
            if spreadsheet_id and sheet_row:
                try:
                    mark_sheet_row_sent(spreadsheet_id, sheet_row, status_value='SENT')
                except Exception as e:
                    print(f'WARN: failed to mark sheet row {sheet_row}: {e}')
            time.sleep(1.5)  # gentle pace
        except Exception as e:
            print(f'ERROR sending to {email}: {e}')

    save_sent_log(sent_log)
    print(f'Done. Sent {sent_count}.')

if __name__ == '__main__':
    main()