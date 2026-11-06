"""Testes do envio pelo WhatsApp: montagem das mensagens, travas e chamadas mockadas."""

import json
from datetime import timedelta
from io import StringIO
from typing import Any

import httpx
import pytest
import respx
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.core.models import (
    Channel,
    ChannelIdentity,
    ConsentPurpose,
    Contact,
    Conversation,
    Event,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.core.services import grant_consent
from apps.whatsapp import payloads
from apps.whatsapp.payloads import InvalidPayload, ListRow, ListSection
from apps.whatsapp.services import SendBlocked, mark_as_read, send_message

GRAPH = "https://graph.facebook.com/v27.0"
MESSAGES_URL = f"{GRAPH}/444/messages"
PHONE = "+5511987654321"
BSUID = "BR.13491208655302741918"


@pytest.fixture
def real_sends(settings: Any) -> Any:
    """Desliga o dry-run e libera o telefone de teste na allowlist."""
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = [PHONE]
    return settings


def _contact(*, phone: str = PHONE, window_open: bool = True) -> tuple[Contact, Conversation]:
    contact = Contact.objects.create(name="Ana", phone=phone)
    conversation = Conversation.objects.create(
        contact=contact,
        channel=Channel.WHATSAPP,
        account_id="444",
        last_inbound_at=timezone.now() - timedelta(hours=1 if window_open else 30),
    )
    return contact, conversation


def _accepted(wamid: str = "wamid.OUT") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "messaging_product": "whatsapp",
            "contacts": [{"input": PHONE, "wa_id": "5511987654321"}],
            "messages": [{"id": wamid}],
        },
    )


# Montagem das mensagens


def test_text_payload() -> None:
    outbound = payloads.text("Oi, Ana")

    assert outbound.data == {"type": "text", "text": {"body": "Oi, Ana", "preview_url": False}}
    assert not outbound.is_template


def test_buttons_payload() -> None:
    outbound = payloads.buttons(
        "Quer agendar?", [("sim", "Sim"), ("nao", "Agora não")], footer="Brave2Grow"
    )

    interactive = outbound.data["interactive"]
    assert interactive["type"] == "button"
    assert interactive["action"]["buttons"][1] == {
        "type": "reply",
        "reply": {"id": "nao", "title": "Agora não"},
    }
    assert interactive["footer"] == {"text": "Brave2Grow"}


