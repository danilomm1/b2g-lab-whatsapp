"""Recebimento pela Messenger Platform, comum ao Instagram (Direct) e à Página (Messenger).

Os dois canais entregam no mesmo formato: entry[].messaging[] com sender, recipient,
timestamp e um bloco por tipo de evento (message, postback, reaction, read, delivery,
message_edit, referral). Os horários vêm em milissegundos. O botão "Teste" do painel
manda os mesmos eventos em entry[].changes[].value, com o horário em segundos.

entry.id é a conta da Brave2Grow (conta do Instagram ou Página) e vira o account_id da
identidade e da conversa: IGSID e PSID só valem dentro da conta que recebeu a mensagem.
Tudo é idempotente pelo mid: reprocessar a mesma entrega não duplica nada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import (
    ChannelIdentity,
    Contact,
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.core.safety import is_opt_out_message
from apps.core.services import apply_opt_out, record_event

logger = logging.getLogger(__name__)

# Acima disso o número só pode ser milissegundos (10**11 segundos cai no ano 5138)
_MILLISECONDS_THRESHOLD = 10**11


def parse_timestamp(value: Any) -> datetime:
    """Horário da Meta em datetime com fuso, aceitando milissegundos ou segundos.

    Ausente ou inválido vira agora.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return timezone.now()
    if number > _MILLISECONDS_THRESHOLD:
        number /= 1000
    return datetime.fromtimestamp(number, tz=UTC)


def is_messaging_value(value: Any) -> bool:
    """Indica se um value de changes[] é um evento de mensagem (formato do botão "Teste")."""
    return isinstance(value, dict) and "sender" in value and "recipient" in value


@dataclass(frozen=True)
class InboundContent:
    kind: str
    body: str
    reply_id: str = ""  # payload da resposta rápida ou do botão escolhido


def extract_content(message: dict[str, Any]) -> InboundContent:
    """Tipo, texto legível e, em respostas rápidas, o payload escolhido."""
    text = str(message.get("text") or "")
    quick_reply = message.get("quick_reply")
    reply_id = str(quick_reply.get("payload", "")) if isinstance(quick_reply, dict) else ""
    if message.get("is_unsupported"):
        return InboundContent("unsupported", text)
    if text:
        return InboundContent("text", text, reply_id)
    attachments = [a for a in message.get("attachments") or [] if isinstance(a, dict)]
    if attachments:
        first = attachments[0]
        payload = first.get("payload")
        title = str(payload.get("title") or "") if isinstance(payload, dict) else ""
        return InboundContent(str(first.get("type") or "attachment"), title)
    if message.get("admin_text"):
        return InboundContent("admin_text", str(message["admin_text"]))
    return InboundContent("unknown", "")


def find_identity(channel: str, account_id: str, user_id: str) -> ChannelIdentity | None:
    return (
        ChannelIdentity.objects.select_related("contact")
        .filter(channel=channel, account_id=account_id, external_id=user_id)
        .first()
    )


