"""Testes do recebimento comum da Messenger Platform: Direct do Instagram e Messenger da Página.

Os payloads seguem o formato das primeiras entregas reais (07/11/2026), com IDs fictícios.
"""

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
from apps.meta_business.messaging import extract_content, parse_timestamp
from apps.webhooks.models import DeliveryStatus, WebhookDelivery

IG_ID = "17840000000000001"
IGSID = "2860000000000001"
PAGE_ID = "111"
PSID = "3970000000000001"
TS = 1_794_047_902_403  # milissegundos, como nas entregas reais


def _entry(account_id: str, *events: dict[str, Any], time: int = TS + 500) -> dict[str, Any]:
    return {"time": time, "id": account_id, "messaging": list(events)}


def _ig(*events: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return {"object": "instagram", "entry": [_entry(IG_ID, *events, **kwargs)]}


def _page(*events: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return {"object": "page", "entry": [_entry(PAGE_ID, *events, **kwargs)]}


def _from_user(user_id: str, account_id: str, *, timestamp: int = TS, **body: Any) -> dict:
    return {
        "sender": {"id": user_id},
        "recipient": {"id": account_id},
        "timestamp": timestamp,
        **body,
    }


def _to_user(user_id: str, account_id: str, *, timestamp: int = TS, **body: Any) -> dict:
    return {
        "sender": {"id": account_id},
        "recipient": {"id": user_id},
        "timestamp": timestamp,
        **body,
    }


def _ig_text(text: str, *, mid: str = "aWdfZAG1", timestamp: int = TS) -> dict[str, Any]:
    return _from_user(IGSID, IG_ID, timestamp=timestamp, message={"mid": mid, "text": text})


def test_parse_timestamp_accepts_milliseconds_and_seconds() -> None:
    expected = datetime(2026, 11, 7, 10, 38, 22, 403000, tzinfo=UTC)
    assert parse_timestamp(TS) == expected
    assert parse_timestamp("1794047902") == expected.replace(microsecond=0)
    assert parse_timestamp(None) is not None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"mid": "m1", "text": "Oi"}, ("text", "Oi", "")),
        ({"mid": "m1", "text": "Sim", "quick_reply": {"payload": "SIM"}}, ("text", "Sim", "SIM")),
        (
            {"mid": "m1", "attachments": [{"type": "image", "payload": {"url": "https://x"}}]},
            ("image", "", ""),
        ),
        ({"mid": "m1", "is_unsupported": True}, ("unsupported", "", "")),
        (
            {"admin_text": "Conversa passada pela IA"},
            ("admin_text", "Conversa passada pela IA", ""),
        ),
    ],
)
def test_extract_content(message: dict[str, Any], expected: tuple[str, str, str]) -> None:
    content = extract_content(message)
    assert (content.kind, content.body, content.reply_id) == expected


@pytest.mark.django_db
def test_instagram_dm_creates_contact_conversation_and_message(meta_post: Any) -> None:
    response = meta_post(_ig(_ig_text("Oi")))

    assert response.status_code == 200
    delivery = WebhookDelivery.objects.get()
    assert delivery.route_key == "instagram"
    assert delivery.status == DeliveryStatus.PROCESSED

    identity = ChannelIdentity.objects.get()
    assert (identity.channel, identity.account_id, identity.external_id) == (
        Channel.INSTAGRAM,
        IG_ID,
        IGSID,
    )
    assert identity.contact.source == "instagram_inbound"

    message = Message.objects.get()
    assert message.channel == Channel.INSTAGRAM
    assert message.direction == MessageDirection.INBOUND
    assert (message.kind, message.body, message.external_id) == ("text", "Oi", "aWdfZAG1")
    assert message.status == MessageStatus.RECEIVED
    assert message.created_at == parse_timestamp(TS)

    conversation = message.conversation
    assert (conversation.channel, conversation.account_id) == (Channel.INSTAGRAM, IG_ID)
    assert conversation.last_inbound_at == parse_timestamp(TS)
    assert conversation.is_service_window_open(now=parse_timestamp(TS + 3_600_000))

    event = Event.objects.get(event_type="instagram.message_received")
    assert event.contact == identity.contact
    assert event.external_id == "aWdfZAG1"


