"""Testes de mídia, formulários nativos (WhatsApp Flows), aviso ao dono e simulação de resposta."""

import itertools
import json
import time
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Channel,
    ChannelIdentity,
    ConsentPurpose,
    Contact,
    Conversation,
    ConversationStatus,
    Event,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.meta_business.webhook import SIGNATURE_HEADER
from apps.webhooks.signatures import verify_hmac_sha256
from apps.whatsapp import payloads
from apps.whatsapp.forms_catalog import CADASTRO, FormError, FormSpec, get_form
from apps.whatsapp.inbound import extract_content
from apps.whatsapp.models import FlowRun, FlowRunStatus, WhatsAppForm
from apps.whatsapp.payloads import InvalidPayload
from apps.whatsapp.services import send_media, store_inbound_media

GRAPH = "https://graph.facebook.com/v27.0"
PHONE = "+5511987654321"
BSUID = "BR.13491208655302741918"
OWNER = "+5521999990000"
_ids = itertools.count(1)


@pytest.fixture
def media_dir(settings: Any, tmp_path: Path) -> Path:
    settings.WHATSAPP_MEDIA_DIR = tmp_path / "media"
    return settings.WHATSAPP_MEDIA_DIR


@pytest.fixture
def real_sends(settings: Any) -> Any:
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = [PHONE, OWNER]
    return settings


def _envelope(message: dict[str, Any], *, name: str = "Ana Souza", wa_id: str = "5511987654321"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "333",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "444"},
                            "contacts": [
                                {"profile": {"name": name}, "wa_id": wa_id, "user_id": BSUID}
                            ],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def _message(**content: Any) -> dict[str, Any]:
    return {
        "from": "5511987654321",
        "from_user_id": BSUID,
        "id": f"wamid.mf.{next(_ids)}",
        "timestamp": str(int(time.time())),
        **content,
    }


def _replies() -> list[Message]:
    return list(Message.objects.filter(direction=MessageDirection.OUTBOUND).order_by("pk"))


def _conversation(phone: str = PHONE, *, window_open: bool = True) -> Conversation:
    contact = Contact.objects.create(name="Ana", phone=phone)
    return Conversation.objects.create(
        contact=contact,
        channel=Channel.WHATSAPP,
        account_id="444",
        last_inbound_at=timezone.now() - timedelta(hours=1 if window_open else 30),
    )


# Montagem de mídia e formulário


def test_media_payloads() -> None:
    image = payloads.media("image", media_id="m1", caption="Logo")
    assert image.data == {"type": "image", "image": {"id": "m1", "caption": "Logo"}}
    document = payloads.media("document", link="https://x/y.pdf", filename="y.pdf")
    assert document.data["document"] == {"link": "https://x/y.pdf", "filename": "y.pdf"}
    with pytest.raises(InvalidPayload):
        payloads.media("image", media_id="m1", link="https://x")
    with pytest.raises(InvalidPayload):
        payloads.media("audio", media_id="m1", caption="sem legenda em áudio")


@pytest.mark.parametrize(
    ("mime", "kind"),
    [
        ("image/png", "image"),
        ("audio/ogg", "audio"),
        ("video/mp4", "video"),
        ("application/pdf", "document"),
        ("image/gif", "document"),
    ],
)
def test_media_kind_for(mime: str, kind: str) -> None:
    assert payloads.media_kind_for(mime) == kind


def test_media_size_limit() -> None:
    with pytest.raises(InvalidPayload, match="limite"):
        payloads.check_media("image", "image/png", 6 * 1024 * 1024)


def test_form_payload() -> None:
    outbound = payloads.form(
        "Preencha", "Preencher", flow_id="77", token="1:formulario", screen="CADASTRO"
    )

    parameters = outbound.data["interactive"]["action"]["parameters"]
    assert outbound.data["interactive"]["type"] == "flow"
    assert parameters == {
        "flow_message_version": "3",
        "flow_token": "1:formulario",
        "flow_id": "77",
        "flow_cta": "Preencher",
        "flow_action": "navigate",
        "flow_action_payload": {"screen": "CADASTRO"},
        "mode": "published",
    }


def test_form_catalog_validation() -> None:
    assert get_form("b2g_cadastro") is CADASTRO
    assert json.loads(CADASTRO.flow_json_text())["screens"][0]["id"] == "CADASTRO"
    with pytest.raises(FormError):
        FormSpec("x", ("INVALIDA",), "A", {"screens": [{"id": "A"}]})
    with pytest.raises(FormError):
        FormSpec("x", ("OTHER",), "SUCCESS", {"screens": [{"id": "SUCCESS"}]})
    with pytest.raises(FormError):
        get_form("nao_existe")


# Mídia


