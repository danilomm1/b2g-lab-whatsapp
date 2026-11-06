"""Testes do motor de fluxo do WhatsApp e do fluxo boas_vindas, pela esteira completa.

Cada mensagem passa pelo webhook assinado, pelo motor e pela tarefa de envio (Huey em
modo imediato). Com o dry-run dos testes, as respostas ficam como mensagens simuladas.
"""

import itertools
import json
import time
from dataclasses import asdict
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from django.utils import timezone

from apps.core.models import (
    Channel,
    ConsentPurpose,
    Contact,
    Conversation,
    ConversationStatus,
    Event,
    Message,
    MessageDirection,
    MessageStatus,
    Tag,
)
from apps.core.services import grant_consent
from apps.webhooks.models import DeliveryStatus, WebhookDelivery
from apps.whatsapp import payloads
from apps.whatsapp.flows import engine
from apps.whatsapp.flows.engine import Ask, Call, End, Flow, Option, Say
from apps.whatsapp.models import FlowRun, FlowRunStatus
from apps.whatsapp.services import deliver_outbox

BSUID = "BR.13491208655302741918"
_ids = itertools.count(1)


def _envelope(message: dict[str, Any]) -> dict[str, Any]:
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
                                {
                                    "profile": {"name": "Ana Souza"},
                                    "wa_id": "5511987654321",
                                    "user_id": BSUID,
                                }
                            ],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def _base() -> dict[str, Any]:
    return {
        "from": "5511987654321",
        "from_user_id": BSUID,
        "id": f"wamid.in.{next(_ids)}",
        "timestamp": str(int(time.time())),
    }


@pytest.fixture
def contact_says(meta_post: Any) -> Any:
    """Simula o contato: texto, toque em botão ou lista, ou botão de template."""

    def say(text: str = "", *, tap: str = "", title: str = "", template_button: str = "") -> None:
        message = _base()
        if tap:
            message |= {
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": tap, "title": title},
                },
            }
        elif template_button:
            message |= {"type": "button", "button": {"payload": template_button, "text": title}}
        else:
            message |= {"type": "text", "text": {"body": text}}
        response = meta_post(_envelope(message))
        assert response.status_code == 200

    return say


def _replies() -> list[Message]:
    return list(Message.objects.filter(direction=MessageDirection.OUTBOUND).order_by("pk"))


def _button_ids(message: Message) -> list[str]:
    interactive = message.raw_payload["request"]["interactive"]
    return [b["reply"]["id"] for b in interactive["action"]["buttons"]]


def _run() -> FlowRun:
    return FlowRun.objects.order_by("-pk").first()


@pytest.mark.django_db
def test_first_message_greets_with_privacy_notice_and_shows_menu(contact_says: Any) -> None:
    contact_says("oi")

    greeting, menu = _replies()
    assert greeting.body.startswith("Olá, Ana! Aqui é o assistente automático da Brave2Grow.")
    assert "https://brave2grow.com/privacidade" in greeting.body
    assert "envie SAIR" in greeting.body
    assert _button_ids(menu) == ["menu:servicos", "menu:agendar", "menu:danilo"]
    assert all(m.status == MessageStatus.SIMULATED for m in (greeting, menu))
    run = _run()
    assert (run.flow_key, run.node, run.status) == ("boas_vindas", "menu", FlowRunStatus.ACTIVE)
    assert Event.objects.filter(event_type="privacy.notice_shown").count() == 1


@pytest.mark.django_db
def test_privacy_notice_is_given_only_once(contact_says: Any) -> None:
    contact_says("oi")
    contact_says("menu")

    greetings = [m for m in _replies() if m.body.startswith("Olá")]
    assert len(greetings) == 2
    assert "privacidade" not in greetings[1].body
    assert FlowRun.objects.filter(status=FlowRunStatus.CANCELLED).count() == 1


@pytest.mark.django_db
def test_services_path_grants_marketing_consent(contact_says: Any) -> None:
    contact_says("oi")
    contact_says(tap="menu:servicos", title="Conhecer serviços")

    replies = _replies()
    assert "brave2grow.com" in replies[-2].body
    assert _button_ids(replies[-1]) == ["novidades:sim", "novidades:nao"]

    contact_says(tap="novidades:sim", title="Quero receber")

    contact = Contact.objects.get()
    consent = contact.consents.active().get(channel=Channel.WHATSAPP)
    assert consent.purpose == ConsentPurpose.MARKETING
    assert consent.source == "whatsapp_flow"
    assert "Quero receber" in consent.consent_text
    assert consent.evidence["message_id"].startswith("wamid.in.")
    assert _replies()[-1].body.startswith("Combinado!")
    run = _run()
    assert run.status == FlowRunStatus.COMPLETED
    assert run.state["answers"] == {"interesse": "servicos", "quer_novidades": "sim"}


