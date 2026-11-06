"""Templates na Meta: envio para aprovação, sincronização e webhook de status.

O conteúdo vem do catálogo (templates_catalog.py); o estado na Meta fica em
MessageTemplate. Enviar para aprovação não manda mensagem a ninguém, mas cria um
registro na conta da Meta: o comando pede o nome explicitamente.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.core.services import record_event

from .client import WhatsAppClient
from .models import MessageTemplate
from .templates_catalog import TemplateError, TemplateSpec

logger = logging.getLogger(__name__)


def _waba_id() -> str:
    if not settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
        raise TemplateError("Defina WHATSAPP_BUSINESS_ACCOUNT_ID no .env.")
    return settings.WHATSAPP_BUSINESS_ACCOUNT_ID


def _language(value: str) -> str:
    """O webhook usa "en-US" e a API usa "en_US"; guardamos com sublinhado."""
    return value.replace("-", "_")


def store_template(data: dict[str, Any]) -> MessageTemplate:
    """Grava o que a Meta informou sobre um template (listagem ou criação)."""
    template, _ = MessageTemplate.objects.update_or_create(
        name=str(data.get("name", "")),
        language=_language(str(data.get("language", ""))),
        defaults={
            "category": str(data.get("category", "")),
            "status": str(data.get("status", "")),
            "meta_id": str(data.get("id", "")),
            "rejected_reason": str(data.get("rejected_reason") or "")[:255],
            "components": data.get("components") or [],
            "raw": data,
        },
    )
    return template


def submit_template(spec: TemplateSpec, *, client: WhatsAppClient | None = None) -> MessageTemplate:
    """Envia um template do catálogo para a análise da Meta e grava o status inicial."""
    if spec.managed_by_meta:
        raise TemplateError(f"{spec.name} é um exemplo da Meta e já existe na conta")
    payload = spec.creation_payload()
    own_client = client is None
    client = client or WhatsAppClient()
    try:
        response = client.create_template(_waba_id(), payload)
    finally:
        if own_client:
            client.close()
    template = store_template({**payload, **response, "components": payload["components"]})
    record_event(
        "whatsapp.template_submitted",
        external_id=f"{spec.name}:{spec.language}:{template.meta_id}",
        summary=f"{spec.name} [{spec.language}] {template.status}",
        data={"response": response},
    )
    return template


def sync_templates(*, client: WhatsAppClient | None = None) -> list[MessageTemplate]:
    """Atualiza MessageTemplate com a lista de templates da conta (só leitura na Meta)."""
    own_client = client is None
    client = client or WhatsAppClient()
    try:
        items = client.message_templates(_waba_id())
    finally:
        if own_client:
            client.close()
    return [store_template(item) for item in items]


def apply_status_update(value: dict[str, Any]) -> MessageTemplate | None:
    """Webhook message_template_status_update: novo status, categoria e motivo."""
    name = str(value.get("message_template_name") or "")
    language = _language(str(value.get("message_template_language") or ""))
    event = str(value.get("event") or "")
    if not name or not event:
        logger.warning("Status de template sem nome ou evento: %s", value)
        return None
    template, _ = MessageTemplate.objects.get_or_create(name=name, language=language)
    template.status = event
    template.meta_id = str(value.get("message_template_id") or template.meta_id)
    template.category = str(value.get("message_template_category") or template.category)
    reason = value.get("reason")
    template.rejected_reason = "" if reason in (None, "NONE") else str(reason)[:255]
    template.raw = {**template.raw, "last_status_update": value}
    template.save()
    record_event(
        "whatsapp.template_status",
        summary=f"{name} [{language}] {event}",
        data={"value": value},
    )
    return template
