"""Telas de teste das conversas do WhatsApp: ler a conversa e responder pelo laboratório.

É uma versão só do WhatsApp; a caixa de entrada unificada é a Fase 8 (app inbox).
Todo envio passa por services.send_message, com as mesmas travas dos fluxos.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Max
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.models import (
    Channel,
    Conversation,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.meta_business.client import GraphAPIError

from . import payloads
from .flows import FLOWS, release_handoff
from .flows.engine import open_run, start_by_agent
from .payloads import InvalidPayload, ListRow, ListSection, OutboundPayload
from .services import SendBlocked, send_media, send_message

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
# Lista com duas seções, para testar a resposta list_reply e os títulos de seção
TEST_LIST = payloads.list_message(
    "Teste do laboratório: escolha um horário na lista para ver a resposta chegar.",
    "Ver horários",
    [
        ListSection(
            "Esta semana",
            [
                ListRow("teste_seg_10", "Segunda, 10h", "30 minutos"),
                ListRow("teste_qua_15", "Quarta, 15h", "30 minutos"),
            ],
        ),
        ListSection(
            "Próxima semana",
            [ListRow("teste_ter_09", "Terça, 9h", "45 minutos")],
        ),
    ],
    footer="B2G Integrations Lab",
)
TEST_IMAGE = Path(__file__).resolve().parent / "static" / "whatsapp" / "imagem-teste.png"


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
        media = payload.get("media") or {}
        message.media_url = (
            reverse("whatsapp:media", args=[conversation.pk, message.pk])
            if media.get("path")
            else ""
        )
        message.media_is_image = str(media.get("mime_type", "")).startswith("image/")
    run = open_run(conversation)
    flow = FLOWS.get(run.flow_key) if run else None
    return {
        "conversation": conversation,
        "run": run,
        "flow_name": flow.name if flow else (run.flow_key if run else ""),
        "answers": (run.state or {}).get("answers", {}) if run else {},
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
    return _attempt(lambda: send_message(conversation.contact, outbound, conversation=conversation))


def _attempt(send: Callable[[], Message]) -> tuple[str, str]:
    try:
        message = send()
    except SendBlocked as exc:
        return f"Envio bloqueado: {exc}", "warn"
    except InvalidPayload as exc:
        return str(exc), "warn"
    except GraphAPIError as exc:
        return f"A Graph API recusou o arquivo: {exc}", "danger"
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
    """Responde com texto livre ou com um arquivo (só dentro da janela de 24h)."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    body = request.POST.get("body", "").strip()
    attachment = request.FILES.get("attachment")
    if attachment:
        content = attachment.read()
        mime_type = attachment.content_type or "application/octet-stream"
        feedback = _attempt(
            lambda: send_media(
                conversation.contact,
                content,
                mime_type,
                attachment.name,
                caption=body,
                conversation=conversation,
            )
        )
        return _respond(request, conversation, *feedback)
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


@staff_member_required
@require_POST
def give_back_to_assistant(request: HttpRequest, pk: int) -> HttpResponse:
    """Encerra o atendimento humano: a próxima mensagem do contato volta ao fluxo."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    released = release_handoff(conversation)
    conversation.refresh_from_db()
    feedback = (
        "Conversa devolvida ao assistente."
        if released
        else "Não havia atendimento humano em andamento."
    )
    return _respond(request, conversation, feedback, "ok" if released else "neutral")


@staff_member_required
@require_POST
def send_test_list(request: HttpRequest, pk: int) -> HttpResponse:
    """Manda a mensagem de teste com lista de duas seções."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    return _respond(request, conversation, *_send(request, conversation, TEST_LIST))


@staff_member_required
@require_POST
def send_test_image(request: HttpRequest, pk: int) -> HttpResponse:
    """Manda a imagem de teste do laboratório (sobe para a Meta e envia pelo ID)."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    content = TEST_IMAGE.read_bytes()
    feedback = _attempt(
        lambda: send_media(
            conversation.contact,
            content,
            "image/png",
            TEST_IMAGE.name,
            caption="Imagem de teste do B2G Integrations Lab",
            conversation=conversation,
        )
    )
    return _respond(request, conversation, *feedback)


@staff_member_required
@require_POST
def start_registration(request: HttpRequest, pk: int) -> HttpResponse:
    """Inicia o fluxo de cadastro pelo formulário nativo (WhatsApp Flow) nesta conversa."""
    conversation = get_object_or_404(_whatsapp_conversations(), pk=pk)
    if not conversation.is_service_window_open():
        feedback = "Fora da janela de 24h: não dá para abrir o formulário."
        return _respond(request, conversation, feedback, "warn")
    outbox = start_by_agent(conversation, "cadastro")
    feedback = (
        "Cadastro iniciado: o formulário foi para a fila de envio."
        if outbox
        else "O fluxo de cadastro não gerou mensagem."
    )
    return _respond(request, conversation, feedback, "ok" if outbox else "warn")


@staff_member_required
def media(request: HttpRequest, pk: int, message_pk: int) -> FileResponse:
    """Arquivo de uma mídia recebida, servido só a staff (nunca como estático público)."""
    message = get_object_or_404(Message, pk=message_pk, conversation_id=pk)
    stored = (message.raw_payload or {}).get("media") or {}
    base = Path(settings.WHATSAPP_MEDIA_DIR).resolve()
    path = (base / str(stored.get("path", ""))).resolve()
    if not stored.get("path") or base not in path.parents or not path.is_file():
        raise Http404("Mídia não encontrada")
    return FileResponse(path.open("rb"), content_type=stored.get("mime_type") or None)
