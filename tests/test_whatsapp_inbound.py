"""Testes do recebimento do WhatsApp: contatos por BSUID, mensagens, saída e status."""

from datetime import UTC, datetime
from typing import Any

import pytest

from apps.core.models import (
    Channel,
    ChannelIdentity,
    Consent,
    ConsentPurpose,
    Contact,
    Conversation,
    Event,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.core.services import grant_consent
from apps.webhooks.models import DeliveryStatus, WebhookDelivery
from apps.whatsapp.identity import normalize_wa_id
from apps.whatsapp.inbound import extract_content, process_inbound_message, process_status

WABA_ID = "333"
PHONE_NUMBER_ID = "444"
BSUID = "BR.13491208655302741918"
METADATA = {"display_phone_number": "15550783881", "phone_number_id": PHONE_NUMBER_ID}


def _contact_block(**overrides: Any) -> dict[str, Any]:
    block = {"profile": {"name": "Ana Souza"}, "wa_id": "5511987654321", "user_id": BSUID}
    block.update(overrides)
    return block


def _text(body: str, *, wamid: str = "wamid.1", timestamp: int = 1_790_000_000, **extra: Any):
    message = {
        "from": "5511987654321",
        "from_user_id": BSUID,
        "id": wamid,
        "timestamp": str(timestamp),
        "type": "text",
        "text": {"body": body},
    }
    message.update(extra)
    return message


def _payload(
    *,
    messages: list[dict[str, Any]] | None = None,
    statuses: list[dict[str, Any]] | None = None,
    contacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"messaging_product": "whatsapp", "metadata": METADATA}
    if contacts is not None:
        value["contacts"] = contacts
    if messages is not None:
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": WABA_ID, "changes": [{"field": "messages", "value": value}]}],
    }


def _receive(message: dict[str, Any], contacts: list[dict[str, Any]] | None = None) -> Any:
    return process_inbound_message(
        message,
        contacts=[_contact_block()] if contacts is None else contacts,
        metadata=METADATA,
        waba_id=WABA_ID,
    )


@pytest.mark.parametrize(
    ("wa_id", "expected"),
    [
        ("5511987654321", "+5511987654321"),
        ("551187654321", "+5511987654321"),  # celular antigo, sem o nono dígito
        ("551133334444", "+551133334444"),  # fixo: não ganha o 9
        ("16505551234", "+16505551234"),
        ("", None),
        ("123", None),
    ],
)
def test_normalize_wa_id(wa_id: str, expected: str | None) -> None:
    assert normalize_wa_id(wa_id) == expected


@pytest.mark.django_db
def test_text_message_creates_contact_identity_conversation_and_message(meta_post: Any) -> None:
    meta_post(_payload(messages=[_text("Oi, quero saber mais")], contacts=[_contact_block()]))

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    contact = Contact.objects.get()
    assert (contact.name, contact.phone, contact.source) == (
        "Ana Souza",
        "+5511987654321",
        "whatsapp_inbound",
    )
    identity = ChannelIdentity.objects.get()
    assert (identity.channel, identity.account_id, identity.external_id) == (
        Channel.WHATSAPP,
        WABA_ID,
        BSUID,
    )
    conversation = Conversation.objects.get()
    sent_at = datetime.fromtimestamp(1_790_000_000, tz=UTC)
    assert conversation.account_id == PHONE_NUMBER_ID
    assert conversation.last_inbound_at == sent_at
    assert conversation.is_service_window_open(now=sent_at)
    message = Message.objects.get()
    assert (message.direction, message.kind, message.body, message.status) == (
        MessageDirection.INBOUND,
        "text",
        "Oi, quero saber mais",
        MessageStatus.RECEIVED,
    )
    assert message.external_id == "wamid.1"
    assert message.raw_payload["message"]["text"]["body"] == "Oi, quero saber mais"
    event = Event.objects.get(event_type="whatsapp.message_received")
    assert event.contact == contact
    # Quem escreve não ganha consentimento automático para contatos proativos
    assert not Consent.objects.exists()


@pytest.mark.django_db
def test_same_wamid_is_processed_once() -> None:
    assert _receive(_text("Oi")) is not None
    assert _receive(_text("Oi")) is None

    assert Message.objects.count() == 1
    assert Event.objects.filter(event_type="whatsapp.message_received").count() == 1


