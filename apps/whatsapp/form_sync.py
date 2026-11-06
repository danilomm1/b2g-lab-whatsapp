"""WhatsApp Flows (formulários nativos) na Meta: criação, publicação e sincronização.

Criar um Flow não manda mensagem a ninguém, mas cria um registro na conta da Meta, e um
Flow publicado não pode mais ser editado: o comando pede o nome explicitamente.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.core.services import record_event

from .client import WhatsAppClient
from .forms_catalog import FormError, FormSpec
from .models import WhatsAppForm


def _waba_id() -> str:
    if not settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
        raise FormError("Defina WHATSAPP_BUSINESS_ACCOUNT_ID no .env.")
    return settings.WHATSAPP_BUSINESS_ACCOUNT_ID


def store_form(data: dict[str, Any]) -> WhatsAppForm:
    form, _ = WhatsAppForm.objects.update_or_create(
        name=str(data.get("name", "")),
        defaults={
            "meta_id": str(data.get("id", "")),
            "status": str(data.get("status", "")),
            "categories": data.get("categories") or [],
            "validation_errors": data.get("validation_errors") or [],
            "raw": data,
        },
    )
    return form


def create_form(
    spec: FormSpec, *, publish: bool = True, client: WhatsAppClient | None = None
) -> WhatsAppForm:
    """Cria o Flow na Meta (publicado, se o JSON for válido) e grava o resultado."""
    own_client = client is None
    client = client or WhatsAppClient()
    try:
        response = client.create_form(
            _waba_id(), spec.name, list(spec.categories), spec.flow_json_text(), publish=publish
        )
        details: dict[str, Any] = {}
        if response.get("id"):
            details = client.graph.get(str(response["id"]), {"fields": "id,name,status,categories"})
    finally:
        if own_client:
            client.close()
    form = store_form(
        {
            "name": spec.name,
            "categories": list(spec.categories),
            **response,
            **details,
            "validation_errors": response.get("validation_errors") or [],
        }
    )
    record_event(
        "whatsapp.form_created",
        external_id=f"{spec.name}:{form.meta_id}",
        summary=f"{spec.name} {form.status or 'sem status'}",
        data={"response": response},
    )
    return form


def sync_forms(*, client: WhatsAppClient | None = None) -> list[WhatsAppForm]:
    """Atualiza WhatsAppForm com os Flows da conta (só leitura na Meta)."""
    own_client = client is None
    client = client or WhatsAppClient()
    try:
        items = client.forms(_waba_id())
    finally:
        if own_client:
            client.close()
    return [store_form(item) for item in items]
