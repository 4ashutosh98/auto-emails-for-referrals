# Auto Emails for Referrals

Send tailored referral emails at scale using Google Sheets (or CSV), Gmail, Drive (for resumes), and an optional LLM to draft high-quality messages.

This repo includes:
- A Python mailer (`main.py`) with Google APIs and an LLM abstraction (GitHub Models, OpenAI, or Azure OpenAI)
- Jinja templates for cold, warm, coffee chat, and direct referral styles
- A robust Google Sheets workflow with write-back status and timestamps
- GitHub Actions automation (scheduled every 4 hours) and a failure tracker

---

## What you’ll need

- Python 3.11+
- A Google account with Gmail, Google Drive, and Sheets access
- A Google Cloud project with OAuth credentials (Desktop app) and APIs enabled:
   - Gmail API
   - Google Drive API
   - Google Sheets API
- One LLM provider (optional but recommended):
   - GitHub Models (Copilot) with a PAT
   - OR OpenAI API key
   - OR Azure OpenAI endpoint, key, and deployment
- Optionally: a Google Sheet to store contacts and track status (CSV fallback works too)

---

## Setup (Local)

1) Clone and install

```bash
git clone <this-repo-url>
cd auto-emails-for-referrals
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

2) Configure environment

```bash
cp .env.example .env
# Open .env and fill in values; see sections below for details.
```

Key env groups used by `main.py`:
- Core flags: `DRY_RUN`, `VERBOSE`, `USE_LLM`, `DAILY_LIMIT`, `USE_SENT_LOG`
- LLM provider: `LLM_PROVIDER` (github|openai|azure), `LLM_MODEL`
- GitHub Models: `LLM_GITHUB_TOKEN`, `LLM_GITHUB_MODEL`, `LLM_GITHUB_MODELS_ENDPOINT`
- OpenAI: `OPENAI_API_KEY`
- Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`
- Google Sheets: `SHEETS_SPREADSHEET_ID`, `SHEETS_RANGE`, `SHEETS_HAS_HEADER`, `SHEETS_STATUS_COLUMN`, `SHEETS_SENT_AT_COLUMN`
- Resume mapping: `RESUME_MAP`, `RESUME_FOLDER_ID`, `RESUME_DEFAULT_NAME`, `RESUME_DEFAULT_ID`, `RESUME_PATH`
- Alerts: `ALERT_EMAIL`, `ALERT_ON` (error|always|never), `ALERT_SUBJECT_PREFIX`
- Debug/Precheck: `GOOGLE_REFRESH_DEBUG`, `PRECHECK`

3) Add Google OAuth files

Create a Google Cloud project and enable:
- Gmail API
- Google Drive API
- Google Sheets API

Then create OAuth 2.0 credentials:
- Type: Desktop app
- Download as `credentials.json`
- Place `credentials.json` in the repo root (same folder as `main.py`)

First run will create `token.json` after you approve consent.

4) First run (OAuth consent)

```bash
export DRY_RUN=true
python main.py
```

Your browser will open for Google consent. Approve requested scopes. On success, `token.json` is created.

5) Preflight check (optional but recommended)

Before sending, validate your credentials and scopes:

```bash
python main.py --precheck
```

This checks that `credentials.json` and `token.json` exist, scopes are present, and Gmail profile is reachable.

6) Send a test

```bash
unset DRY_RUN
python main.py
```

---

## Data sources: Google Sheets (recommended) or CSV

By default, the app reads from Google Sheets when `SHEETS_SPREADSHEET_ID` is set; otherwise it falls back to `leads.csv`.

### Google Sheets

Set in `.env`:
- `SHEETS_SPREADSHEET_ID`: the Sheet ID (from the URL)
- `SHEETS_RANGE`: A1 range including the header row (e.g., `Contacts!A:J`)
- `SHEETS_HAS_HEADER=true`

Headers (case/spacing is normalized) should include:
- Required: `name`, `email`, `company`, `role`, `template`, `resume` or `resume_flag`
- Optional: `personalized_note`, `job_link`, `job_id`
- Status tracking: one of `status` or `email_sent` MUST be present in the first row of the provided range

Important:
- The code writes back status and timestamp into the same sheet/range. If your range doesn’t start at column A, it auto-offsets or you can override columns with `SHEETS_STATUS_COLUMN` and `SHEETS_SENT_AT_COLUMN` (e.g., `H`).
- When a row is sent, `status` is set to `SENT` and `sent_at` is filled (if present). For dry runs, status is `DRY_RUN`.
- Missing required fields are marked `required_field_missing`. Fix the row later and it will be revalidated and processed.
- Rows already marked as `SENT`, `YES`, `TRUE`, `1`, or `DONE` are skipped.