@pytest.mark.django_db
@respx.mock
def test_inbound_image_is_downloaded_and_served_to_staff(
    meta_post: Any, media_dir: Path, admin_client: Client, client: Client
) -> None:
    respx.get(f"{GRAPH}/media-123").mock(
        return_value=httpx.Response(
            200,
            json={
                "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
                "mime_type": "image/jpeg",
                "sha256": "abc",
                "file_size": 4,
                "id": "media-123",
            },
        )
    )
    download = respx.get("https://lookaside.fbsbx.com/whatsapp_business/attachments/").mock(
        return_value=httpx.Response(200, content=b"JPEG", headers={"Content-Type": "image/jpeg"})
    )

    meta_post(_envelope(_message(type="image", image={"id": "media-123", "caption": "Meu logo"})))

    assert download.calls.last.request.headers["Authorization"].startswith("Bearer ")
    message = Message.objects.get(direction=MessageDirection.INBOUND)
    stored = message.raw_payload["media"]
    assert stored["mime_type"] == "image/jpeg"
    assert (media_dir / stored["path"]).read_bytes() == b"JPEG"
    url = reverse("whatsapp:media", args=[message.conversation_id, message.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"JPEG"
    assert client.get(url).status_code == 302  # anônimo vai para o login
    detail = admin_client.get(
        reverse("whatsapp:conversation_thread", args=[message.conversation_id])
    ).content.decode()
    assert url in detail


@pytest.mark.django_db
def test_media_view_refuses_paths_outside_media_dir(admin_client: Client, media_dir: Path) -> None:
    conversation = _conversation()
    message = Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.INBOUND,
        kind="document",
        status=MessageStatus.RECEIVED,
        raw_payload={"media": {"path": "../../.env", "mime_type": "text/plain"}},
    )

    response = admin_client.get(reverse("whatsapp:media", args=[conversation.pk, message.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
@respx.mock
def test_store_inbound_media_is_idempotent(media_dir: Path) -> None:
    respx.get(f"{GRAPH}/m9").mock(
        return_value=httpx.Response(
            200, json={"url": "https://lookaside.fbsbx.com/x", "mime_type": "audio/ogg"}
        )
    )
    route = respx.get("https://lookaside.fbsbx.com/x").mock(
        return_value=httpx.Response(200, content=b"OGG")
    )
    conversation = _conversation()
    message = Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.INBOUND,
        kind="audio",
        status=MessageStatus.RECEIVED,
        raw_payload={"message": {"type": "audio", "audio": {"id": "m9"}}},
    )

    first = store_inbound_media(message.pk)
    second = store_inbound_media(message.pk)

    assert first == second
    assert first.endswith(".oga") or first.endswith(".ogg")
    assert route.call_count == 1


@pytest.mark.django_db
def test_send_media_in_dry_run_uploads_nothing() -> None:
    conversation = _conversation()

    message = send_media(
        conversation.contact,
        b"PNG",
        "image/png",
        "teste.png",
        caption="Oi",
        conversation=conversation,
    )

    assert message.status == MessageStatus.SIMULATED
    assert message.kind == "image"
    assert message.raw_payload["request"]["image"] == {"id": "simulado", "caption": "Oi"}


@pytest.mark.django_db
@respx.mock
def test_send_media_uploads_then_sends_by_id(real_sends: Any) -> None:
    upload = respx.post(f"{GRAPH}/444/media").mock(
        return_value=httpx.Response(200, json={"id": "up-1"})
    )
    send = respx.post(f"{GRAPH}/444/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.img"}]})
    )
    conversation = _conversation()

    message = send_media(
        conversation.contact, b"%PDF", "application/pdf", "proposta.pdf", conversation=conversation
    )

    assert b'name="messaging_product"' in upload.calls.last.request.content
    assert b"proposta.pdf" in upload.calls.last.request.content
    request = json.loads(send.calls.last.request.content)
    assert request["document"] == {"id": "up-1", "filename": "proposta.pdf"}
    assert (message.kind, message.external_id) == ("document", "wamid.img")


@pytest.mark.django_db
def test_panel_test_image_and_attachment_in_dry_run(admin_client: Client) -> None:
    conversation = _conversation()
    headers = {"HX-Request": "true"}

    admin_client.post(reverse("whatsapp:send_test_image", args=[conversation.pk]), headers=headers)
    attachment = SimpleUploadedFile("nota.pdf", b"%PDF-1.4", content_type="application/pdf")
    response = admin_client.post(
        reverse("whatsapp:reply", args=[conversation.pk]),
        {"body": "Segue a proposta", "attachment": attachment},
        headers=headers,
    )

    assert "Simulada" in response.content.decode()
    kinds = [(m.kind, m.body) for m in _replies()]
    assert kinds == [
        ("image", "Imagem de teste do B2G Integrations Lab"),
        ("document", "Segue a proposta"),
    ]