@pytest.mark.parametrize(
    "options",
    [
        [],
        [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        [("a", "Um título com mais de vinte")],
        [("a", "A"), ("a", "B")],
    ],
)
def test_buttons_limits(options: list[tuple[str, str]]) -> None:
    with pytest.raises(InvalidPayload):
        payloads.buttons("Escolha", options)


def test_list_payload() -> None:
    outbound = payloads.list_message(
        "Escolha um horário",
        "Ver horários",
        [
            ListSection(
                "", [ListRow("seg-10", "Segunda 10h", "30 min"), ListRow("ter-15", "Terça 15h")]
            )
        ],
    )

    action = outbound.data["interactive"]["action"]
    assert action["button"] == "Ver horários"
    assert action["sections"] == [
        {
            "rows": [
                {"id": "seg-10", "title": "Segunda 10h", "description": "30 min"},
                {"id": "ter-15", "title": "Terça 15h"},
            ]
        }
    ]


def test_list_limits() -> None:
    rows = [ListRow(f"r{i}", f"Linha {i}") for i in range(11)]
    with pytest.raises(InvalidPayload):
        payloads.list_message("Corpo", "Botão", [ListSection("", rows)])
    with pytest.raises(InvalidPayload):  # duas seções exigem título em cada uma
        payloads.list_message(
            "Corpo", "Botão", [ListSection("A", rows[:2]), ListSection("", rows[2:4])]
        )


def test_template_payload() -> None:
    outbound = payloads.template(
        "confirmacao_reuniao",
        components=[{"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}],
    )

    assert outbound.is_template
    assert outbound.data["template"]["language"] == {"code": "pt_BR"}
    assert outbound.body == "[template confirmacao_reuniao]"


# Travas de envio


@pytest.mark.django_db
@respx.mock
def test_dry_run_is_the_default_and_calls_nothing() -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=_accepted())
    contact, conversation = _contact()

    message = send_message(contact, payloads.text("Oi"))

    assert not route.called
    assert message.status == MessageStatus.SIMULATED
    assert message.conversation == conversation
    assert message.raw_payload["request"]["to"] == PHONE
    assert not message.is_proactive


@pytest.mark.django_db
def test_free_text_outside_window_is_blocked() -> None:
    contact, _ = _contact(window_open=False)

    with pytest.raises(SendBlocked, match="janela de 24h"):
        send_message(contact, payloads.text("Oi"))
    assert not Message.objects.exists()


@pytest.mark.django_db
def test_template_outside_window_needs_consent() -> None:
    contact, _ = _contact(window_open=False)

    with pytest.raises(SendBlocked, match="consentimento"):
        send_message(contact, payloads.template("hello_world", language="en_US"))


@pytest.mark.django_db
def test_template_outside_window_with_consent_is_proactive() -> None:
    contact, _ = _contact(window_open=False)
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.SERVICE, source="teste")

    message = send_message(contact, payloads.template("hello_world", language="en_US"))

    assert message.status == MessageStatus.SIMULATED
    assert message.is_proactive


@pytest.mark.django_db
def test_weekly_proactive_limit(settings: Any) -> None:
    settings.LAB_MAX_PROACTIVE_PER_WEEK = 1
    contact, conversation = _contact(window_open=False)
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")
    Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.OUTBOUND,
        status=MessageStatus.DELIVERED,
        is_proactive=True,
    )

    with pytest.raises(SendBlocked, match="limite"):
        send_message(contact, payloads.template("novidade"), purpose=ConsentPurpose.MARKETING)


@pytest.mark.django_db
def test_real_send_outside_allowlist_is_blocked(real_sends: Any) -> None:
    contact, _ = _contact(phone="+5521999990000")

    with pytest.raises(SendBlocked, match="LAB_ALLOWED_RECIPIENTS"):
        send_message(contact, payloads.text("Oi"))
    assert not Message.objects.exists()


@pytest.mark.django_db
@respx.mock
def test_real_send_stores_wamid_and_status_webhook_advances_it(
    real_sends: Any, meta_post: Any
) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=_accepted())
    contact, _ = _contact()

    message = send_message(contact, payloads.text("Oi, Ana"))

    assert json.loads(route.calls.last.request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": PHONE,
        "type": "text",
        "text": {"body": "Oi, Ana", "preview_url": False},
    }
    assert (message.status, message.external_id) == (MessageStatus.QUEUED, "wamid.OUT")

    meta_post(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "333",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "444"},
                                "statuses": [
                                    {"id": "wamid.OUT", "status": "delivered", "timestamp": "1"}
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )
    message.refresh_from_db()
    assert message.status == MessageStatus.DELIVERED


@pytest.mark.django_db
@respx.mock
def test_contact_without_phone_is_reached_by_bsuid(real_sends: Any) -> None:
    real_sends.LAB_ALLOWED_RECIPIENTS = [BSUID]
    route = respx.post(MESSAGES_URL).mock(return_value=_accepted())
    contact, _ = _contact(phone="")
    ChannelIdentity.objects.create(
        contact=contact, channel=Channel.WHATSAPP, account_id="333", external_id=BSUID
    )

    send_message(contact, payloads.text("Oi"))

    request = json.loads(route.calls.last.request.content)
    assert request["recipient"] == BSUID
    assert "to" not in request


@pytest.mark.django_db
def test_contact_without_phone_or_bsuid_is_blocked() -> None:
    contact, _ = _contact(phone="")

    with pytest.raises(SendBlocked, match="nem BSUID"):
        send_message(contact, payloads.text("Oi"))


