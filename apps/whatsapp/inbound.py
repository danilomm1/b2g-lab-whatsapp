"""Mensagens recebidas e status de entrega vindos do campo "messages" do webhook.

Referência: Webhooks > Reference > messages (text, interactive, button, status, system).
Tudo é idempotente pelo wamid: reprocessar a mesma entrega não duplica nada.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.models import (
    Channel,
    Contact,
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.core.safety import is_opt_out_message
from apps.core.services import apply_opt_out, record_event

from .identity import Sender, apply_identity_change, resolve_sender

logger = logging.getLogger(__name__)

OPT_OUT_SOURCE = "whatsapp_keyword"

# "played" (áudio ouvido) não muda o status da mensagem; fica só no histórico
STATUS_MAP = {
    "sent": MessageStatus.SENT,
    "delivered": MessageStatus.DELIVERED,
    "read": MessageStatus.READ,
    "failed": MessageStatus.FAILED,
}

# Tipos cujo texto é escrito ou escolhido pelo contato: valem para a palavra de saída
_OPT_OUT_KINDS = frozenset({"text", "button", "interactive"})
MEDIA_KINDS = frozenset({"image", "video", "audio", "document", "sticker"})


def parse_timestamp(value: Any) -> datetime:
    """Unixtime da Meta em datetime com fuso; ausente ou inválido vira agora."""
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return timezone.now()


@dataclass(frozen=True)
class InboundContent:
    kind: str
    body: str
    reply_id: str = ""  # ID do botão ou da linha da lista escolhida
    form_response: dict[str, Any] = field(default_factory=dict)  # respostas de um WhatsApp Flow


def _form_summary(response: dict[str, Any]) -> str:
    fields = [f"{k}: {v}" for k, v in response.items() if k != "flow_token" and v not in ("", None)]
    return "[formulário] " + "; ".join(fields) if fields else "[formulário enviado]"


def extract_content(message: dict[str, Any]) -> InboundContent:
    """Tipo, texto legível e, em respostas a botões e listas, o ID escolhido."""
    kind = str(message.get("type") or "unknown")
    data = message.get(kind)
    data = data if isinstance(data, dict) else {}
    if kind == "text":
        return InboundContent(kind, str(data.get("body", "")))
    if kind == "interactive":
        reply = data.get(str(data.get("type", "")), {})
        reply = reply if isinstance(reply, dict) else {}
        if data.get("type") == "nfm_reply":  # resposta de WhatsApp Flow (formulário nativo)
            try:
                response = json.loads(reply.get("response_json") or "{}")
            except ValueError:
                response = {}
            response = response if isinstance(response, dict) else {}
            return InboundContent(kind, _form_summary(response), form_response=response)
        return InboundContent(
            kind, str(reply.get("title") or reply.get("body") or ""), str(reply.get("id", ""))
        )
    if kind == "button":  # botão de resposta rápida de template
        return InboundContent(kind, str(data.get("text", "")), str(data.get("payload", "")))
    if kind in MEDIA_KINDS:
        return InboundContent(kind, str(data.get("caption", "")))
    if kind == "location":
        place = ", ".join(str(data[k]) for k in ("name", "address") if data.get(k))
        return InboundContent(kind, place or f"{data.get('latitude')},{data.get('longitude')}")
    if kind == "reaction":
        return InboundContent(kind, str(data.get("emoji", "")))
    if kind == "contacts":
        contacts = message.get("contacts", [])
        names = [str(c.get("name", {}).get("formatted_name", "")) for c in contacts]
        return InboundContent(kind, ", ".join(n for n in names if n))
    return InboundContent(kind, "")


def _sender_for(message: dict[str, Any], contacts: list[dict[str, Any]]) -> tuple[Sender, dict]:
    """Junta o remetente da mensagem com o bloco contacts correspondente."""
    user_id = str(message.get("from_user_id") or "")
    wa_id = str(message.get("from") or "")
    contact_data: dict[str, Any] = {}
    for item in contacts:
        if (user_id and item.get("user_id") == user_id) or (wa_id and item.get("wa_id") == wa_id):
            contact_data = item
            break
    else:
        if len(contacts) == 1:
            contact_data = contacts[0]
    profile = contact_data.get("profile") or {}
    sender = Sender(
        user_id=user_id or str(contact_data.get("user_id") or ""),
        wa_id=wa_id or str(contact_data.get("wa_id") or ""),
        name=str(profile.get("name") or ""),
        username=str(profile.get("username") or ""),
    )
    return sender, contact_data


def open_conversation(contact: Contact, phone_number_id: str) -> Conversation:
    """Conversa não encerrada do contato com o número da Brave2Grow, ou uma nova."""
    conversation = (
        Conversation.objects.filter(
            contact=contact, channel=Channel.WHATSAPP, account_id=phone_number_id
        )
        .exclude(status=ConversationStatus.CLOSED)
        .order_by("-created_at")
        .first()
    )
    if conversation is None:
        conversation = Conversation.objects.create(
            contact=contact, channel=Channel.WHATSAPP, account_id=phone_number_id
        )
    return conversation


def process_inbound_message(
    message: dict[str, Any],
    *,
    contacts: list[dict[str, Any]],
    metadata: dict[str, Any],
    waba_id: str,
) -> Message | None:
    """Grava a mensagem recebida, atualiza a janela de 24h e aplica a palavra de saída.

    Retorna None para mensagens de sistema e para wamids já gravados.
    """
    wamid = str(message.get("id") or "")
    if not wamid or Message.objects.filter(channel=Channel.WHATSAPP, external_id=wamid).exists():
        return None
    sent_at = parse_timestamp(message.get("timestamp"))

    if message.get("type") == "system":
        system = message.get("system") or {}
        identity = apply_identity_change(system, waba_id=waba_id)
        record_event(
            "whatsapp.identity_changed",
            contact=identity.contact if identity else None,
            channel=Channel.WHATSAPP,
            external_id=wamid,
            occurred_at=sent_at,
            summary=str(system.get("type", "system")),
            data={"system": system, "matched": identity is not None},
        )
        return None

    sender, contact_data = _sender_for(message, contacts)
    if not sender.external_id:
        logger.warning("Mensagem %s do WhatsApp sem remetente identificável", wamid)
        return None
    identity = resolve_sender(sender, waba_id=waba_id, seen_at=sent_at)
    contact = identity.contact
    phone_number_id = str(metadata.get("phone_number_id", ""))
    conversation = open_conversation(contact, phone_number_id)

    content = extract_content(message)
    stored = Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.INBOUND,
        kind=content.kind,
        body=content.body,
        external_id=wamid,
        status=MessageStatus.RECEIVED,
        raw_payload={
            "message": message,
            "contact": contact_data,
            "metadata": metadata,
            "reply_id": content.reply_id,
            "form_response": content.form_response,
        },
        created_at=sent_at,
    )
    if content.kind in MEDIA_KINDS:
        _schedule_media_download(stored.pk)
    conversation.last_inbound_at = max(filter(None, [conversation.last_inbound_at, sent_at]))
    conversation.last_message_at = max(filter(None, [conversation.last_message_at, sent_at]))
    conversation.save(update_fields=["last_inbound_at", "last_message_at", "updated_at"])

    record_event(
        "whatsapp.message_received",
        contact=contact,
        channel=Channel.WHATSAPP,
        external_id=wamid,
        occurred_at=sent_at,
        summary=content.body or content.kind,
        data={"message_id": stored.pk, "kind": content.kind, "reply_id": content.reply_id},
    )
    if content.kind in _OPT_OUT_KINDS and is_opt_out_message(content.body):
        apply_opt_out(contact, Channel.WHATSAPP, source=OPT_OUT_SOURCE)
    return stored


def process_status(status: dict[str, Any]) -> Message | None:
    """Avança o status de uma mensagem enviada por nós, sem regredir.

    Guarda cada notificação (com o bloco pricing) no histórico da mensagem. Status de
    mensagens que não saíram do laboratório (ex.: teste pelo painel) são ignorados.
    """
    wamid = str(status.get("id") or "")
    message = (
        Message.objects.select_related("conversation__contact")
        .filter(channel=Channel.WHATSAPP, direction=MessageDirection.OUTBOUND, external_id=wamid)
        .first()
    )
    if message is None:
        logger.info("Status %s para mensagem desconhecida %s", status.get("status"), wamid)
        return None

    payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
    history = payload.setdefault("statuses", [])
    if status in history:
        return message
    history.append(status)
    message.raw_payload = payload
    fields = ["raw_payload"]

    new_status = STATUS_MAP.get(str(status.get("status")))
    at = parse_timestamp(status.get("timestamp"))
    if new_status and message.advance_status(new_status, at):
        fields += ["status", "status_updated_at"]
        if new_status == MessageStatus.FAILED:
            errors = status.get("errors") or []
            message.error = {"errors": errors}
            fields.append("error")
            first = errors[0] if errors and isinstance(errors[0], dict) else {}
            record_event(
                "whatsapp.message_failed",
                contact=message.conversation.contact,
                channel=Channel.WHATSAPP,
                external_id=wamid,
                occurred_at=at,
                summary=f"{first.get('code', '')} {first.get('title', 'falha no envio')}".strip(),
                data={"message_id": message.pk, "errors": errors},
            )
    message.save(update_fields=fields)
    return message


def _schedule_media_download(message_id: int) -> None:
    """A URL da mídia vale só 5 minutos: o download sai logo depois do commit."""
    from .tasks import download_media

    transaction.on_commit(lambda: download_media(message_id))
