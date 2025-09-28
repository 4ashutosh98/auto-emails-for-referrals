from __future__ import annotations

import sys
import time
from typing import Optional

from .alerts import send_alert_email
from .config import AppConfig, CONFIG
from . import data_sources, emailer, google_clients, llm, log_utils, storage, templates


def run_precheck(config: AppConfig = CONFIG) -> bool:
    log_utils.reset()
    try:
        google_clients.preflight_validate_credentials(config)
        print("Pre-flight credentials validation OK.")
        return True
    except google_clients.CredentialError as exc:
        print(f"Pre-flight credentials validation FAILED: {exc}")
        return False


def execute_mailer(config: AppConfig = CONFIG) -> None:
    log_utils.reset()

    try:
        contacts_df = data_sources.load_contacts_df(config)
    except Exception as exc:
        log_utils.log_error(f"Failed to load contacts: {exc}")
        send_alert_email(service=None, config=config, subject_suffix="contacts load failure")
        return

    gmail_service = google_clients.get_gmail_service(config)
    if gmail_service is None:
        log_utils.log_error("Unable to initialise Gmail service; aborting run.")
        send_alert_email(service=None, config=config, subject_suffix="gmail service failure")
        return

    drive_service = google_clients.get_drive_service(config)
    sheets_service = google_clients.get_sheets_service(config) if config.sheets.spreadsheet_id else None

    if config.sheets.spreadsheet_id and sheets_service is not None:
        if not data_sources.ensure_status_column(config, sheets_service):
            send_alert_email(gmail_service, config, subject_suffix="missing status column")
            return

    sent_log = storage.load_sent_log() if config.use_sent_log else {}
    spreadsheet_id = config.sheets.spreadsheet_id

    sent_count = 0

    def describe_contact() -> str:
        safe_name = name or "(no name)"
        safe_role = role or "(no role)"
        safe_company = company or "(no company)"
        return f"{safe_name} ({safe_role} @ {safe_company})"

    for _, row in contacts_df.iterrows():
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()
        company = (row.get("company") or "").strip()
        role = (row.get("role") or "").strip()
        note = (row.get("personalized_note") or "").strip()
        job_link = (row.get("job_link") or "").strip()
        job_id = (row.get("job_id") or "").strip()
        template_kind = (row.get("template", "cold") or "cold").lower()
        sheet_row = int(row.get("sheet_row", 0) or 0)

        raw_status = (row.get("status") or row.get("email_sent") or "").strip()
        status_val = raw_status.upper()
        contact_label = describe_contact()

        if status_val in {"SENT", "YES", "TRUE", "1", "DONE"}:
            log_utils.log_info(
                f"SKIP (sheet marked SENT) -> {contact_label}",
                verbose=config.verbose,
            )
            continue
        if status_val == "REQUIRED_FIELD_MISSING":
            log_utils.log_info(
                f"Revalidating previously incomplete row -> {contact_label}",
                verbose=config.verbose,
            )

        missing_fields = []
        if not name:
            missing_fields.append("name")
        if not email:
            missing_fields.append("email")
        if not company:
            missing_fields.append("company")
        if not role:
            missing_fields.append("role")
        if not (row.get("template") or ""):
            missing_fields.append("template")
        resume_flag_value = (row.get("resume_flag") or row.get("resume") or "").strip()
        if not resume_flag_value:
            missing_fields.append("resume")

        if missing_fields:
            log_utils.log_info(
                f"REQUIRED FIELD MISSING {missing_fields} -> {contact_label}",
                verbose=config.verbose,
            )
            if spreadsheet_id and sheet_row and sheets_service is not None:
                try:
                    data_sources.mark_sheet_row_sent(config, sheets_service, sheet_row, status_value="required_field_missing")
                except Exception as exc:
                    log_utils.log_error(f"Failed to mark sheet row {sheet_row} (missing fields): {exc}")
            continue
        else:
            if status_val == "REQUIRED_FIELD_MISSING" and spreadsheet_id and sheet_row and sheets_service is not None:
                try:
                    data_sources.mark_sheet_row_sent(config, sheets_service, sheet_row, status_value="")
                except Exception as exc:
                    log_utils.log_error(f"Failed to clear status for sheet row {sheet_row}: {exc}")

        if config.use_sent_log and storage.already_sent(sent_log, name, email, role, company):
            log_utils.log_info(f"SKIP already sent -> {contact_label}", verbose=config.verbose)
            continue

        if config.daily_limit > 0 and sent_count >= config.daily_limit:
            log_utils.log_info("Daily limit reached. Stopping.", verbose=config.verbose)
            break

        row_dict = row.to_dict()

        subject: str
        body: str

        template_value = (row_dict.get("template", "") or "").lower()
        if template_value.startswith("llm") and config.llm.enabled:
            try:
                inspiration = None
                if "-" in template_value:
                    explicit = template_value.split("-", 1)[1]
                    if explicit in {"coffee", "direct", "warm", "cold"}:
                        inspiration = explicit
                if inspiration is None:
                    inspiration = "warm" if note else "cold"
                intent = "coffee" if inspiration == "coffee" else ("direct" if inspiration == "direct" else None)
                log_utils.log_info(
                    f"LLM mode -> provider={config.llm.provider}, model={config.llm.model}; style inspiration={inspiration}; intent={intent or 'auto'}",
                    verbose=config.verbose,
                )
                subject, body = llm.generate_email_with_llm(config, row_dict, inspiration_kind=inspiration, intent=intent)
            except Exception as exc:
                log_utils.log_error(f"LLM error for {contact_label}: {exc}; falling back to template '{template_kind}'")
                tmpl = templates.load_template(config, template_kind)
                rendered = tmpl.render(name=name, company=company, role=role, personalized_note=note, job_link=job_link, job_id=job_id)
                subject, body = _split_subject(rendered)
        else:
            template_kind = template_kind if template_kind in {"cold", "warm", "coffee", "direct"} else "cold"
            tmpl = templates.load_template(config, template_kind)
            rendered = tmpl.render(name=name, company=company, role=role, personalized_note=note, job_link=job_link, job_id=job_id)
            subject, body = _split_subject(rendered)

        attachment = None
        resume_flag = (row.get("resume_flag") or row.get("resume") or "").strip().lower()
        try:
            attachment = emailer.get_resume_attachment(config, drive_service, resume_flag)
        except Exception as exc:
            log_utils.log_error(f"Failed to fetch resume for flag '{resume_flag}': {exc}")

        if config.dry_run:
            attachment_info = "no"
            if attachment:
                attachment_info = f"yes ({attachment.get('filename')})"
            elif config.resume.local_path.exists():
                attachment_info = f"yes ({config.resume.local_path.name})"
            if config.verbose:
                print(f"-- DRY RUN -- To: {contact_label}\nSubject: {subject}\n{body}\n(attached: {attachment_info})\n---")
            if config.use_sent_log:
                storage.mark_sent(sent_log, name, email, role, company, "DRY_RUN")
            if spreadsheet_id and sheet_row and sheets_service is not None:
                try:
                    data_sources.mark_sheet_row_sent(config, sheets_service, sheet_row, status_value="DRY_RUN")
                except Exception as exc:
                    log_utils.log_error(f"Failed to mark sheet row {sheet_row} (dry run): {exc}")
            continue

        try:
            message = emailer.create_message_with_attachment(email, subject, body, attachment=attachment,
                                                             attachment_path=config.resume.local_path if config.resume.local_path.exists() and not attachment else None)
            response = emailer.send_message(gmail_service, "me", message)
            message_id = response.get("id", "UNKNOWN")
            if config.use_sent_log:
                storage.mark_sent(sent_log, name, email, role, company, message_id)
            sent_count += 1
            log_utils.log_info(f"SENT -> {contact_label} (id={message_id})", verbose=config.verbose)
            if config.use_sent_log:
                storage.save_sent_log(sent_log)
            if spreadsheet_id and sheet_row and sheets_service is not None:
                try:
                    data_sources.mark_sheet_row_sent(config, sheets_service, sheet_row, status_value="SENT")
                except Exception as exc:
                    log_utils.log_error(f"Failed to mark sheet row {sheet_row}: {exc}")
            time.sleep(1.5)
        except Exception as exc:
            log_utils.log_error(f"ERROR sending to {contact_label}: {exc}")

    if config.use_sent_log:
        storage.save_sent_log(sent_log)
    log_utils.log_info(f"Done. Sent {sent_count}.", verbose=config.verbose)
    send_alert_email(gmail_service, config)


def _split_subject(rendered: str) -> tuple[str, str]:
    lines = rendered.splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body = "\n".join(lines[1:]).lstrip()
        return subject, body
    return "Hello", rendered


def main(argv: Optional[list[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "--precheck":
        success = run_precheck(CONFIG)
        if not success:
            sys.exit(1)
    else:
        execute_mailer(CONFIG)


if __name__ == "__main__":
    main()