@pytest.mark.django_db
def test_second_message_reuses_contact_and_conversation() -> None:
    _receive(_text("Oi", wamid="wamid.1", timestamp=1_790_000_000))
    _receive(_text("Tudo bem?", wamid="wamid.2", timestamp=1_790_000_100))

    assert Contact.objects.count() == 1
    assert ChannelIdentity.objects.count() == 1
    conversation = Conversation.objects.get()
    assert conversation.messages.count() == 2
    assert conversation.last_inbound_at == datetime.fromtimestamp(1_790_000_100, tz=UTC)


@pytest.mark.django_db
def test_user_with_username_and_no_phone_is_identified_by_bsuid() -> None:
    message = _text("Olá")
    del message["from"]
    contact_block = {"profile": {"name": "Bia", "username": "bia.loja"}, "user_id": BSUID}

    _receive(message, contacts=[contact_block])

    contact = Contact.objects.get()
    assert contact.phone == ""
    identity = ChannelIdentity.objects.get()
    assert (identity.external_id, identity.handle) == (BSUID, "bia.loja")


@pytest.mark.django_db
def test_existing_contact_with_same_phone_is_linked() -> None:
    existing = Contact.objects.create(name="Ana (site)", phone="+5511987654321", email="a@x.com")

    _receive(_text("Oi"))

    assert Contact.objects.get() == existing
    existing.refresh_from_db()
    assert existing.name == "Ana (site)"  # não sobrescreve dados existentes
    assert ChannelIdentity.objects.get().contact == existing


@pytest.mark.django_db
def test_identity_keyed_by_wa_id_is_promoted_to_bsuid() -> None:
    contact = Contact.objects.create(phone="+5511987654321")
    ChannelIdentity.objects.create(
        contact=contact, channel=Channel.WHATSAPP, account_id=WABA_ID, external_id="5511987654321"
    )

    _receive(_text("Oi"))

    identity = ChannelIdentity.objects.get()
    assert identity.external_id == BSUID
    assert identity.contact == contact


@pytest.mark.django_db
def test_button_reply_keeps_title_and_id() -> None:
    message = {
        "from": "5511987654321",
        "from_user_id": BSUID,
        "id": "wamid.btn",
        "timestamp": "1790000000",
        "type": "interactive",
        "context": {"from": "15550783881", "id": "wamid.out"},
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "agendar", "title": "Quero agendar"},
        },
    }

    stored = _receive(message)

    assert (stored.kind, stored.body) == ("interactive", "Quero agendar")
    assert stored.raw_payload["reply_id"] == "agendar"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            {
                "type": "interactive",
                "interactive": {
                    "type": "list_reply",
                    "list_reply": {"id": "row-2", "title": "Quinta 15h", "description": "30 min"},
                },
            },
            ("interactive", "Quinta 15h", "row-2"),
        ),
        (
            {"type": "button", "button": {"text": "Confirmo", "payload": "confirmar"}},
            ("button", "Confirmo", "confirmar"),
        ),
        (
            {"type": "image", "image": {"id": "media-1", "caption": "Meu logo"}},
            ("image", "Meu logo", ""),
        ),
        ({"type": "audio", "audio": {"id": "media-2"}}, ("audio", "", "")),
        (
            {"type": "location", "location": {"latitude": -23.5, "longitude": -46.6}},
            ("location", "-23.5,-46.6", ""),
        ),
        ({"type": "reaction", "reaction": {"emoji": "👍"}}, ("reaction", "👍", "")),
        ({"type": "unsupported"}, ("unsupported", "", "")),
    ],
)
def test_extract_content(message: dict[str, Any], expected: tuple[str, str, str]) -> None:
    content = extract_content(message)

    assert (content.kind, content.body, content.reply_id) == expected


@pytest.mark.django_db
@pytest.mark.parametrize("word", ["SAIR", "parar", "Stop!"])
def test_opt_out_word_revokes_whatsapp_consents(word: str) -> None:
    contact = Contact.objects.create(phone="+5511987654321")
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")
    grant_consent(contact, Channel.EMAIL, ConsentPurpose.MARKETING, source="teste")

    _receive(_text(word))

    assert not contact.consents.active().filter(channel=Channel.WHATSAPP).exists()
    assert contact.consents.active().filter(channel=Channel.EMAIL).exists()
    assert Event.objects.filter(event_type="consent.revoked", contact=contact).exists()


@pytest.mark.django_db
def test_sentence_containing_opt_out_word_does_not_revoke() -> None:
    contact = Contact.objects.create(phone="+5511987654321")
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")

    _receive(_text("não quero sair do grupo"))

    assert contact.consents.active().exists()