@pytest.mark.django_db
def test_same_mid_in_another_delivery_is_not_duplicated(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    # Reenvio com outro entry.time: corpo diferente, mesma mensagem
    meta_post(_ig(_ig_text("Oi"), time=TS + 9_000))

    assert WebhookDelivery.objects.count() == 2
    assert Message.objects.count() == 1
    assert Event.objects.filter(event_type="instagram.message_received").count() == 1


@pytest.mark.django_db
def test_second_message_reuses_contact_and_conversation(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    meta_post(_ig(_ig_text("Tudo bem?", mid="aWdfZAG2", timestamp=TS + 20_000)))

    assert Contact.objects.count() == 1
    assert Conversation.objects.count() == 1
    conversation = Conversation.objects.get()
    assert conversation.last_inbound_at == parse_timestamp(TS + 20_000)
    assert list(conversation.messages.values_list("body", flat=True)) == ["Oi", "Tudo bem?"]


@pytest.mark.django_db
def test_panel_test_event_in_changes_format_is_processed(meta_post: Any) -> None:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "0",
                "time": 1794008649,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "sender": {"id": "12334"},
                            "recipient": {"id": "23245"},
                            "timestamp": "1527459824",
                            "message": {"mid": "random_mid", "text": "random_text"},
                        },
                    }
                ],
            }
        ],
    }
    meta_post(payload)

    message = Message.objects.get()
    assert (message.body, message.conversation.account_id) == ("random_text", "0")
    assert message.created_at == datetime.fromtimestamp(1527459824, tz=UTC)


