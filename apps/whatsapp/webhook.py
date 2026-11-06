"""Handler da rota whatsapp_business_account do provedor de webhook da Meta.

A entrega já chegou assinada e foi gravada pela esteira (ADR 0003). Campos tratados:
messages (mensagens recebidas, que seguem para o motor de fluxo, e status de entrega) e
message_template_status_update (aprovação dos templates). Os demais ficam no bruto.
"""

import logging
from typing import Any

from django.db import transaction

from apps.core.models import Message
from apps.core.services import record_event
from apps.webhooks.models import WebhookDelivery
from apps.webhooks.registry import registry

from .flows import handle_inbound
from .inbound import process_inbound_message, process_status
from .template_sync import apply_status_update

logger = logging.getLogger(__name__)

ROUTE = "whatsapp_business_account"


def run_flows(message: Message) -> None:
    """Passa a mensagem ao motor de fluxo num savepoint: uma falha nele vira evento e não
    impede que a mensagem fique gravada (um novo processamento não a repassaria ao motor)."""
    try:
        with transaction.atomic():
            handle_inbound(message)
    except Exception as exc:
        logger.exception("Falha no motor de fluxo para a mensagem %s", message.external_id)
        record_event(
            "whatsapp.flow_error",
            contact=message.conversation.contact,
            channel="whatsapp",
            summary=f"Motor de fluxo: {exc}"[:255],
            data={"message_id": message.pk},
        )


def process_messages_value(value: dict[str, Any], *, waba_id: str) -> None:
    """Processa um bloco value do campo messages: mensagens recebidas e status."""
    metadata = value.get("metadata") or {}
    contacts = [c for c in value.get("contacts") or [] if isinstance(c, dict)]
    for message in value.get("messages") or []:
        if isinstance(message, dict):
            stored = process_inbound_message(
                message, contacts=contacts, metadata=metadata, waba_id=waba_id
            )
            if stored is not None:
                run_flows(stored)
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
            value = change.get("value") or {}
            if field == "messages":
                process_messages_value(value, waba_id=waba_id)
            elif field == "message_template_status_update":
                apply_status_update(value)
            else:
                logger.info("Campo %s do WhatsApp sem tratamento (entrega %s)", field, delivery.pk)


def register() -> None:
    registry.register_handler("meta", ROUTE, handle_delivery)
