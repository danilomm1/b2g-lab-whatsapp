"""Testes dos templates do WhatsApp: catálogo, criação, sincronização, webhook e envio."""

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
    ConsentPurpose,
    Contact,
    Conversation,
    Event,
    MessageStatus,
)
from apps.core.services import grant_consent
from apps.whatsapp.models import MessageTemplate
from apps.whatsapp.services import SendBlocked, send_message
from apps.whatsapp.templates_catalog import (
    CATALOG_ENTRIES,
    QuickReply,
    TemplateError,
    TemplateSpec,
    get_template,
)

GRAPH = "https://graph.facebook.com/v26.0"


def test_catalog_entries_are_valid_and_unique() -> None:
    keys = [(spec.name, spec.language) for spec in CATALOG_ENTRIES]

    assert len(keys) == len(set(keys))
    assert all(
        spec.category in {"UTILITY", "MARKETING", "AUTHENTICATION"} for spec in CATALOG_ENTRIES
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "Nome Com Espaço"},
        {"body": "Olá, {{2}}!", "variables": ("nome",), "examples": ("Ana",)},
        {"body": "Olá, {{1}}!"},  # variável sem descrição nem exemplo
        {"quick_replies": (QuickReply("Um rótulo com mais de 25 letras", "x"),)},
    ],
)
def test_invalid_specs_are_rejected(kwargs: dict[str, Any]) -> None:
    base = {"name": "teste", "category": "UTILITY", "language": "pt_BR", "body": "Oi"}
    with pytest.raises(TemplateError):
        TemplateSpec(**(base | kwargs))


def test_creation_payload_has_examples_footer_and_quick_replies() -> None:
    payload = get_template("b2g_confirmacao_reuniao").creation_payload()

    assert payload["language"] == "pt_BR"
    assert payload["category"] == "UTILITY"
    assert payload["parameter_format"] == "POSITIONAL"
    body, footer, buttons = payload["components"]
    assert body["type"] == "BODY"
    assert body["example"] == {"body_text": [["Ana", "quinta-feira, 12/11, às 10h"]]}
    assert footer == {"type": "FOOTER", "text": "Brave2Grow"}
    assert [b["text"] for b in buttons["buttons"]] == ["Confirmo", "Reagendar", "Cancelar"]


def test_build_fills_variables_and_button_payloads() -> None:
    outbound = get_template("b2g_confirmacao_reuniao").build("Ana", "quinta, às 10h")

    template = outbound.data["template"]
    assert template["language"] == {"code": "pt_BR"}
    body, *buttons = template["components"]
    assert body["parameters"] == [
        {"type": "text", "text": "Ana"},
        {"type": "text", "text": "quinta, às 10h"},
    ]
    assert [(b["index"], b["parameters"][0]["payload"]) for b in buttons] == [
        ("0", "reuniao_confirmar"),
        ("1", "reuniao_reagendar"),
        ("2", "reuniao_cancelar"),
    ]
    assert outbound.body.startswith("Olá, Ana! Sua conversa com a Brave2Grow está marcada para")


def test_build_checks_number_of_variables() -> None:
    with pytest.raises(TemplateError, match="espera 2"):
        get_template("b2g_confirmacao_reuniao").build("Ana")
    assert get_template("hello_world").build().data["template"].get("components") is None


def test_unknown_template() -> None:
    with pytest.raises(TemplateError):
        get_template("nao_existe")


@pytest.mark.django_db
@respx.mock
def test_submit_command_creates_template_on_meta() -> None:
    route = respx.post(f"{GRAPH}/333/message_templates").mock(
        return_value=httpx.Response(
            200, json={"id": "987", "status": "PENDING", "category": "UTILITY"}
        )
    )
    out = StringIO()

    call_command("whatsapp_templates", "submit", "b2g_retomar_conversa", stdout=out)

    sent = json.loads(route.calls.last.request.content)
    assert sent["name"] == "b2g_retomar_conversa"
    stored = MessageTemplate.objects.get()
    assert (stored.status, stored.meta_id, stored.language) == ("PENDING", "987", "pt_BR")
    assert "enviado: PENDING" in out.getvalue()
    assert Event.objects.filter(event_type="whatsapp.template_submitted").exists()