@pytest.mark.django_db
def test_declining_news_records_no_consent(contact_says: Any) -> None:
    contact_says("oi")
    contact_says(tap="menu:servicos", title="Conhecer serviços")
    contact_says(tap="novidades:nao", title="Agora não")

    assert not Contact.objects.get().consents.exists()
    assert _replies()[-1].body.startswith("Sem problemas!")


@pytest.mark.django_db
def test_scheduling_path_asks_email_validates_and_registers_lead(contact_says: Any) -> None:
    contact_says("oi")
    contact_says(tap="menu:agendar", title="Agendar conversa")
    assert "melhor email" in _replies()[-1].body

    contact_says("meu email é ana")
    assert "Não reconheci esse email" in _replies()[-1].body
    assert _run().node == "pedir_email"

    contact_says("Ana@Empresa.com.br")
    assert _button_ids(_replies()[-1]) == ["periodo:manha", "periodo:tarde", "periodo:noite"]
    assert Contact.objects.get().email == "ana@empresa.com.br"

    contact_says(tap="periodo:tarde", title="Tarde")

    assert _replies()[-1].body == (
        "Anotado! O Danilo vai te enviar opções de horário para o período da tarde. "
        "Obrigado pelo contato!"
    )
    event = Event.objects.get(event_type="lead.scheduling_requested")
    assert event.data["answers"]["periodo"] == "tarde"
    assert Tag.objects.get(name="lead-whatsapp").contacts.count() == 1
    assert _run().status == FlowRunStatus.COMPLETED


@pytest.mark.django_db
def test_scheduling_skips_email_when_contact_has_one(contact_says: Any) -> None:
    Contact.objects.create(name="Ana", phone="+5511987654321", email="ana@x.com")
    contact_says("oi")
    contact_says(tap="menu:agendar", title="Agendar conversa")

    assert _run().node == "periodo"


@pytest.mark.django_db
def test_email_already_used_by_another_contact_is_not_copied(contact_says: Any) -> None:
    Contact.objects.create(name="Outra pessoa", email="ana@empresa.com")
    contact_says("oi")
    contact_says(tap="menu:agendar", title="Agendar conversa")
    contact_says("ana@empresa.com")

    assert Contact.objects.get(phone="+5511987654321").email == ""
    assert _run().node == "periodo"


@pytest.mark.django_db
@pytest.mark.parametrize("typed", ["conhecer servicos", "CONHECER SERVIÇOS!", "1"])
def test_typed_answer_matches_option(contact_says: Any, typed: str) -> None:
    contact_says("oi")
    contact_says(typed)

    assert _run().node == "novidades"


@pytest.mark.django_db
def test_stale_button_from_another_question_is_not_accepted(contact_says: Any) -> None:
    contact_says("oi")
    contact_says(tap="novidades:sim", title="Quero receber")

    assert _run().node == "menu"
    retry, prompt = _replies()[-2:]
    assert retry.body.startswith("Não entendi")
    assert _button_ids(prompt) == ["menu:servicos", "menu:agendar", "menu:danilo"]
    assert not Contact.objects.get().consents.exists()


@pytest.mark.django_db
def test_two_invalid_answers_hand_off_and_bot_goes_quiet(contact_says: Any) -> None:
    contact_says("oi")
    contact_says("hmm")
    contact_says("sei lá")

    conversation = Conversation.objects.get()
    assert conversation.status == ConversationStatus.HANDOFF
    assert _run().status == FlowRunStatus.HANDOFF
    assert "Vou avisar o Danilo" in _replies()[-1].body
    assert Event.objects.filter(event_type="whatsapp.handoff").exists()

    before = len(_replies())
    contact_says("alguém aí?")
    assert len(_replies()) == before


@pytest.mark.django_db
def test_menu_during_handoff_gives_conversation_back_to_the_bot(contact_says: Any) -> None:
    contact_says("oi")
    contact_says(tap="menu:danilo", title="Falar com o Danilo")
    contact_says("MENU")

    assert Conversation.objects.get().status == ConversationStatus.OPEN
    assert _run().node == "menu"
    assert FlowRun.objects.filter(status=FlowRunStatus.CANCELLED).count() == 1