def resolve_user(
    channel: str,
    account_id: str,
    user_id: str,
    *,
    seen_at: datetime,
    source: str,
    handle: str = "",
) -> ChannelIdentity:
    """Encontra ou cria o contato e a identidade de quem escreveu (IGSID ou PSID).

    O webhook não traz nome nem telefone: um contato novo nasce só com a origem, e o
    perfil é buscado logo depois (profiles.fetch_profile).
    """
    identity = find_identity(channel, account_id, user_id)
    created = identity is None
    if identity is None:
        contact = Contact.objects.create(source=source)
        identity = ChannelIdentity(
            contact=contact,
            channel=channel,
            account_id=account_id,
            external_id=user_id,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
    if handle:
        identity.handle = handle
    identity.last_seen_at = max(identity.last_seen_at or seen_at, seen_at)
    identity.save()
    if created:
        _schedule_profile_fetch(identity.pk)
    return identity


def _schedule_profile_fetch(identity_id: int) -> None:
    """Nome e @ vêm da User Profile API, consultada depois do commit."""
    from .tasks import fetch_user_profile

    transaction.on_commit(lambda: fetch_user_profile(identity_id))


def open_conversation(contact: Contact, channel: str, account_id: str) -> Conversation:
    """Conversa não encerrada do contato com a conta da Brave2Grow, ou uma nova."""
    conversation = (
        Conversation.objects.filter(contact=contact, channel=channel, account_id=account_id)
        .exclude(status=ConversationStatus.CLOSED)
        .order_by("-created_at")
        .first()
    )
    if conversation is None:
        conversation = Conversation.objects.create(
            contact=contact, channel=channel, account_id=account_id
        )
    return conversation


def _touch(conversation: Conversation, at: datetime, *, inbound: bool) -> None:
    """Atualiza a última mensagem e, se veio do contato, a janela de 24h."""
    fields = ["last_message_at", "updated_at"]
    conversation.last_message_at = max(filter(None, [conversation.last_message_at, at]))
    if inbound:
        conversation.last_inbound_at = max(filter(None, [conversation.last_inbound_at, at]))
        fields.append("last_inbound_at")
    conversation.save(update_fields=fields)


def process_messaging_event(
    event: dict[str, Any], *, channel: str, account_id: str
) -> Message | None:
    """Trata um evento de messaging[]. Retorna a mensagem gravada, quando houver uma nova."""
    sender = str((event.get("sender") or {}).get("id") or "")
    recipient = str((event.get("recipient") or {}).get("id") or "")
    at = parse_timestamp(event.get("timestamp"))
    message = event.get("message")
    if isinstance(message, dict):
        if message.get("is_echo"):  # enviada pela própria conta: o contato é o destinatário
            return _store_echo(
                event, message, channel=channel, account_id=account_id, user_id=recipient, at=at
            )
        if message.get("is_deleted"):
            _mark_deleted(message, channel=channel, account_id=account_id, user_id=sender, at=at)
            return None
        return _store_inbound(
            event, message, channel=channel, account_id=account_id, user_id=sender, at=at
        )
    if isinstance(event.get("postback"), dict):
        return _store_postback(event, channel=channel, account_id=account_id, user_id=sender, at=at)
    if isinstance(event.get("reaction"), dict):
        _record_reaction(event, channel=channel, account_id=account_id, user_id=sender, at=at)
    elif isinstance(event.get("read"), dict):
        _advance_outbound(
            event["read"],
            MessageStatus.READ,
            channel=channel,
            account_id=account_id,
            user_id=sender,
        )
    elif isinstance(event.get("delivery"), dict):
        _advance_outbound(
            event["delivery"],
            MessageStatus.DELIVERED,
            channel=channel,
            account_id=account_id,
            user_id=sender,
        )
    elif isinstance(event.get("message_edit"), dict):
        _apply_edit(event["message_edit"], channel=channel, at=at)
    elif isinstance(event.get("referral"), dict):
        _record_referral(event, channel=channel, account_id=account_id, user_id=sender, at=at)
    else:
        logger.info("Evento de %s sem tratamento: %s", channel, sorted(event))
    return None


def _store_inbound(
    event: dict[str, Any],
    message: dict[str, Any],
    *,
    channel: str,
    account_id: str,
    user_id: str,
    at: datetime,
) -> Message | None:
    """Grava a mensagem do contato, abre a janela de 24h e aplica a palavra de saída."""
    mid = str(message.get("mid") or "")
    if not mid or not user_id:
        logger.info("Mensagem de %s sem mid ou remetente: %s", channel, sorted(message))
        return None
    if Message.objects.filter(channel=channel, external_id=mid).exists():
        return None
    identity = resolve_user(channel, account_id, user_id, seen_at=at, source=f"{channel}_inbound")
    contact = identity.contact
    conversation = open_conversation(contact, channel, account_id)
    content = extract_content(message)
    stored = Message.objects.create(
        conversation=conversation,
        channel=channel,
        direction=MessageDirection.INBOUND,
        kind=content.kind,
        body=content.body,
        external_id=mid,
        status=MessageStatus.RECEIVED,
        raw_payload={"event": event, "reply_id": content.reply_id},
        created_at=at,
    )
    _touch(conversation, at, inbound=True)
    record_event(
        f"{channel}.message_received",
        contact=contact,
        channel=channel,
        external_id=mid,
        occurred_at=at,
        summary=content.body or content.kind,
        data={"message_id": stored.pk, "kind": content.kind, "reply_id": content.reply_id},
    )
    if content.kind == "text" and is_opt_out_message(content.body):
        apply_opt_out(contact, channel, source=f"{channel}_keyword")
    return stored


def _store_postback(
    event: dict[str, Any], *, channel: str, account_id: str, user_id: str, at: datetime
) -> Message | None:
    """Botão tocado (Icebreaker, template genérico): vira mensagem do contato com o payload."""
    postback = event["postback"]
    mid = str(postback.get("mid") or f"postback:{user_id}:{event.get('timestamp', '')}")
    if not user_id or Message.objects.filter(channel=channel, external_id=mid).exists():
        return None
    identity = resolve_user(channel, account_id, user_id, seen_at=at, source=f"{channel}_inbound")
    conversation = open_conversation(identity.contact, channel, account_id)
    payload = str(postback.get("payload") or "")
    stored = Message.objects.create(
        conversation=conversation,
        channel=channel,
        direction=MessageDirection.INBOUND,
        kind="postback",
        body=str(postback.get("title") or ""),
        external_id=mid,
        status=MessageStatus.RECEIVED,
        raw_payload={"event": event, "reply_id": payload},
        created_at=at,
    )
    _touch(conversation, at, inbound=True)
    record_event(
        f"{channel}.message_received",
        contact=identity.contact,
        channel=channel,
        external_id=mid,
        occurred_at=at,
        summary=stored.body or "postback",
        data={"message_id": stored.pk, "kind": "postback", "reply_id": payload},
    )
    return stored


def _store_echo(
    event: dict[str, Any],
    message: dict[str, Any],
    *,
    channel: str,
    account_id: str,
    user_id: str,
    at: datetime,
) -> Message | None:
    """Eco de mensagem enviada pela conta (app do Instagram, caixa da Página ou outro app).

    Mensagens enviadas pelo laboratório já estão gravadas com o mesmo mid e são puladas.
    """
    mid = str(message.get("mid") or "")
    if not mid or not user_id or Message.objects.filter(channel=channel, external_id=mid).exists():
        return None
    identity = resolve_user(channel, account_id, user_id, seen_at=at, source=f"{channel}_outbound")
    conversation = open_conversation(identity.contact, channel, account_id)
    content = extract_content(message)
    stored = Message.objects.create(
        conversation=conversation,
        channel=channel,
        direction=MessageDirection.OUTBOUND,
        kind=content.kind,
        body=content.body,
        external_id=mid,
        status=MessageStatus.SENT,
        raw_payload={"event": event, "echo": True},
        status_updated_at=at,
        created_at=at,
    )
    _touch(conversation, at, inbound=False)
    return stored


def _mark_deleted(
    message: dict[str, Any], *, channel: str, account_id: str, user_id: str, at: datetime
) -> None:
    """O contato apagou a mensagem: o registro fica, marcado como apagado."""
    mid = str(message.get("mid") or "")
    stored = Message.objects.filter(channel=channel, external_id=mid).first() if mid else None
    if stored is not None:
        payload = stored.raw_payload if isinstance(stored.raw_payload, dict) else {}
        payload["deleted_at"] = at.isoformat()
        stored.raw_payload = payload
        stored.save(update_fields=["raw_payload"])
    identity = find_identity(channel, account_id, user_id)
    record_event(
        f"{channel}.message_deleted",
        contact=identity.contact if identity else None,
        channel=channel,
        external_id=mid,
        occurred_at=at,
        summary="Mensagem apagada pelo contato",
        data={"message_id": stored.pk if stored else None},
    )


def _apply_edit(edit: dict[str, Any], *, channel: str, at: datetime) -> None:
    """Texto editado pelo contato: guarda a versão anterior no histórico da mensagem."""
    mid = str(edit.get("mid") or "")
    stored = Message.objects.filter(channel=channel, external_id=mid).first() if mid else None
    if stored is None:
        logger.info("Edição de mensagem desconhecida em %s: %s", channel, mid)
        return
    new_text = str(edit.get("text") or "")
    payload = stored.raw_payload if isinstance(stored.raw_payload, dict) else {}
    edits = payload.setdefault("edits", [])
    entry = {"num_edit": edit.get("num_edit"), "previous": stored.body, "at": at.isoformat()}
    if any(item.get("num_edit") == entry["num_edit"] for item in edits):
        return
    edits.append(entry)
    stored.body = new_text
    stored.raw_payload = payload
    stored.save(update_fields=["body", "raw_payload"])
    record_event(
        f"{channel}.message_edited",
        contact=stored.conversation.contact,
        channel=channel,
        external_id=f"{mid}:{edit.get('num_edit', '')}",
        occurred_at=at,
        summary=new_text,
        data={"message_id": stored.pk, "previous": entry["previous"]},
    )


def _record_reaction(
    event: dict[str, Any], *, channel: str, account_id: str, user_id: str, at: datetime
) -> None:
    """Reação a uma mensagem: só evento na linha do tempo, sem mexer na conversa."""
    reaction = event["reaction"]
    mid = str(reaction.get("mid") or "")
    action = str(reaction.get("action") or "react")
    emoji = str(reaction.get("emoji") or reaction.get("reaction") or "")
    target = Message.objects.filter(channel=channel, external_id=mid).first() if mid else None
    identity = find_identity(channel, account_id, user_id)
    record_event(
        f"{channel}.reaction",
        contact=identity.contact if identity else None,
        channel=channel,
        external_id=f"{mid}:{user_id}:{event.get('timestamp', '')}",
        occurred_at=at,
        summary=f"{emoji} ({action})".strip(),
        data={"mid": mid, "action": action, "message_id": target.pk if target else None},
    )


def _record_referral(
    event: dict[str, Any], *, channel: str, account_id: str, user_id: str, at: datetime
) -> None:
    """Clique em link ig.me ou m.me com ref numa conversa existente."""
    if not user_id:
        return
    referral = event["referral"]
    identity = resolve_user(channel, account_id, user_id, seen_at=at, source=f"{channel}_referral")
    record_event(
        f"{channel}.referral",
        contact=identity.contact,
        channel=channel,
        external_id=f"referral:{user_id}:{event.get('timestamp', '')}",
        occurred_at=at,
        summary=str(referral.get("ref") or referral.get("source") or "referral"),
        data={"referral": referral},
    )


def _advance_outbound(
    receipt: dict[str, Any], new_status: str, *, channel: str, account_id: str, user_id: str
) -> int:
    """Leitura ou entrega: avança as mensagens enviadas ao contato até o ponto informado.

    O Messenger informa um watermark (tudo até aquele horário); o Instagram, o mid da
    mensagem lida, o que também vale para as anteriores. Retorna quantas mudaram.
    """
    identity = find_identity(channel, account_id, user_id)
    if identity is None:
        return 0
    outbound = Message.objects.filter(
        channel=channel,
        direction=MessageDirection.OUTBOUND,
        conversation__contact=identity.contact,
        conversation__account_id=account_id,
    )
    mids = [str(m) for m in receipt.get("mids") or []]
    if receipt.get("mid"):
        mids.append(str(receipt["mid"]))
    cutoff = parse_timestamp(receipt["watermark"]) if receipt.get("watermark") else None
    for anchor in outbound.filter(external_id__in=mids):
        cutoff = max(filter(None, [cutoff, anchor.created_at]))
    condition = Q(external_id__in=mids)
    if cutoff is not None:
        condition |= Q(created_at__lte=cutoff)
    changed = 0
    for message in outbound.filter(condition):
        if message.advance_status(new_status):
            message.save(update_fields=["status", "status_updated_at"])
            changed += 1
    return changed
