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
import mimetypes
import time
from pathlib import Path
from typing import Any

from django.conf import settings
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

from . import payloads
from .client import WhatsAppClient, default_phone_number_id
from .inbound import MEDIA_KINDS, open_conversation
from .models import MessageTemplate
from .payloads import OutboundPayload

logger = logging.getLogger(__name__)


SIMULATED_WAMID_PREFIX = "wamid.simulado."


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

    if outbound.is_template:
        _check_template_status(outbound)
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


def _check_template_status(outbound: OutboundPayload) -> None:
    """Barra template sabidamente não aprovado; sem registro local, deixa a Meta decidir."""
    data = outbound.data.get("template", {})
    stored = MessageTemplate.objects.filter(
        name=data.get("name", ""), language=data.get("language", {}).get("code", "")
    ).first()
    if stored is not None and not stored.is_approved:
        raise SendBlocked(f"Template {stored.name} [{stored.language}] está {stored.status}")


def deliver_outbox(
    conversation_id: int,
    items: list[dict[str, Any]],
    *,
    reply_to_id: int | None = None,
    client: WhatsAppClient | None = None,
) -> list[Message]:
    """Envia em ordem as mensagens decididas pelo motor de fluxo (tarefa send_outbox).

    Antes, marca a mensagem recebida como lida e mostra "digitando...". Entre um envio e
    outro espera WHATSAPP_FLOW_SEND_DELAY segundos, porque a Meta não garante a ordem de
    entrega. Um bloqueio interrompe o resto da caixa e vira evento.
    """
    conversation = Conversation.objects.select_related("contact").get(pk=conversation_id)
    if reply_to_id:
        reply_to = Message.objects.filter(pk=reply_to_id).first()
        # Mensagem simulada (whatsapp_simulate_reply) não existe na Meta para ser marcada
        if reply_to and not reply_to.external_id.startswith(SIMULATED_WAMID_PREFIX):
            mark_as_read(reply_to, typing=True, client=client)
    sent: list[Message] = []
    for index, item in enumerate(items):
        if index and settings.WHATSAPP_FLOW_SEND_DELAY:
            time.sleep(settings.WHATSAPP_FLOW_SEND_DELAY)
        try:
            sent.append(
                send_message(
                    conversation.contact,
                    OutboundPayload(**item),
                    conversation=conversation,
                    client=client,
                )
            )
        except SendBlocked as exc:
            record_event(
                "whatsapp.flow_send_blocked",
                contact=conversation.contact,
                channel=Channel.WHATSAPP,
                summary=str(exc)[:255],
                data={"conversation_id": conversation_id, "pending": items[index:]},
            )
            break
    return sent


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


def store_inbound_media(message_id: int, *, client: WhatsAppClient | None = None) -> str:
    """Baixa a mídia de uma mensagem recebida para WHATSAPP_MEDIA_DIR. Retorna o caminho.

    Idempotente: se o arquivo já foi baixado, não chama a Meta de novo.
    """
    message = Message.objects.select_related("conversation").get(pk=message_id)
    payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
    stored = payload.get("media") or {}
    if stored.get("path") and (Path(settings.WHATSAPP_MEDIA_DIR) / stored["path"]).exists():
        return stored["path"]
    raw_message = payload.get("message") or {}
    media_id = str((raw_message.get(message.kind) or {}).get("id", ""))
    if message.kind not in MEDIA_KINDS or not media_id:
        return ""
    own_client = client is None
    client = client or WhatsAppClient(message.conversation.account_id or None)
    try:
        content, info = client.download_media(media_id)
    finally:
        if own_client:
            client.close()
    mime_type = str(info.get("mime_type", "")).split(";")[0]
    extension = mimetypes.guess_extension(mime_type) or ".bin"
    relative = f"{message.created_at:%Y/%m}/{message.pk}-{media_id[-8:]}{extension}"
    target = Path(settings.WHATSAPP_MEDIA_DIR) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    payload["media"] = {
        "id": media_id,
        "mime_type": mime_type,
        "sha256": info.get("sha256", ""),
        "file_size": len(content),
        "path": relative,
    }
    message.raw_payload = payload
    message.save(update_fields=["raw_payload"])
    return relative


def send_media(
    contact: Contact,
    content: bytes,
    mime_type: str,
    filename: str,
    *,
    caption: str = "",
    conversation: Conversation | None = None,
    dry_run: bool | None = None,
    client: WhatsAppClient | None = None,
) -> Message:
    """Envia um arquivo como imagem, áudio, vídeo ou documento, conforme o tipo.

    Os limites de tipo e tamanho são conferidos antes. No dry-run (ou fora da allowlist),
    nada sobe para a Meta: a mensagem fica simulada ou o envio é barrado por send_message.
    """
    kind = payloads.media_kind_for(mime_type)
    payloads.check_media(kind, mime_type, len(content))
    caption = "" if kind == "audio" else caption
    decision = check_outbound(next(iter(recipient_fields(contact).values())), dry_run=dry_run)
    if not decision.send_for_real:
        outbound = payloads.media(kind, media_id="simulado", caption=caption, filename=filename)
        return send_message(
            contact, outbound, conversation=conversation, dry_run=dry_run, client=client
        )
    own_client = client is None
    phone_number_id = conversation.account_id if conversation else None
    client = client or WhatsAppClient(phone_number_id or None)
    try:
        media_id = client.upload_media(content, mime_type, filename)
        outbound = payloads.media(kind, media_id=media_id, caption=caption, filename=filename)
        return send_message(
            contact, outbound, conversation=conversation, dry_run=dry_run, client=client
        )
    finally:
        if own_client:
            client.close()


def owner_notifications(
    contact: Contact, summary: str, answers: dict[str, Any]
) -> list[tuple[Conversation, OutboundPayload]]:
    """Avisos de handoff para os números de OWNER_WHATSAPP_NUMBERS com janela aberta.

    Sem janela aberta, o aviso só pode ir por template aprovado; até lá, fica o evento no
    painel. O Console CEO (Fase 9) amplia esses avisos.
    """
    who = contact.name or contact.phone or f"contato #{contact.pk}"
    lines = [f"Aviso do laboratório: {who} pediu atendimento humano no WhatsApp."]
    if contact.phone:
        lines.append(f"Telefone: {contact.phone}")
    lines.append(f"Motivo: {summary}")
    if answers:
        lines.append("Respostas: " + "; ".join(f"{k}: {v}" for k, v in answers.items()))
    lines.append("Responda pela tela Conversas do laboratório.")
    text = payloads.text("\n".join(lines))
    notices = []
    for number in settings.OWNER_WHATSAPP_NUMBERS:
        owner = Contact.objects.filter(phone=number.strip()).first()
        conversation = (
            owner.conversations.filter(channel=Channel.WHATSAPP)
            .order_by("-last_inbound_at")
            .first()
            if owner
            else None
        )
        if conversation and conversation.is_service_window_open():
            notices.append((conversation, text))
        else:
            record_event(
                "whatsapp.owner_notice_skipped",
                contact=contact,
                channel=Channel.WHATSAPP,
                summary=f"Aviso de handoff para {number} sem janela aberta; ficou só no painel",
            )
    return notices