@pytest.mark.django_db
def test_opt_out_mid_flow_cancels_run_confirms_and_revokes(contact_says: Any) -> None:
    contact_says("oi")
    contact = Contact.objects.get()
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")

    contact_says("Sair")

    assert _run().status == FlowRunStatus.CANCELLED
    assert _replies()[-1].body == engine.OPT_OUT_CONFIRMATION
    assert not contact.consents.active().exists()


@pytest.mark.django_db
def test_completed_flow_does_not_restart_on_thanks_until_cooldown(contact_says: Any) -> None:
    contact_says("oi")
    contact_says(tap="menu:servicos", title="Conhecer serviços")
    contact_says(tap="novidades:nao", title="Agora não")
    before = len(_replies())

    contact_says("obrigado!")
    assert len(_replies()) == before

    FlowRun.objects.update(finished_at=timezone.now() - timedelta(hours=13))
    contact_says("oi de novo")
    assert _run().status == FlowRunStatus.ACTIVE
    assert len(_replies()) == before + 2


@pytest.mark.django_db
def test_stale_run_expires_and_flow_restarts(contact_says: Any) -> None:
    contact_says("oi")
    FlowRun.objects.update(updated_at=timezone.now() - timedelta(hours=25))

    contact_says("voltei")

    assert FlowRun.objects.filter(status=FlowRunStatus.EXPIRED).count() == 1
    assert _run().status == FlowRunStatus.ACTIVE


@pytest.mark.django_db
def test_template_quick_replies_outside_flows(contact_says: Any) -> None:
    contact_says(template_button="reuniao_confirmar", title="Confirmo")

    assert Event.objects.get(event_type="meeting.response").data == {"answer": "confirmar"}
    assert _replies()[-1].body == "Presença confirmada. Até lá!"
    assert not FlowRun.objects.exists()

    contact_says(template_button="retomar_sim", title="Sim, continuar")
    assert _run().node == "menu"


def test_flow_definition_is_validated() -> None:
    with pytest.raises(ValueError, match="inexistentes"):
        Flow("x", "X", start="a", nodes=[Say("a", "oi", next="b")])
    with pytest.raises(ValueError, match="opções ou parse"):
        Ask("a", "?", save_as="x", on_fail="a")


