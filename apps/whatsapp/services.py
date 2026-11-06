"""Único ponto de envio do WhatsApp, com as travas da seção 8 do CLAUDE.md.

Ordem das checagens em send_message:
1. destinatário: telefone do contato ou, sem ele, o BSUID;
2. janela de 24h: fora dela, só template aprovado, e o envio conta como proativo;
3. contato proativo: consentimento ativo e LAB_MAX_PROACTIVE_PER_WEEK;
4. check_outbound: LAB_DRY_RUN simula, e envio real só para LAB_ALLOWED_RECIPIENTS.
Bloqueios levantam SendBlocked e nada é gravado; simulações e falhas da API viram Message.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from apps.core.models import (
    Channel,
    ChannelIdentity,
    ConsentPurpose,
    Contact,
    Conversation,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.core.safety import check_outbound, check_proactive_contact
from apps.core.services import record_event
from apps.meta_business.client import GraphAPIError

from .client import WhatsAppClient, default_phone_number_id
from .inbound import open_conversation
from .payloads import OutboundPayload

logger = logging.getLogger(__name__)


class SendBlocked(Exception):
    """Envio barrado por uma trava do laboratório; a mensagem não saiu nem foi gravada."""


def _bsuid(contact: Contact) -> str:
    identity = (
        ChannelIdentity.objects.filter(contact=contact, channel=Channel.WHATSAPP)
        .order_by("-last_seen_at")
        .first()
    )
    return identity.external_id if identity and "." in identity.external_id else ""


def recipient_fields(contact: Contact) -> dict[str, str]:
    """Campo de destino da Cloud API: "to" com o telefone ou "recipient" com o BSUID."""
    if contact.phone:
        return {"to": contact.phone}
    bsuid = _bsuid(contact)
    if bsuid:
        return {"recipient": bsuid}
    raise SendBlocked(f"{contact} não tem telefone nem BSUID do WhatsApp")


def send_message(
    contact: Contact,
    outbound: OutboundPayload,
    *,
    conversation: Conversation | None = None,
    proactive: bool = False,
    purpose: str = ConsentPurpose.SERVICE,
    dry_run: bool | None = None,
    client: WhatsAppClient | None = None,
) -> Message:
    """Envia (ou simula) uma mensagem e grava o resultado. Ver as travas no topo do módulo.

    proactive=True marca mensagens iniciadas pela empresa mesmo dentro da janela;
    fora da janela o envio é sempre tratado como proativo.
    """
    phone_number_id = (
        conversation.account_id if conversation and conversation.account_id else None
    ) or default_phone_number_id()
    conversation = conversation or open_conversation(contact, phone_number_id)
    target = recipient_fields(contact)

    if not conversation.is_service_window_open():
        if not outbound.is_template:
            raise SendBlocked("Fora da janela de 24h: só um template aprovado pode ser enviado")
        proactive = True
    if proactive:
        proactive_decision = check_proactive_contact(contact, Channel.WHATSAPP, purpose)
        if not proactive_decision.allowed:
            raise SendBlocked(proactive_decision.reason)
    decision = check_outbound(next(iter(target.values())), dry_run=dry_run)
    if not decision.allowed:
        raise SendBlocked(decision.reason)

    request: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        **target,
        **outbound.data,
    }
    message = Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.OUTBOUND,
        kind=outbound.kind,
        body=outbound.body,
        status=MessageStatus.SIMULATED if decision.dry_run else MessageStatus.QUEUED,
        is_proactive=proactive,
        raw_payload={"request": request, "decision": decision.reason},
    )
    if decision.dry_run:
        logger.info("WhatsApp simulado para %s: %s", contact, outbound.body[:80])
        return _touch(conversation, message)

    own_client = client is None
    client = client or WhatsAppClient(phone_number_id)
    try:
        response = client.send(request)
    except GraphAPIError as exc:
        message.status = MessageStatus.FAILED
        message.error = {
            "message": str(exc),
            "status": exc.status,
            "code": exc.code,
            "subcode": exc.subcode,
            "fbtrace_id": exc.fbtrace_id,
            "payload": exc.payload,
        }
        message.save(update_fields=["status", "error"])
        record_event(
            "whatsapp.message_failed",
            contact=contact,
            channel=Channel.WHATSAPP,
            summary=f"{exc.code or exc.status or ''} {exc}".strip(),
            data={"message_id": message.pk, "code": exc.code, "network": exc.network},
        )
        return message
    finally:
        if own_client:
            client.close()

    sent = (response.get("messages") or [{}])[0]
    message.external_id = str(sent.get("id", ""))
    message.raw_payload = {**message.raw_payload, "response": response}
    message.save(update_fields=["external_id", "raw_payload"])
    return _touch(conversation, message)


def _touch(conversation: Conversation, message: Message) -> Message:
    conversation.last_message_at = message.created_at or timezone.now()
    conversation.save(update_fields=["last_message_at", "updated_at"])
    return message


def mark_as_read(
    message: Message,
    *,
    typing: bool = False,
    dry_run: bool | None = None,
    client: WhatsAppClient | None = None,
) -> bool:
    """Marca uma mensagem recebida como lida (e opcionalmente mostra "digitando...").

    Também é um efeito visível para o contato, então segue dry-run e allowlist.
    Retorna se a chamada foi feita de verdade.
    """
    if message.direction != MessageDirection.INBOUND or not message.external_id:
        return False
    contact = message.conversation.contact
    try:
        target = recipient_fields(contact)
    except SendBlocked:
        return False
    if not check_outbound(next(iter(target.values())), dry_run=dry_run).send_for_real:
        return False
    own_client = client is None
    client = client or WhatsAppClient(message.conversation.account_id or None)
    try:
        client.mark_as_read(message.external_id, typing=typing)
    except GraphAPIError as exc:
        logger.warning("Falha ao marcar %s como lida: %s", message.external_id, exc)
        return False
    finally:
        if own_client:
            client.close()
    return True