# Formulário nativo (WhatsApp Flow)


def test_nfm_reply_is_parsed() -> None:
    content = extract_content(
        {
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "name": "flow",
                    "body": "Sent",
                    "response_json": json.dumps(
                        {"flow_token": "1:formulario", "nome": "Ana", "interesse": "agendar"}
                    ),
                },
            },
        }
    )

    assert content.form_response == {
        "flow_token": "1:formulario",
        "nome": "Ana",
        "interesse": "agendar",
    }
    assert content.body == "[formulário] nome: Ana; interesse: agendar"


def _form_reply(token: str, **answers: Any) -> dict[str, Any]:
    return _message(
        type="interactive",
        interactive={
            "type": "nfm_reply",
            "nfm_reply": {
                "name": "flow",
                "body": "Sent",
                "response_json": json.dumps({"flow_token": token, **answers}),
            },
        },
    )


@pytest.mark.django_db
def test_cadastro_flow_with_native_form_end_to_end(meta_post: Any) -> None:
    WhatsAppForm.objects.create(name="b2g_cadastro", meta_id="777", status="PUBLISHED")

    meta_post(_envelope(_message(type="text", text={"body": "Cadastro"})))

    run = FlowRun.objects.get(flow_key="cadastro")
    invite = _replies()[-1]
    parameters = invite.raw_payload["request"]["interactive"]["action"]["parameters"]
    assert parameters["flow_id"] == "777"
    assert parameters["flow_token"] == f"{run.pk}:formulario"
    assert parameters["mode"] == "published"

    meta_post(
        _envelope(
            _form_reply(
                f"{run.pk}:formulario",
                nome="Ana Souza",
                email="Ana@Empresa.com",
                interesse="agendar",
                novidades=True,
            )
        )
    )

    run.refresh_from_db()
    assert run.status == FlowRunStatus.COMPLETED
    contact = Contact.objects.get()
    assert contact.email == "ana@empresa.com"
    consent = contact.consents.active().get(purpose=ConsentPurpose.MARKETING)
    assert consent.source == "whatsapp_form"
    assert Event.objects.get(event_type="lead.form_submitted").summary.endswith(
        "Agendar uma conversa"
    )
    assert _replies()[-1].body == (
        "Obrigado, Ana! Recebemos seu cadastro. Se precisar de algo, é só enviar MENU."
    )


@pytest.mark.django_db
def test_cadastro_without_opt_in_and_with_wrong_token(meta_post: Any) -> None:
    WhatsAppForm.objects.create(name="b2g_cadastro", meta_id="777", status="DRAFT")
    meta_post(_envelope(_message(type="text", text={"body": "cadastro"})))
    run = FlowRun.objects.get(flow_key="cadastro")
    invite = _replies()[-1].raw_payload["request"]["interactive"]["action"]["parameters"]
    assert invite["mode"] == "draft"

    meta_post(_envelope(_form_reply("outro:token", nome="X")))
    assert "toque no botão abaixo" in _replies()[-2].body
    assert _replies()[-1].raw_payload["request"]["interactive"]["type"] == "flow"

    meta_post(_envelope(_form_reply(f"{run.pk}:formulario", nome="Bia", novidades=False)))
    assert not Contact.objects.get().consents.exists()


@pytest.mark.django_db
def test_cadastro_without_form_on_meta_ends_politely(meta_post: Any) -> None:
    meta_post(_envelope(_message(type="text", text={"body": "CADASTRO"})))

    assert "indisponível" in _replies()[-1].body
    assert FlowRun.objects.get().status == FlowRunStatus.COMPLETED


@pytest.mark.django_db
def test_panel_starts_registration(
    admin_client: Client, django_capture_on_commit_callbacks: Any
) -> None:
    WhatsAppForm.objects.create(name="b2g_cadastro", meta_id="777", status="PUBLISHED")
    conversation = _conversation()

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("whatsapp:start_registration", args=[conversation.pk]),
            headers={"HX-Request": "true"},
        )

    assert "Cadastro iniciado" in response.content.decode()
    assert _replies()[-1].raw_payload["request"]["interactive"]["type"] == "flow"


@pytest.mark.django_db
@respx.mock
def test_forms_command_creates_published_form() -> None:
    create = respx.post(f"{GRAPH}/333/flows").mock(
        return_value=httpx.Response(
            200, json={"id": "777", "success": True, "validation_errors": []}
        )
    )
    respx.get(f"{GRAPH}/777").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "777",
                "name": "b2g_cadastro",
                "status": "PUBLISHED",
                "categories": ["LEAD_GENERATION"],
            },
        )
    )
    out = StringIO()

    call_command("whatsapp_forms", "create", "b2g_cadastro", stdout=out)

    sent = json.loads(create.calls.last.request.content)
    assert sent["publish"] is True
    assert json.loads(sent["flow_json"])["version"] == "6.0"
    form = WhatsAppForm.objects.get()
    assert (form.meta_id, form.status) == ("777", "PUBLISHED")
    assert "b2g_cadastro criado: PUBLISHED" in out.getvalue()


