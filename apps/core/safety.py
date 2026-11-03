"""Travas de segurança operacional (CLAUDE.md, seção 8).

Toda função que publica, envia mensagem, envia email ou faz ligação deve passar por
check_outbound antes de chamar a API externa. Contatos iniciados pela empresa passam
também por check_proactive_contact.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Contact, Message, MessageDirection, MessageStatus
from .phone import InvalidPhoneNumber, normalize_phone
from .services import has_active_consent

OPT_OUT_KEYWORDS = frozenset({"SAIR", "PARAR", "STOP"})


def is_opt_out_message(text: str) -> bool:
    """Indica se a mensagem inteira é uma palavra de saída, ignorando caixa, acento e pontuação."""
    decomposed = unicodedata.normalize("NFKD", text)
    letters = "".join(ch for ch in decomposed if ch.isalpha())
    return letters.upper() in OPT_OUT_KEYWORDS


def effective_dry_run(dry_run: bool | None = None) -> bool:
    """Resolve o modo simulado: LAB_DRY_RUN=True sempre vence; dry_run=True força a simulação."""
    return bool(settings.LAB_DRY_RUN or dry_run)


def normalize_recipient(value: str) -> str:
    """Normaliza email (minúsculas) e telefone (E.164) para comparar com a allowlist."""
    value = value.strip()
    if "@" in value and not value.startswith("@"):
        return value.lower()
    try:
        return normalize_phone(value)
    except InvalidPhoneNumber:
        return value.lower()


def is_recipient_allowed(recipient: str) -> bool:
    """Indica se o destinatário está em LAB_ALLOWED_RECIPIENTS."""
    allowed = {normalize_recipient(item) for item in settings.LAB_ALLOWED_RECIPIENTS if item}
    return normalize_recipient(recipient) in allowed


@dataclass(frozen=True)
class OutboundDecision:
    """Resultado da checagem antes de um envio."""

    dry_run: bool
    allowed: bool
    reason: str

    @property
    def send_for_real(self) -> bool:
        return self.allowed and not self.dry_run


def check_outbound(recipient: str, *, dry_run: bool | None = None) -> OutboundDecision:
    """Decide se um envio pode sair de verdade, deve ser simulado ou deve ser bloqueado."""
    if effective_dry_run(dry_run):
        return OutboundDecision(dry_run=True, allowed=True, reason="dry-run: envio simulado")
    if not is_recipient_allowed(recipient):
        return OutboundDecision(
            dry_run=False, allowed=False, reason="destinatário fora de LAB_ALLOWED_RECIPIENTS"
        )
    return OutboundDecision(dry_run=False, allowed=True, reason="envio real liberado")


def proactive_sends_last_week(contact: Contact) -> int:
    """Mensagens iniciadas pela empresa nos últimos 7 dias, somando todos os canais.

    Envios simulados (dry-run) não contam, pois não chegaram a ninguém.
    """
    since = timezone.now() - timedelta(days=7)
    return (
        Message.objects.filter(
            conversation__contact=contact,
            direction=MessageDirection.OUTBOUND,
            is_proactive=True,
            created_at__gte=since,
        )
        .exclude(status__in=[MessageStatus.SIMULATED, MessageStatus.FAILED])
        .count()
    )


@dataclass(frozen=True)
class ProactiveDecision:
    allowed: bool
    reason: str


def check_proactive_contact(contact: Contact, channel: str, purpose: str) -> ProactiveDecision:
    """Verifica consentimento e limite semanal antes de um contato iniciado pela empresa."""
    if not has_active_consent(contact, channel, purpose):
        return ProactiveDecision(False, f"sem consentimento ativo para {channel}/{purpose}")
    limit = settings.LAB_MAX_PROACTIVE_PER_WEEK
    if proactive_sends_last_week(contact) >= limit:
        return ProactiveDecision(False, f"limite de {limit} contatos proativos por semana atingido")
    return ProactiveDecision(True, "ok")
