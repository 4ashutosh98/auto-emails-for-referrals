from __future__ import annotations

import json
from typing import Optional, Tuple

from openai import OpenAI

from .config import AppConfig
from . import templates, log_utils


class LLMUnavailable(RuntimeError):
    """Raised when LLM configuration is incomplete."""


def _build_github_model_name(config: AppConfig) -> str:
    configured = config.llm.github_model or config.llm.model
    if "/" in configured:
        return configured
    return f"openai/{configured}"


def get_llm_client_and_model(config: AppConfig) -> Tuple[OpenAI, str]:
    provider = config.llm.provider
    if provider == "openai":
        if not config.llm.openai_api_key:
            raise LLMUnavailable("OPENAI_API_KEY not set; cannot use OpenAI provider")
        client = OpenAI(api_key=config.llm.openai_api_key)
        return client, config.llm.model

    if provider == "azure":
        if not (config.llm.azure_endpoint and config.llm.azure_api_key and config.llm.azure_deployment):
            raise LLMUnavailable(
                "AZURE provider requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT"
            )
        client = OpenAI(
            api_key=config.llm.azure_api_key,
            base_url=f"{config.llm.azure_endpoint}/openai/deployments/{config.llm.azure_deployment}",
        )
        return client, config.llm.azure_deployment

    if provider == "github":
        if not config.llm.github_token:
            raise LLMUnavailable("LLM_GITHUB_TOKEN not set; cannot use GitHub Models provider")
        client = OpenAI(base_url=config.llm.github_endpoint or "https://models.github.ai/inference", api_key=config.llm.github_token)
        return client, _build_github_model_name(config)

    raise LLMUnavailable(f"Unsupported LLM_PROVIDER: {provider}")


def generate_email_with_llm(config: AppConfig, row_dict: dict, inspiration_kind: Optional[str] = None, intent: Optional[str] = None) -> Tuple[str, str]:
    client, model_name = get_llm_client_and_model(config)

    name = row_dict.get("name", "")
    company = row_dict.get("company", "")
    role = row_dict.get("role", "")
    note = row_dict.get("personalized_note", "")
    job_link = row_dict.get("job_link", "")
    job_id = row_dict.get("job_id", "")

    style_text: Optional[str] = None
    if inspiration_kind in {"cold", "warm"}:
        try:
            style_text = templates.load_template_text(config, inspiration_kind)
        except Exception:  # pragma: no cover - fallback handled below
            style_text = None

    system_prompt = (
        "You are an assistant that drafts short, respectful, high-signal referral request emails. "
        "Target length: 120–170 words. One clear ask. Professional and warm. "
        "Include a concise 'why me' line tailored to the company/role. Use the provided personalization if present. "
        "Write in plain text (no markdown). Return ONLY JSON with keys 'subject' and 'body'."
    )

    style_block = ""
    if style_text:
        style_block = (
            "Style inspiration (do not copy verbatim; emulate tone, pacing, and structure):\n"
            f"{style_text}\n"
            "Notes: Ignore any variable markers like {{...}} or Subject: lines in the sample; generate fresh content.\n"
        )

    intent_line = ""
    if intent == "coffee":
        intent_line = (
            "Email intent: Coffee chat — Avoid a direct referral ask; propose a brief 15–20 minute chat to learn about their experience. "
            "It's okay to subtly indicate interest in a referral if the conversation goes well.\n"
        )
    elif intent == "direct":
        intent_line = (
            "Email intent: Direct referral — Be concise and polite; clearly ask for a referral and acknowledge their time. "
            "You may mention that a resume is attached.\n"
        )

    user_prompt = f"""{style_block}{intent_line}
Recipient: {name}
Company: {company}
Role: {role}
Personalization: {note or '(none)'}
Job Link: {job_link or '(not provided)'}
Job ID: {job_id or '(not provided)'}
Candidate: Ashutosh Choudhari — DS/ML/AI engineer. Portfolio: https://4ashutosh98.github.io
Return JSON only."""

    if config.llm.provider == "azure":
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=600,
            extra_query={"api-version": config.llm.azure_api_version},
        )
    else:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=600,
        )

    content = response.choices[0].message.content
    try:
        payload = json.loads(content)
        subject = payload.get("subject", "Referral request")
        body = payload.get("body", content)
        return subject, body
    except Exception as exc:  # pragma: no cover - fallback logic
        log_utils.log_warn(f"LLM returned non-JSON payload: {exc}")
        lines = content.splitlines()
        subject = lines[0].replace("Subject:", "").strip() if lines else "Referral request"
        body = "\n".join(lines[1:]).strip()
        return subject, body