def _outbound(wamid: str = "wamid.out", status: str = MessageStatus.QUEUED) -> Message:
    contact = Contact.objects.create(phone="+5511987654321")
    conversation = Conversation.objects.create(
        contact=contact, channel=Channel.WHATSAPP, account_id=PHONE_NUMBER_ID
    )
    return Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.OUTBOUND,
        external_id=wamid,
        status=status,
        raw_payload={"request": {}, "response": {}},
    )


def _status(name: str, *, timestamp: int = 1_790_000_000, **extra: Any) -> dict[str, Any]:
    return {
        "id": "wamid.out",
        "status": name,
        "timestamp": str(timestamp),
        "recipient_id": "5511987654321",
        "recipient_user_id": BSUID,
        **extra,
    }


@pytest.mark.django_db
def test_status_webhooks_advance_without_regressing(meta_post: Any) -> None:
    message = _outbound()
    pricing = {"billable": True, "pricing_model": "PMP", "category": "utility", "type": "regular"}

    meta_post(_payload(statuses=[_status("sent", timestamp=1_790_000_001)]))
    meta_post(_payload(statuses=[_status("read", timestamp=1_790_000_003)]))
    meta_post(_payload(statuses=[_status("delivered", timestamp=1_790_000_002, pricing=pricing)]))

    message.refresh_from_db()
    assert message.status == MessageStatus.READ
    assert [s["status"] for s in message.raw_payload["statuses"]] == ["sent", "read", "delivered"]
    assert message.raw_payload["statuses"][2]["pricing"]["category"] == "utility"


@pytest.mark.django_db
def test_failed_status_stores_error_and_event() -> None:
    message = _outbound()
    error = {"code": 131047, "title": "Re-engagement message", "message": "Mais de 24h"}

    process_status(_status("failed", errors=[error]))

    message.refresh_from_db()
    assert message.status == MessageStatus.FAILED
    assert message.error == {"errors": [error]}
    event = Event.objects.get(event_type="whatsapp.message_failed")
    assert event.summary == "131047 Re-engagement message"


@pytest.mark.django_db
def test_failed_after_delivered_is_kept_only_in_history() -> None:
    message = _outbound(status=MessageStatus.DELIVERED)

    process_status(_status("failed", errors=[{"code": 1}]))

    message.refresh_from_db()
    assert message.status == MessageStatus.DELIVERED
    assert len(message.raw_payload["statuses"]) == 1
    assert not Event.objects.filter(event_type="whatsapp.message_failed").exists()


@pytest.mark.django_db
def test_status_of_unknown_message_is_ignored() -> None:
    assert process_status(_status("delivered")) is None


@pytest.mark.django_db
def test_user_changed_number_updates_bsuid_and_phone() -> None:
    _receive(_text("Oi"))
    system_message = {
        "from": "5511987654321",
        "id": "wamid.sys",
        "timestamp": "1790000500",
        "type": "system",
        "system": {
            "body": "User Ana changed from 5511987654321 to 5521999990000",
            "type": "user_changed_number",
            "wa_id": "5521999990000",
            "user_id": "BR.NOVO",
            "previous_user_id": BSUID,
        },
    }

    assert _receive(system_message, contacts=[]) is None

    identity = ChannelIdentity.objects.get()
    assert identity.external_id == "BR.NOVO"
    assert identity.contact.phone == "+5521999990000"
    event = Event.objects.get(event_type="whatsapp.identity_changed")
    assert event.contact == identity.contact
    assert event.data["matched"] is True


@pytest.mark.django_db
def test_user_changed_user_id_with_unknown_previous_is_only_logged() -> None:
    system_message = {
        "id": "wamid.sys2",
        "timestamp": "1790000500",
        "type": "system",
        "system": {
            "type": "user_changed_user_id",
            "user_id": "BR.NOVO",
            "previous_user_id": "BR.DESCONHECIDO",
        },
    }

    _receive(system_message, contacts=[])

    assert not ChannelIdentity.objects.exists()
    assert Event.objects.get(event_type="whatsapp.identity_changed").data["matched"] is False


@pytest.mark.django_db
def test_other_whatsapp_fields_are_processed_without_side_effects(meta_post: Any) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "field": "message_template_status_update",
                        "value": {"event": "APPROVED", "message_template_name": "boas_vindas"},
                    }
                ],
            }
        ],
    }

    meta_post(payload)

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    assert not Message.objects.exists()
