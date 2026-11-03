"""Credenciais de integração (tokens, escopos e validade por plataforma)."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone

from .fields import EncryptedTextField

# Antecedência para considerar um token "expirando" no painel e na renovação automática
EXPIRING_SOON = timedelta(days=7)


class Platform(models.TextChoices):
    META = "meta", "Meta (System User)"
    WHATSAPP = "whatsapp", "WhatsApp Cloud API"
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook (Página)"
    THREADS = "threads", "Threads"
    GOOGLE = "google", "Google (YouTube e Calendar)"
    ELEVENLABS = "elevenlabs", "ElevenLabs"
    TWILIO = "twilio", "Twilio"
    AWS = "aws", "AWS (SES e Route 53)"
    ANTHROPIC = "anthropic", "Anthropic"
    FUNNEL_BRIDGE = "funnel_bridge", "Ponte com o funil"


class CredentialStatus(models.TextChoices):
    OK = "ok", "Válida"
    EXPIRING = "expiring", "Expirando"
    EXPIRED = "expired", "Expirada"
    INACTIVE = "inactive", "Inativa"


def mask_secret(value: str) -> str:
    """Mostra só os 4 últimos caracteres de um segredo."""
    if not value:
        return ""
    return f"••••{value[-4:]}" if len(value) > 8 else "••••"


class IntegrationCredential(models.Model):
    """Token de acesso de uma plataforma. Tokens e refresh tokens ficam criptografados."""

    platform = models.CharField("plataforma", max_length=30, choices=Platform.choices)
    label = models.CharField(
        "rótulo",
        max_length=60,
        default="default",
        help_text="Diferencia várias credenciais da mesma plataforma (ex.: duas páginas).",
    )
    account_id = models.CharField(
        "conta", max_length=100, blank=True, help_text="Conta, página, número ou canal do token."
    )
    access_token = EncryptedTextField("access token", blank=True)
    refresh_token = EncryptedTextField("refresh token", blank=True)
    token_type = models.CharField(
        "tipo de token", max_length=40, blank=True, help_text="system_user, page, user, oauth2..."
    )
    scopes = models.JSONField("escopos", default=list, blank=True)
    expires_at = models.DateTimeField(
        "expira em", null=True, blank=True, help_text="Vazio se o token não expira."
    )
    last_refreshed_at = models.DateTimeField("renovada em", null=True, blank=True)
    last_error = models.TextField("último erro", blank=True)
    is_active = models.BooleanField("ativa", default=True)
    metadata = models.JSONField("metadados", default=dict, blank=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["platform", "label"]
        verbose_name = "credencial de integração"
        verbose_name_plural = "credenciais de integração"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "label"], name="credentials_unique_platform_label"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_platform_display()} ({self.label})"

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at is not None and self.expires_at <= (now or timezone.now())

    def expires_within(self, delta: timedelta, now: datetime | None = None) -> bool:
        return self.expires_at is not None and self.expires_at <= (now or timezone.now()) + delta

    def status(self, now: datetime | None = None) -> CredentialStatus:
        """Situação para o painel: inativa, expirada, expirando em até 7 dias ou válida."""
        if not self.is_active:
            return CredentialStatus.INACTIVE
        if self.is_expired(now):
            return CredentialStatus.EXPIRED
        if self.expires_within(EXPIRING_SOON, now):
            return CredentialStatus.EXPIRING
        return CredentialStatus.OK

    @property
    def masked_access_token(self) -> str:
        return mask_secret(self.access_token)

    @property
    def masked_refresh_token(self) -> str:
        return mask_secret(self.refresh_token)