@pytest.mark.django_db
@respx.mock
def test_api_error_is_recorded_as_failed_message(real_sends: Any) -> None:
    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "(#131030) Recipient phone number not in allowed list",
                    "code": 131030,
                    "fbtrace_id": "Abc",
                }
            },
        )
    )
    contact, _ = _contact()

    message = send_message(contact, payloads.text("Oi"))

    assert message.status == MessageStatus.FAILED
    assert message.error["code"] == 131030
    assert Event.objects.get(event_type="whatsapp.message_failed").contact == contact


def _inbound(contact: Contact, conversation: Conversation) -> Message:
    return Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.INBOUND,
        external_id="wamid.IN",
        status=MessageStatus.RECEIVED,
    )


@pytest.mark.django_db
@respx.mock
def test_mark_as_read_respects_dry_run() -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={}))
    contact, conversation = _contact()

    assert not mark_as_read(_inbound(contact, conversation), typing=True)
    assert not route.called


@pytest.mark.django_db
@respx.mock
def test_mark_as_read_with_typing_indicator(real_sends: Any) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"success": True}))
    contact, conversation = _contact()

    assert mark_as_read(_inbound(contact, conversation), typing=True)
    assert json.loads(route.calls.last.request.content) == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN",
        "typing_indicator": {"type": "text"},
    }


# Comandos


def _mock_check_endpoints(app_id: str = "1234567890") -> None:
    respx.get(f"{GRAPH}/444").mock(
        return_value=httpx.Response(
            200,
            json={
                "display_phone_number": "15550783881",
                "verified_name": "Test Number",
                "quality_rating": "GREEN",
                "throughput": {"level": "STANDARD"},
            },
        )
    )
    respx.get(f"{GRAPH}/333/subscribed_apps").mock(
        return_value=httpx.Response(
            200, json={"data": [{"whatsapp_business_api_data": {"id": app_id, "name": "Lab"}}]}
        )
    )
    respx.get(f"{GRAPH}/333/message_templates").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "name": "hello_world",
                        "language": "en_US",
                        "category": "UTILITY",
                        "status": "APPROVED",
                    }
                ]
            },
        )
    )


@respx.mock
def test_whatsapp_check_reports_number_apps_and_templates() -> None:
    _mock_check_endpoints()
    out = StringIO()

    call_command("whatsapp_check", stdout=out)

    output = out.getvalue()
    assert "Test Number" in output
    assert "Lab (1234567890)" in output
    assert "hello_world [en_US] UTILITY APPROVED" in output


@respx.mock
def test_whatsapp_check_fails_when_app_is_not_subscribed() -> None:
    _mock_check_endpoints(app_id="999")

    with pytest.raises(CommandError, match="não está pronto"):
        call_command("whatsapp_check", stdout=StringIO())


def test_whatsapp_check_requires_ids(settings: Any) -> None:
    settings.WHATSAPP_PHONE_NUMBER_ID = ""

    with pytest.raises(CommandError, match="Configuração da API"):
        call_command("whatsapp_check", stdout=StringIO())


@pytest.mark.django_db
def test_send_test_requires_known_contact() -> None:
    with pytest.raises(CommandError, match="Nenhum contato"):
        call_command("whatsapp_send_test", "--to", PHONE, "--text", "Oi", stdout=StringIO())


@pytest.mark.django_db
def test_send_test_simulates_by_default() -> None:
    _contact()
    out = StringIO()

    call_command("whatsapp_send_test", "--to", "11987654321", "--text", "Oi", stdout=out)

    assert "simulado" in out.getvalue()
    assert Message.objects.get().status == MessageStatus.SIMULATED


@pytest.mark.django_db
def test_send_test_reports_block() -> None:
    _contact(window_open=False)

    with pytest.raises(CommandError, match="janela de 24h"):
        call_command("whatsapp_send_test", "--to", PHONE, "--text", "Oi", stdout=StringIO())