@pytest.mark.django_db
def test_submit_refuses_meta_sample_and_requires_name() -> None:
    with pytest.raises(CommandError, match="exemplo da Meta"):
        call_command("whatsapp_templates", "submit", "hello_world", stdout=StringIO())
    with pytest.raises(CommandError, match="Informe o nome"):
        call_command("whatsapp_templates", "submit", stdout=StringIO())


@pytest.mark.django_db
@respx.mock
def test_sync_command_stores_meta_state_and_lists_catalog() -> None:
    respx.get(f"{GRAPH}/333/message_templates").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "1",
                        "name": "hello_world",
                        "language": "en_US",
                        "status": "APPROVED",
                        "category": "UTILITY",
                        "rejected_reason": "NONE",
                    },
                    {
                        "id": "2",
                        "name": "b2g_confirmacao_reuniao",
                        "language": "pt_BR",
                        "status": "REJECTED",
                        "category": "UTILITY",
                        "rejected_reason": "INVALID_FORMAT",
                    },
                    {
                        "id": "3",
                        "name": "jaspers_market_plain_text_v1",
                        "language": "en_US",
                        "status": "APPROVED",
                        "category": "MARKETING",
                    },
                ]
            },
        )
    )
    out = StringIO()

    call_command("whatsapp_templates", "sync", stdout=out)

    output = out.getvalue()
    assert "3 templates sincronizados" in output
    assert "hello_world [en_US] UTILITY: APPROVED (UTILITY)\n" in output  # sem "motivo: NONE"
    assert (
        "b2g_confirmacao_reuniao [pt_BR] UTILITY: REJECTED (UTILITY), motivo: INVALID_FORMAT"
        in (output)
    )
    assert "b2g_retomar_conversa [pt_BR] UTILITY: não enviado" in output
    assert "jaspers_market_plain_text_v1" in output.split("Só na Meta")[1]


def _status_webhook(event: str, reason: str = "NONE") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "333",
                "time": 1751247548,
                "changes": [
                    {
                        "field": "message_template_status_update",
                        "value": {
                            "event": event,
                            "message_template_id": 1689556908129832,
                            "message_template_name": "b2g_retomar_conversa",
                            "message_template_language": "pt-BR",
                            "reason": reason,
                            "message_template_category": "MARKETING",
                        },
                    }
                ],
            }
        ],
    }


@pytest.mark.django_db
def test_status_webhook_updates_template(meta_post: Any) -> None:
    MessageTemplate.objects.create(name="b2g_retomar_conversa", language="pt_BR", status="PENDING")

    meta_post(_status_webhook("APPROVED"))

    template = MessageTemplate.objects.get()
    assert (template.status, template.category, template.rejected_reason) == (
        "APPROVED",
        "MARKETING",
        "",
    )
    assert template.meta_id == "1689556908129832"
    assert Event.objects.get(event_type="whatsapp.template_status").summary == (
        "b2g_retomar_conversa [pt_BR] APPROVED"
    )


@pytest.mark.django_db
def test_rejection_reason_is_stored(meta_post: Any) -> None:
    meta_post(_status_webhook("REJECTED", reason="INCORRECT_CATEGORY"))

    template = MessageTemplate.objects.get()
    assert (template.status, template.rejected_reason) == ("REJECTED", "INCORRECT_CATEGORY")


def _contact_outside_window() -> Contact:
    contact = Contact.objects.create(name="Ana", phone="+5511987654321")
    Conversation.objects.create(
        contact=contact,
        channel=Channel.WHATSAPP,
        account_id="444",
        last_inbound_at=timezone.now() - timedelta(hours=30),
    )
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.SERVICE, source="teste")
    return contact


@pytest.mark.django_db
def test_template_not_approved_is_blocked_before_calling_meta() -> None:
    contact = _contact_outside_window()
    MessageTemplate.objects.create(name="b2g_retomar_conversa", language="pt_BR", status="REJECTED")

    with pytest.raises(SendBlocked, match="REJECTED"):
        send_message(contact, get_template("b2g_retomar_conversa").build("Ana"))


@pytest.mark.django_db
def test_approved_template_goes_out_of_window() -> None:
    contact = _contact_outside_window()
    MessageTemplate.objects.create(name="b2g_retomar_conversa", language="pt_BR", status="APPROVED")

    message = send_message(contact, get_template("b2g_retomar_conversa").build("Ana"))

    assert message.status == MessageStatus.SIMULATED
    assert message.is_proactive
    assert message.body.startswith("Olá, Ana! Aqui é o assistente automático da Brave2Grow.")