@pytest.mark.django_db
@respx.mock
def test_forms_command_sync_and_list() -> None:
    respx.get(f"{GRAPH}/333/flows").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "777", "name": "b2g_cadastro", "status": "DRAFT", "categories": []}]
            },
        )
    )
    out = StringIO()

    call_command("whatsapp_forms", "sync", stdout=out)

    assert "b2g_cadastro: DRAFT (777)" in out.getvalue()
    with pytest.raises(CommandError, match="Informe o nome"):
        call_command("whatsapp_forms", "create", stdout=StringIO())


# Aviso ao dono no handoff


@pytest.mark.django_db
def test_handoff_notifies_owner_with_open_window(meta_post: Any, settings: Any) -> None:
    settings.OWNER_WHATSAPP_NUMBERS = [OWNER]
    owner_conversation = _conversation(OWNER)

    meta_post(_envelope(_message(type="text", text={"body": "oi"})))
    run = FlowRun.objects.get()
    meta_post(
        _envelope(
            _message(
                type="interactive",
                interactive={
                    "type": "button_reply",
                    "button_reply": {"id": "menu:danilo", "title": "Falar com o Danilo"},
                },
            )
        )
    )

    notice = Message.objects.filter(conversation=owner_conversation).get()
    assert notice.body.startswith("Aviso do laboratório: Ana Souza pediu atendimento humano")
    assert "Motivo: Contato pediu para falar com o Danilo" in notice.body
    assert "interesse: danilo" in notice.body
    client_messages = Message.objects.filter(
        conversation__contact__phone=PHONE, direction=MessageDirection.OUTBOUND
    )
    assert client_messages.last().pk < notice.pk  # o cliente recebe a resposta antes do aviso
    run.refresh_from_db()
    assert run.status == FlowRunStatus.HANDOFF


@pytest.mark.django_db
def test_handoff_without_owner_window_only_records_event(meta_post: Any, settings: Any) -> None:
    settings.OWNER_WHATSAPP_NUMBERS = [OWNER]
    _conversation(OWNER, window_open=False)

    meta_post(_envelope(_message(type="text", text={"body": "oi"})))
    meta_post(
        _envelope(
            _message(
                type="interactive",
                interactive={
                    "type": "button_reply",
                    "button_reply": {"id": "menu:danilo", "title": "Falar com o Danilo"},
                },
            )
        )
    )

    assert Event.objects.filter(event_type="whatsapp.owner_notice_skipped").exists()
    assert Conversation.objects.get(contact__phone=PHONE).status == ConversationStatus.HANDOFF


# Simulação de resposta (respostas hipotéticas)


@pytest.mark.django_db
@respx.mock
def test_simulate_reply_signs_like_meta(settings: Any) -> None:
    conversation = _conversation()
    ChannelIdentity.objects.create(
        contact=conversation.contact, channel=Channel.WHATSAPP, account_id="333", external_id=BSUID
    )
    route = respx.post("http://lab.test/webhooks/meta/").mock(
        return_value=httpx.Response(200, json={"status": "received"})
    )

    call_command(
        "whatsapp_simulate_reply",
        "--contact",
        PHONE,
        "--template-button",
        "reuniao_confirmar",
        "--title",
        "Confirmo",
        "--url",
        "http://lab.test/webhooks/meta/",
        stdout=StringIO(),
    )

    request = route.calls.last.request
    assert verify_hmac_sha256(
        settings.META_APP_SECRET, request.content, request.headers[SIGNATURE_HEADER]
    )
    message = json.loads(request.content)["entry"][0]["changes"][0]["value"]["messages"][0]
    assert message["type"] == "button"
    assert message["button"] == {"payload": "reuniao_confirmar", "text": "Confirmo"}
    assert message["from_user_id"] == BSUID
    assert message["id"].startswith("wamid.simulado.")
    assert message["simulated"] is True


@pytest.mark.django_db
def test_simulated_template_reply_goes_through_pipeline(meta_post: Any) -> None:
    message = _message(type="button", button={"payload": "reuniao_cancelar", "text": "Cancelar"})
    message["id"] = "wamid.simulado.abc"
    message["simulated"] = True

    meta_post(_envelope(message))

    assert Event.objects.get(event_type="meeting.response").data == {"answer": "cancelar"}
    assert _replies()[-1].body.startswith("Reunião cancelada.")
