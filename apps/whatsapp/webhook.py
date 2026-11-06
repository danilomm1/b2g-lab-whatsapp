"""Handler da rota whatsapp_business_account do provedor de webhook da Meta.

A entrega já chegou assinada e foi gravada pela esteira (ADR 0003); aqui só se
interpreta o campo "messages". Os demais campos (ex.: message_template_status_update)
ficam registrados no bruto e ganham tratamento quando forem usados.
"""

import logging
from typing import Any

from apps.webhooks.models import WebhookDelivery
from apps.webhooks.registry import registry

from .inbound import process_inbound_message, process_status

logger = logging.getLogger(__name__)

ROUTE = "whatsapp_business_account"


def process_messages_value(value: dict[str, Any], *, waba_id: str) -> None:
    """Processa um bloco value do campo messages: mensagens recebidas e status."""
    metadata = value.get("metadata") or {}
    contacts = [c for c in value.get("contacts") or [] if isinstance(c, dict)]
    for message in value.get("messages") or []:
        if isinstance(message, dict):
            process_inbound_message(message, contacts=contacts, metadata=metadata, waba_id=waba_id)
    for status in value.get("statuses") or []:
        if isinstance(status, dict):
            process_status(status)
    for error in value.get("errors") or []:
        logger.warning("Erro informado pelo webhook do WhatsApp (WABA %s): %s", waba_id, error)


def handle_delivery(delivery: WebhookDelivery) -> None:
    payload = delivery.raw_payload if isinstance(delivery.raw_payload, dict) else {}
    for entry in payload.get("entry") or []:
        waba_id = str(entry.get("id", ""))
        for change in entry.get("changes") or []:
            field = change.get("field")
            if field == "messages":
                process_messages_value(change.get("value") or {}, waba_id=waba_id)
            else:
                logger.info("Campo %s do WhatsApp sem tratamento (entrega %s)", field, delivery.pk)


def register() -> None:
    registry.register_handler("meta", ROUTE, handle_delivery)
