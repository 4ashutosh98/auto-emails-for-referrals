# Auto Emails for Referrals

## Quick Start (GitHub Models / Copilot Pro)

1. Copy `.env.example` to `.env` and edit:
   - Set `LLM_PROVIDER=github`
   - Paste your GitHub Personal Access Token in `LLM_GITHUB_TOKEN=` (from the account with Copilot Pro)
   - Keep `LLM_GITHUB_MODEL=openai/gpt-4o-mini` (recommended) or choose another supported model

2. Install deps:
```bash
pip install -r requirements.txt
```

3. First run (OAuth):
```bash
export DRY_RUN=true
python main.py
```
- Approve Google consent (Gmail send, Sheets, Drive). This creates `token.json`.

4. Send a test (to yourself):
```bash
unset DRY_RUN
python main.py
```

## GitHub PAT for Models
- Create a PAT: GitHub → Settings → Developer settings → Personal access tokens (classic or fine-grained)
- Store it in your local `.env` as `LLM_GITHUB_TOKEN=...` (do not commit `.env`).
- Default endpoint is `https://models.github.ai/inference`.

## Inputs
- Google Sheet (recommended): set `SHEETS_SPREADSHEET_ID`, `SHEETS_RANGE`, `SHEETS_HAS_HEADER` in `.env`.
- CSV fallback: `leads.csv` used when `SHEETS_SPREADSHEET_ID` is not set.

## Attachments
- Map a `resume_flag` column to Drive file IDs via `RESUME_MAP` (JSON or `a:ID1,b:ID2`) and optional `RESUME_DEFAULT_ID`.

## Safety
- `.gitignore` already ignores sensitive files: `.env`, `credentials.json`, `token.json`, `sent_log.json`.

## Logs
- Local: stdout shows progress; `sent_log.json` records sent entries.
- GitHub Actions: logs in the job output; artifact `mailer.log` + `sent_log.json` uploaded each run.