Synonyms handled automatically:
- `personalized_no` → `personalized_note`
- `personalizednote` → `personalized_note`
- `resume` → `resume_flag`
- `joburl`/`job_url` → `job_link`
- `email_sent` can act as the `status` column

### CSV fallback

If `SHEETS_SPREADSHEET_ID` is empty, the app reads `leads.csv`.
Expected columns are the same as the Sheets headers above.

An example starter CSV is included (`leads.csv`).

---

## Templates and LLM drafting

You can choose between static Jinja templates or LLM-generated emails.

Template files:
- `template_cold.txt`
- `template_warm.txt`
- `template_coffee.txt`
- `template_direct.txt`

In your data source, set the `template` column to one of:
- `cold`, `warm`, `coffee`, or `direct` → uses the corresponding template
- `llm` → LLM drafts the email; it will heuristically use `warm` style if there’s a `personalized_note`, else `cold`
- `llm-warm` / `llm-cold` / `llm-coffee` / `llm-direct` → LLM drafts with that style inspiration and intent

LLM output contract:
- The assistant is instructed to return JSON with keys: `subject` and `body`
- If parsing fails, the first line is treated as subject and the rest as body

### Choosing an LLM provider

Set `LLM_PROVIDER` to `github`, `openai`, or `azure`.

GitHub Models (default):
- Set `LLM_GITHUB_TOKEN` to a PAT from the account with Copilot access
- Default endpoint: `LLM_GITHUB_MODELS_ENDPOINT=https://models.github.ai/inference`
- Model name: `LLM_GITHUB_MODEL=openai/gpt-4o-mini` is a good start

OpenAI:
- Set `OPENAI_API_KEY`
- Set `LLM_MODEL` (e.g., `gpt-4o-mini`)

Azure OpenAI:
- Set `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`
- Optional `AZURE_OPENAI_API_VERSION` (default: `2024-02-15-preview`)

---

## Resume attachments (Google Drive)

Attach a PDF resume based on the `resume_flag` column in your data.

Options (can be combined):
- Map flags to Drive file IDs with `RESUME_MAP` (JSON or `flag:fileId` pairs)
- Use names instead of IDs by prefixing with `name:`; e.g., `ai:name:Ashutosh Choudhari Resume for AI.pdf`
- Constrain searches to a folder with `RESUME_FOLDER_ID`
- Provide a default by name `RESUME_DEFAULT_NAME` or by ID `RESUME_DEFAULT_ID`
- As a final fallback, the local file `RESUME_PATH` (default: `Ashutosh_Choudhari_Resume.pdf`) is used if present

---

## Alerts and observability

Set an alert email to receive a run summary and the captured log as an attachment:
- `ALERT_EMAIL=you@example.com`
- `ALERT_ON=error|always|never` (default: `error`)
- `ALERT_SUBJECT_PREFIX` (default: `[Referrals Bot]`)

Additional logs:
- Set `VERBOSE=true` for more console output
- `GOOGLE_REFRESH_DEBUG=true` adds detailed token refresh logs

---

## Safety, deduplication, and limits

- The Google Sheet status column is the source of truth. Already sent rows are skipped.
- Local `sent_log.json` can be enabled with `USE_SENT_LOG=true` (name+role+company key; avoids storing emails).
- Limit daily sends with `DAILY_LIMIT` (0 = unlimited).

Sensitive files are ignored by `.gitignore`: `.env`, `credentials.json`, `token.json`, `sent_log.json`.

---

## Automation with GitHub Actions (optional)

This repo includes two workflows under `.github/workflows/`:

1) `send-emails.yml` — runs every 4 hours and on manual dispatch.
    - Required repository secrets: `GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`
    - Provider secrets (choose one):
       - GitHub Models: `LLM_GITHUB_TOKEN`
       - OpenAI: `OPENAI_API_KEY`
       - Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`
    - Repository variables (`Settings > Variables`) you may set:
       - `VERBOSE`, `DRY_RUN`, `USE_LLM`, `DAILY_LIMIT`
       - `SHEETS_SPREADSHEET_ID`, `SHEETS_RANGE`, `SHEETS_HAS_HEADER`, `SHEETS_STATUS_COLUMN`, `SHEETS_SENT_AT_COLUMN`
       - `RESUME_MAP`, `RESUME_DEFAULT_NAME`, `RESUME_FOLDER_ID`
       - `LLM_PROVIDER`, `LLM_MODEL`, `LLM_GITHUB_MODELS_ENDPOINT`
       - `AZURE_OPENAI_API_VERSION` (if using Azure)
    - The job restores `credentials.json` and `token.json` from secrets and runs `python main.py`.
    - On verbose or failure, logs are uploaded as an artifact named `mailer-logs`.

2) `notify-failure.yml` — creates/updates a single tracker issue when the mailer fails.
    - Adds log snippets, tracks a failure streak, and auto-closes when the next run succeeds.

Notes:
- Never prefix your own repo variables with `GITHUB_` (reserved in Actions).
- In CI, interactive OAuth isn’t possible; you must provide a valid `token.json` via the secret `GOOGLE_TOKEN_JSON`.

Optional: You can create a separate nightly precheck workflow that runs `python main.py --precheck` to catch credential expiry early.

---

## Troubleshooting

Common issues and fixes:

- Missing status column: Error indicates no `status` or `email_sent` header in your `SHEETS_RANGE`. Ensure the first row of the selected range contains one of those headers.
- OAuth in CI: If the workflow fails with a message about `token.json` in CI, regenerate it locally (with Gmail, Drive, Sheets scopes) and paste its full JSON into the `GOOGLE_TOKEN_JSON` secret.
- Gmail send 403/Insufficient permissions: Ensure the Gmail API is enabled and the token/scopes include `gmail.send`.
- Drive/Sheets 403: Ensure the APIs are enabled and the same Google account has access to the spreadsheet and resume files.
- LLM provider errors: The app falls back to a static template if LLM calls fail. Check tokens, endpoints, and model names.
- Daily limit reached: Increase `DAILY_LIMIT` or wait until the next day.
- Re-queue logic: Rows marked `required_field_missing` will be retried once you fix the missing fields.

---

## Reference: environment variables

Core
- `DRY_RUN` (false|true), `VERBOSE` (false|true), `USE_LLM` (true|false), `DAILY_LIMIT` (0 for unlimited), `USE_SENT_LOG` (false|true)

LLM
- `LLM_PROVIDER` (github|openai|azure), `LLM_MODEL`
- GitHub: `LLM_GITHUB_TOKEN`, `LLM_GITHUB_MODEL`, `LLM_GITHUB_MODELS_ENDPOINT`
- OpenAI: `OPENAI_API_KEY`
- Azure: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`

Google Sheets
- `SHEETS_SPREADSHEET_ID`, `SHEETS_RANGE`, `SHEETS_HAS_HEADER`
- `SHEETS_STATUS_COLUMN`, `SHEETS_SENT_AT_COLUMN` (optional overrides)

Resumes
- `RESUME_MAP`, `RESUME_FOLDER_ID`, `RESUME_DEFAULT_NAME`, `RESUME_DEFAULT_ID`, `RESUME_PATH`

Alerts & debug
- `ALERT_EMAIL`, `ALERT_ON`, `ALERT_SUBJECT_PREFIX`
- `GOOGLE_REFRESH_DEBUG` (false|true), `PRECHECK` (false|true)

---

## Example flows

Dry-run on your sheet to verify statuses and attachments without sending:

```bash
export DRY_RUN=true VERBOSE=true
python main.py
```

Live run with a daily limit of 5:

```bash
export DRY_RUN=false DAILY_LIMIT=5
python main.py
```

Preflight only (no sends):

```bash
python main.py --precheck
```

---

## Security

- Don’t commit secrets. `.env`, `credentials.json`, `token.json`, and `sent_log.json` are ignored by `.gitignore`.
- In GitHub Actions, use Secrets for tokens/keys and Variables for non-sensitive settings.
- Avoid using the `GITHUB_` prefix for custom repo variables (reserved by Actions).

---

## How it works (high-level)

1) Load env and data (Sheets or CSV), normalize headers.
2) Enforce required fields and skip already-sent rows based on the sheet status.
3) Render email with either a Jinja template or an LLM (with optional style inspiration and intent).
4) Attach a resume selected via Drive ID/name mapping or local fallback.
5) Send via Gmail API, write back `SENT` (and `sent_at`) to the Sheet, and optionally update `sent_log.json`.
6) On completion, optionally email a run summary to `ALERT_EMAIL` with the full run log attached.

That’s it—happy (and considerate) outreach!
