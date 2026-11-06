"""Telas de teste das conversas do WhatsApp: ler a conversa e responder pelo laboratório.

É uma versão só do WhatsApp; a caixa de entrada unificada é a Fase 8 (app inbox).
Todo envio passa por services.send_message, com as mesmas travas dos fluxos.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Max
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Channel, Conversation, MessageDirection, MessageStatus

from . import payloads
from .payloads import InvalidPayload, OutboundPayload
from .services import SendBlocked, send_message

THREAD_LIMIT = 100

STATUS_TONES = {
    MessageStatus.SIMULATED: "neutral",
    MessageStatus.QUEUED: "neutral",
    MessageStatus.SENT: "ok",
    MessageStatus.DELIVERED: "ok",
    MessageStatus.READ: "ok",
    MessageStatus.FAILED: "danger",
}

# Mensagem com botões para testar o caminho de ida e volta das respostas interativas
TEST_BUTTONS = payloads.buttons(
    "Teste do laboratório: toque em uma opção para ver a resposta chegar.",
    [("teste_sim", "Sim"), ("teste_nao", "Não"), ("teste_talvez", "Talvez")],
    footer="B2G Integrations Lab",
)


def _error_text(error: object) -> str:
    """Erro legível: da chamada à API (message) ou do webhook de status (errors[0])."""
    if not isinstance(error, dict) or not error:
        return ""
    if error.get("message"):
        return str(error["message"])
    first = (error.get("errors") or [{}])[0]
    if isinstance(first, dict):
        return f"{first.get('code', '')} {first.get('title') or first.get('message', '')}".strip()
    return ""


def _whatsapp_conversations():
    return Conversation.objects.filter(channel=Channel.WHATSAPP).select_related("contact")


def _thread_context(conversation: Conversation, *, feedback: str = "", tone: str = "") -> dict:
    thread = list(conversation.messages.order_by("-created_at")[:THREAD_LIMIT])
    thread.reverse()
    for message in thread:
        message.is_outbound = message.direction == MessageDirection.OUTBOUND
        message.tone = STATUS_TONES.get(message.status, "neutral")
        payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
        message.reply_id = payload.get("reply_id", "")
        message.error_text = _error_text(message.error)
    return {
        "conversation": conversation,
        "thread": thread,
        "window_open": conversation.is_service_window_open(),
        "feedback": feedback,
        "feedback_tone": tone,
    }


@staff_member_required
def conversation_list(request: HttpRequest) -> HttpResponse:
    """Conversas do WhatsApp, da mais recente para a mais antiga."""
    conversations = list(
        _whatsapp_conversations()
        .annotate(total=Count("messages"), last_at=Max("messages__created_at"))
        .order_by("-last_message_at", "-created_at")
    )
    for conversation in conversations:
        conversation.window_open = conversation.is_service_window_open()
    return render(request, "whatsapp/conversation_list.html", {"conversations": conversations})


@staff_member_required
def conversation_detail(request: HttpRequest, pk: int) -> HttpResponse:
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    return render(request, "whatsapp/conversation_detail.html", _thread_context(conversation))


@staff_member_required
def conversation_thread(request: HttpRequest, pk: int) -> HttpResponse:
    """Parcial das mensagens, atualizada pelo HTMX a cada 5 segundos."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    return render(request, "whatsapp/partials/thread.html", _thread_context(conversation))


def _send(request: HttpRequest, conversation: Conversation, outbound: OutboundPayload):
    """Envia e devolve (texto, tom) para o aviso abaixo da conversa."""
    try:
        message = send_message(conversation.contact, outbound, conversation=conversation)
    except SendBlocked as exc:
        return f"Envio bloqueado: {exc}", "warn"
    if message.status == MessageStatus.FAILED:
        return f"A Graph API recusou: {message.error.get('message', '')}", "danger"
    if message.status == MessageStatus.SIMULATED:
        return "Simulada: LAB_DRY_RUN está ativo, nada saiu de verdade.", "neutral"
    return "Enviada para a Meta. O status muda quando o webhook avisar.", "ok"


def _respond(request: HttpRequest, conversation: Conversation, feedback: str, tone: str):
    if request.htmx:
        context = _thread_context(conversation, feedback=feedback, tone=tone)
        return render(request, "whatsapp/partials/thread.html", context)
    level = messages.SUCCESS if tone == "ok" else messages.WARNING
    messages.add_message(request, level, feedback)
    return redirect("whatsapp:conversation_detail", pk=conversation.pk)


@staff_member_required
@require_POST
def reply(request: HttpRequest, pk: int) -> HttpResponse:
    """Responde com texto livre (só dentro da janela de 24h)."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    body = request.POST.get("body", "").strip()
    try:
        outbound = payloads.text(body)
    except InvalidPayload as exc:
        return _respond(request, conversation, str(exc), "warn")
    return _respond(request, conversation, *_send(request, conversation, outbound))


@staff_member_required
@require_POST
def send_test_buttons(request: HttpRequest, pk: int) -> HttpResponse:
    """Manda a mensagem de teste com três botões de resposta."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    return _respond(request, conversation, *_send(request, conversation, TEST_BUTTONS))