@pytest.mark.django_db
def test_opt_out_word_revokes_instagram_consents(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    contact = Contact.objects.get()
    grant_consent(contact, Channel.INSTAGRAM, ConsentPurpose.MARKETING, source="teste")
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")

    meta_post(_ig(_ig_text("Sair!", mid="aWdfZAG2", timestamp=TS + 1_000)))

    assert not Consent.objects.active().filter(channel=Channel.INSTAGRAM).exists()
    assert Consent.objects.active().filter(channel=Channel.WHATSAPP).exists()
    revoked = Consent.objects.get(channel=Channel.INSTAGRAM)
    assert revoked.revocation_source == "instagram_keyword"


@pytest.mark.django_db
def test_echo_is_stored_as_outbound_and_skipped_when_already_known(meta_post: Any) -> None:
    echo = _to_user(IGSID, IG_ID, message={"mid": "aWdfZECO1", "text": "Olá!", "is_echo": True})
    meta_post(_ig(echo))
    meta_post(_ig(echo, time=TS + 7_000))

    message = Message.objects.get()
    assert message.direction == MessageDirection.OUTBOUND
    assert message.status == MessageStatus.SENT
    assert message.body == "Olá!"
    identity = ChannelIdentity.objects.get()
    assert identity.external_id == IGSID  # o contato é o destinatário do eco
    assert message.conversation.last_inbound_at is None


@pytest.mark.django_db
def test_instagram_read_marks_outbound_messages_up_to_the_read_one(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    first = _to_user(
        IGSID, IG_ID, timestamp=TS + 1_000, message={"mid": "e1", "text": "1", "is_echo": True}
    )
    second = _to_user(
        IGSID, IG_ID, timestamp=TS + 2_000, message={"mid": "e2", "text": "2", "is_echo": True}
    )
    later = _to_user(
        IGSID, IG_ID, timestamp=TS + 9_000, message={"mid": "e3", "text": "3", "is_echo": True}
    )
    meta_post(_ig(first, second, later))

    meta_post(_ig(_from_user(IGSID, IG_ID, timestamp=TS + 5_000, read={"mid": "e2"})))

    statuses = dict(Message.objects.filter(direction="out").values_list("external_id", "status"))
    assert statuses == {
        "e1": MessageStatus.READ,
        "e2": MessageStatus.READ,
        "e3": MessageStatus.SENT,
    }


@pytest.mark.django_db
def test_reaction_becomes_event_without_message(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    reaction = {"mid": "aWdfZAG1", "action": "react", "reaction": "love", "emoji": "❤️"}
    meta_post(_ig(_from_user(IGSID, IG_ID, timestamp=TS + 1_000, reaction=reaction)))

    assert Message.objects.count() == 1
    event = Event.objects.get(event_type="instagram.reaction")
    assert event.contact == Contact.objects.get()
    assert event.summary == "❤️ (react)"
    assert event.data["message_id"] == Message.objects.get().pk


@pytest.mark.django_db
def test_postback_is_stored_with_payload(meta_post: Any) -> None:
    postback = {"mid": "aWdfZPB1", "title": "Quero saber mais", "payload": "SABER_MAIS"}
    meta_post(_ig(_from_user(IGSID, IG_ID, postback=postback)))

    message = Message.objects.get()
    assert (message.kind, message.body, message.external_id) == (
        "postback",
        "Quero saber mais",
        "aWdfZPB1",
    )
    assert message.raw_payload["reply_id"] == "SABER_MAIS"
    assert message.conversation.last_inbound_at is not None


@pytest.mark.django_db
def test_edit_keeps_previous_text(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    edit = {"mid": "aWdfZAG1", "text": "Oi, tudo bem?", "num_edit": 1}
    meta_post(_ig(_from_user(IGSID, IG_ID, timestamp=TS + 1_000, message_edit=edit)))
    meta_post(_ig(_from_user(IGSID, IG_ID, timestamp=TS + 1_000, message_edit=edit), time=TS + 3))

    message = Message.objects.get()
    assert message.body == "Oi, tudo bem?"
    assert message.raw_payload["edits"] == [
        {"num_edit": 1, "previous": "Oi", "at": parse_timestamp(TS + 1_000).isoformat()}
    ]
    assert Event.objects.filter(event_type="instagram.message_edited").count() == 1


@pytest.mark.django_db
def test_deleted_message_is_kept_and_flagged(meta_post: Any) -> None:
    meta_post(_ig(_ig_text("Oi")))
    deleted = {"mid": "aWdfZAG1", "is_deleted": True}
    meta_post(_ig(_from_user(IGSID, IG_ID, timestamp=TS + 1_000, message=deleted)))

    message = Message.objects.get()
    assert message.body == "Oi"
    assert message.raw_payload["deleted_at"] == parse_timestamp(TS + 1_000).isoformat()
    assert Event.objects.filter(event_type="instagram.message_deleted").count() == 1


@pytest.mark.django_db
def test_messenger_message_goes_to_the_facebook_channel(meta_post: Any) -> None:
    event = _from_user(PSID, PAGE_ID, message={"mid": "m_qP5eBW1", "text": "Oi teste"})
    meta_post(_page(event))

    delivery = WebhookDelivery.objects.get()
    assert (delivery.route_key, delivery.status) == ("page", DeliveryStatus.PROCESSED)
    message = Message.objects.get()
    assert (message.channel, message.body) == (Channel.FACEBOOK, "Oi teste")
    identity = ChannelIdentity.objects.get()
    assert (identity.channel, identity.account_id, identity.external_id) == (
        Channel.FACEBOOK,
        PAGE_ID,
        PSID,
    )
    assert identity.contact.source == "facebook_inbound"
    assert Event.objects.filter(event_type="facebook.message_received").count() == 1


@pytest.mark.django_db
def test_messenger_delivery_and_read_watermarks(meta_post: Any) -> None:
    meta_post(_page(_from_user(PSID, PAGE_ID, message={"mid": "m_in", "text": "Oi"})))
    sent = [
        _to_user(
            PSID,
            PAGE_ID,
            timestamp=TS + n * 1_000,
            message={"mid": f"m_{n}", "text": str(n), "is_echo": True},
        )
        for n in (1, 2, 3)
    ]
    meta_post(_page(*sent))

    delivery = {"mids": ["m_1", "m_2"], "watermark": TS + 2_000}
    meta_post(_page(_from_user(PSID, PAGE_ID, timestamp=TS + 2_500, delivery=delivery)))
    meta_post(
        _page(_from_user(PSID, PAGE_ID, timestamp=TS + 2_600, read={"watermark": TS + 1_000}))
    )

    statuses = dict(Message.objects.filter(direction="out").values_list("external_id", "status"))
    assert statuses == {
        "m_1": MessageStatus.READ,
        "m_2": MessageStatus.DELIVERED,
        "m_3": MessageStatus.SENT,
    }


@pytest.mark.django_db
def test_same_user_id_in_instagram_and_messenger_are_separate_identities(meta_post: Any) -> None:
    meta_post(_ig(_from_user("999", IG_ID, message={"mid": "ig1", "text": "Oi"})))
    meta_post(_page(_from_user("999", PAGE_ID, message={"mid": "m_1", "text": "Oi"})))

    assert ChannelIdentity.objects.count() == 2
    assert Contact.objects.count() == 2
