"""Testes das telas de conversa do WhatsApp: leitura, resposta e botões de teste."""

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Channel,
    Contact,
    Conversation,
    Message,
    MessageDirection,
    MessageStatus,
)

PHONE = "+5511987654321"
HTMX = {"HX-Request": "true"}


def _conversation(*, window_open: bool = True) -> Conversation:
    contact = Contact.objects.create(name="Ana", phone=PHONE)
    conversation = Conversation.objects.create(
        contact=contact,
        channel=Channel.WHATSAPP,
        account_id="444",
        last_inbound_at=timezone.now() - timedelta(hours=1 if window_open else 30),
    )
    Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.INBOUND,
        body="Oi, tudo bem?",
        external_id="wamid.IN",
        status=MessageStatus.RECEIVED,
    )
    return conversation


@pytest.mark.django_db
def test_pages_require_staff(client: Client) -> None:
    conversation = _conversation()

    for url in (
        reverse("whatsapp:conversation_list"),
        reverse("whatsapp:conversation_detail", args=[conversation.pk]),
    ):
        response = client.get(url)
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("admin:login"))
    assert (
        client.post(reverse("whatsapp:reply", args=[conversation.pk]), {"body": "x"}).status_code
        == 302
    )
    assert not Message.objects.filter(direction=MessageDirection.OUTBOUND).exists()


@pytest.mark.django_db
def test_list_shows_conversation_and_window(admin_client: Client) -> None:
    _conversation()

    content = admin_client.get(reverse("whatsapp:conversation_list")).content.decode()

    assert "Ana" in content
    assert "1 mensagem" in content
    assert "janela de 24h aberta" in content


@pytest.mark.django_db
def test_detail_shows_thread_and_reply_form(admin_client: Client) -> None:
    conversation = _conversation()

    content = admin_client.get(
        reverse("whatsapp:conversation_detail", args=[conversation.pk])
    ).content.decode()

    assert "Oi, tudo bem?" in content
    assert reverse("whatsapp:reply", args=[conversation.pk]) in content
    assert reverse("whatsapp:conversation_thread", args=[conversation.pk]) in content


@pytest.mark.django_db
def test_reply_in_dry_run_is_simulated(admin_client: Client) -> None:
    conversation = _conversation()

    response = admin_client.post(
        reverse("whatsapp:reply", args=[conversation.pk]), {"body": "Tudo ótimo!"}, headers=HTMX
    )

    content = response.content.decode()
    assert "Tudo ótimo!" in content
    assert "Simulada" in content
    sent = Message.objects.get(direction=MessageDirection.OUTBOUND)
    assert (sent.body, sent.status) == ("Tudo ótimo!", MessageStatus.SIMULATED)


@pytest.mark.django_db
def test_reply_outside_window_is_blocked(admin_client: Client) -> None:
    conversation = _conversation(window_open=False)

    response = admin_client.post(
        reverse("whatsapp:reply", args=[conversation.pk]), {"body": "Oi"}, headers=HTMX
    )

    assert "Envio bloqueado" in response.content.decode()
    assert not Message.objects.filter(direction=MessageDirection.OUTBOUND).exists()


@pytest.mark.django_db
def test_empty_reply_is_rejected(admin_client: Client) -> None:
    conversation = _conversation()

    response = admin_client.post(
        reverse("whatsapp:reply", args=[conversation.pk]), {"body": "  "}, headers=HTMX
    )

    assert "não pode ficar vazio" in response.content.decode()
    assert not Message.objects.filter(direction=MessageDirection.OUTBOUND).exists()


@pytest.mark.django_db
def test_reply_without_htmx_redirects_back(admin_client: Client) -> None:
    conversation = _conversation()

    response = admin_client.post(reverse("whatsapp:reply", args=[conversation.pk]), {"body": "Oi"})

    assert response.status_code == 302
    assert response["Location"] == reverse("whatsapp:conversation_detail", args=[conversation.pk])


@pytest.mark.django_db
@respx.mock
def test_real_reply_and_test_buttons_go_to_the_api(admin_client: Client, settings: Any) -> None:
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = [PHONE]
    route = respx.post("https://graph.facebook.com/v26.0/444/messages").mock(
        side_effect=[
            httpx.Response(200, json={"messages": [{"id": "wamid.TXT"}]}),
            httpx.Response(200, json={"messages": [{"id": "wamid.BTN"}]}),
        ]
    )
    conversation = _conversation()

    admin_client.post(
        reverse("whatsapp:reply", args=[conversation.pk]), {"body": "Oi, Ana"}, headers=HTMX
    )
    response = admin_client.post(
        reverse("whatsapp:send_test_buttons", args=[conversation.pk]), headers=HTMX
    )

    assert "Enviada para a Meta" in response.content.decode()
    buttons_request = json.loads(route.calls[1].request.content)
    assert buttons_request["type"] == "interactive"
    assert [b["reply"]["id"] for b in buttons_request["interactive"]["action"]["buttons"]] == [
        "teste_sim",
        "teste_nao",
        "teste_talvez",
    ]
    assert set(
        Message.objects.filter(direction=MessageDirection.OUTBOUND).values_list(
            "external_id", flat=True
        )
    ) == {"wamid.TXT", "wamid.BTN"}


@pytest.mark.django_db
def test_failed_status_error_is_readable(admin_client: Client) -> None:
    conversation = _conversation()
    Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.OUTBOUND,
        body="Oi",
        status=MessageStatus.FAILED,
        error={"errors": [{"code": 131047, "title": "Re-engagement message"}]},
    )

    content = admin_client.get(
        reverse("whatsapp:conversation_thread", args=[conversation.pk])
    ).content.decode()

    assert "131047 Re-engagement message" in content