def _conversation() -> Conversation:
    contact = Contact.objects.create(name="Ana", phone="+5511987654321")
    return Conversation.objects.create(
        contact=contact,
        channel=Channel.WHATSAPP,
        account_id="444",
        last_inbound_at=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_call_failure_rolls_back_its_writes_and_follows_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(ctx: Any) -> None:
        Tag.objects.create(name="gravada-antes-do-erro")
        raise RuntimeError("API fora do ar")

    flow = Flow(
        "teste_erro",
        "Teste de erro",
        start="chamar",
        nodes=[
            Call("chamar", broken, next="ok", on_error="falhou"),
            End("ok", "deu certo"),
            End("falhou", "deu errado"),
        ],
    )
    monkeypatch.setitem(engine.FLOWS, flow.key, flow)

    ctx = engine.start_flow(_conversation(), flow.key)

    assert [p.body for p in ctx.outbox] == ["deu errado"]
    assert not Tag.objects.filter(name="gravada-antes-do-erro").exists()
    assert Event.objects.get(event_type="whatsapp.flow_error").summary.endswith("API fora do ar")


@pytest.mark.django_db
def test_list_question_for_more_than_three_options(monkeypatch: pytest.MonkeyPatch) -> None:
    options = [Option(f"o{i}", f"Opção {i}", "fim") for i in range(4)]
    flow = Flow(
        "teste_lista",
        "Lista",
        start="pergunta",
        nodes=[Ask("pergunta", "Escolha", save_as="x", options=options, on_fail="fim"), End("fim")],
    )
    monkeypatch.setitem(engine.FLOWS, flow.key, flow)

    ctx = engine.start_flow(_conversation(), flow.key)

    interactive = ctx.outbox[0].data["interactive"]
    assert interactive["type"] == "list"
    assert interactive["action"]["sections"][0]["rows"][3]["id"] == "pergunta:o3"


@pytest.mark.django_db
def test_engine_crash_keeps_message_and_records_event(
    meta_post: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(message: Message) -> None:
        raise RuntimeError("bug no fluxo")

    monkeypatch.setattr("apps.whatsapp.webhook.handle_inbound", crash)
    message = _base() | {"type": "text", "text": {"body": "oi"}}

    meta_post(_envelope(message))

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    assert Message.objects.filter(direction=MessageDirection.INBOUND).count() == 1
    assert "bug no fluxo" in Event.objects.get(event_type="whatsapp.flow_error").summary


@pytest.mark.django_db
@respx.mock
def test_deliver_outbox_marks_read_with_typing_then_sends_in_order(settings: Any) -> None:
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = ["+5511987654321"]
    route = respx.post("https://graph.facebook.com/v27.0/444/messages").mock(
        side_effect=[
            httpx.Response(200, json={"success": True}),
            httpx.Response(200, json={"messages": [{"id": "wamid.out.1"}]}),
            httpx.Response(200, json={"messages": [{"id": "wamid.out.2"}]}),
        ]
    )
    conversation = _conversation()
    inbound = Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.INBOUND,
        external_id="wamid.in.x",
        status=MessageStatus.RECEIVED,
    )
    items = [asdict(payloads.text("primeira")), asdict(payloads.text("segunda"))]

    sent = deliver_outbox(conversation.pk, items, reply_to_id=inbound.pk)

    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies[0]["status"] == "read"
    assert bodies[0]["typing_indicator"] == {"type": "text"}
    assert [b["text"]["body"] for b in bodies[1:]] == ["primeira", "segunda"]
    assert [m.external_id for m in sent] == ["wamid.out.1", "wamid.out.2"]


@pytest.mark.django_db
def test_blocked_outbox_stops_and_records_event() -> None:
    conversation = _conversation()
    Conversation.objects.filter(pk=conversation.pk).update(
        last_inbound_at=timezone.now() - timedelta(hours=30)
    )
    items = [asdict(payloads.text("primeira")), asdict(payloads.text("segunda"))]

    assert deliver_outbox(conversation.pk, items) == []

    event = Event.objects.get(event_type="whatsapp.flow_send_blocked")
    assert len(event.data["pending"]) == 2


@pytest.mark.django_db
def test_template_button_during_active_flow_is_not_read_as_answer(contact_says: Any) -> None:
    contact_says("oi")
    assert _run().node == "menu"

    contact_says(template_button="reuniao_cancelar", title="Cancelar")

    assert _replies()[-1].body.startswith("Reunião cancelada.")
    assert _run().node == "menu"  # o menu continua esperando, sem contar tentativa
    assert _run().attempts == 0

    contact_says(template_button="retomar_sim", title="Sim, continuar")
    assert FlowRun.objects.filter(status=FlowRunStatus.CANCELLED).count() == 1
    assert _run().status == FlowRunStatus.ACTIVE


@pytest.mark.django_db
def test_reaction_is_ignored_by_the_engine(meta_post: Any) -> None:
    def react() -> None:
        message = _base() | {
            "type": "reaction",
            "reaction": {"message_id": "wamid.x", "emoji": "👍"},
        }
        meta_post(_envelope(message))

    react()  # sem fluxo aberto: não inicia o menu
    assert not FlowRun.objects.exists()
    assert not _replies()

    meta_post(_envelope(_base() | {"type": "text", "text": {"body": "oi"}}))
    replies_before = len(_replies())
    react()  # com o menu aberto: não conta como tentativa
    assert _run().attempts == 0
    assert len(_replies()) == replies_before


@pytest.mark.django_db
@respx.mock
def test_silent_bot_marks_as_read_but_handoff_does_not(meta_post: Any, settings: Any) -> None:
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = ["+5511987654321"]
    ids = itertools.count(1)

    def graph(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content).get("status") == "read":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out.{next(ids)}"}]})

    route = respx.post("https://graph.facebook.com/v27.0/444/messages").mock(side_effect=graph)

    def say(body: str) -> str:
        message = _base() | {"type": "text", "text": {"body": body}}
        meta_post(_envelope(message))
        return message["id"]

    def read_ids() -> list[str]:
        bodies = [json.loads(call.request.content) for call in route.calls]
        return [b["message_id"] for b in bodies if b.get("status") == "read"]

    say("oi")
    say("Conhecer serviços")  # opção digitada
    meta_post(
        _envelope(
            _base()
            | {
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "novidades:nao", "title": "Agora não"},
                },
            }
        )
    )
    thanks = say("obrigado")  # concluído há pouco: robô quieto, mas marca como lida
    assert thanks in read_ids()

    say("MENU")
    meta_post(
        _envelope(
            _base()
            | {
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "menu:danilo", "title": "Falar com o Danilo"},
                },
            }
        )
    )
    waiting = say("alguém aí?")  # handoff: fica só como entregue até alguém atender
    assert waiting not in read_ids()
