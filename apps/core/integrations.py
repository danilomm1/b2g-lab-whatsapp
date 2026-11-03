"""Checklist das variáveis de ambiente de cada integração, para o painel.

Só verifica se cada variável está preenchida; nunca lê nem exibe os valores.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationRequirement:
    name: str
    phase: str
    env_vars: tuple[str, ...]


@dataclass(frozen=True)
class IntegrationStatus:
    name: str
    phase: str
    configured: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return not self.missing

    @property
    def total(self) -> int:
        return len(self.configured) + len(self.missing)


INTEGRATIONS: tuple[IntegrationRequirement, ...] = (
    IntegrationRequirement(
        "Fundação", "Fase 0", ("DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEY", "LAB_WEBHOOK_SECRET")
    ),
    IntegrationRequirement(
        "Meta (app e webhooks)",
        "Fase 1",
        (
            "META_APP_ID",
            "META_APP_SECRET",
            "META_SYSTEM_USER_TOKEN",
            "META_WEBHOOK_VERIFY_TOKEN",
            "META_GRAPH_API_VERSION",
        ),
    ),
    IntegrationRequirement(
        "WhatsApp", "Fase 2", ("WHATSAPP_BUSINESS_ACCOUNT_ID", "WHATSAPP_PHONE_NUMBER_ID")
    ),
    IntegrationRequirement("Claude (Anthropic)", "Fase 2", ("ANTHROPIC_API_KEY",)),
    IntegrationRequirement("Instagram", "Fase 3", ("INSTAGRAM_BUSINESS_ACCOUNT_ID",)),
    IntegrationRequirement("Facebook", "Fase 3", ("FACEBOOK_PAGE_ID",)),
    IntegrationRequirement("Threads", "Fase 4", ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN")),
    IntegrationRequirement(
        "YouTube", "Fase 5", ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "YOUTUBE_CHANNEL_ID")
    ),
    IntegrationRequirement(
        "Email (SES)",
        "Fase 6",
        ("AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "SES_FROM_EMAIL"),
    ),
    IntegrationRequirement(
        "Voz (ElevenLabs e Twilio)",
        "Fase 7",
        (
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_VOICE_ID",
            "ELEVENLABS_AGENT_ID",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_PHONE_NUMBER",
        ),
    ),
    IntegrationRequirement(
        "Google Calendar",
        "Fase 10",
        ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_CALENDAR_ID"),
    ),
    IntegrationRequirement(
        "Ponte com o funil", "Fase 15", ("FUNNEL_BRIDGE_BASE_URL", "FUNNEL_BRIDGE_HMAC_SECRET")
    ),
)


def integration_statuses() -> list[IntegrationStatus]:
    """Situação de cada integração conforme as variáveis presentes no ambiente."""
    statuses = []
    for item in INTEGRATIONS:
        configured = tuple(var for var in item.env_vars if os.environ.get(var, "").strip())
        missing = tuple(var for var in item.env_vars if var not in configured)
        statuses.append(IntegrationStatus(item.name, item.phase, configured, missing))
    return statuses
