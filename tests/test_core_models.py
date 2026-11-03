"""Testes do modelo central (app core)."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.core.models import (
    Channel,
    ConsentPurpose,
    Contact,
    Conversation,
    Event,
    Message,
    MessageDirection,
    MessageStatus,
)
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.core.services import grant_consent, has_active_consent, record_event


@pytest.mark.parametrize(
    "raw",
    ["(11) 98765-4321", "11987654321", "+55 11 98765-4321", "5511987654321"],
)
def test_normalize_phone_brazilian_formats(raw: str) -> None:
    assert normalize_phone(raw) == "+5511987654321"


def test_normalize_phone_wa_id_from_other_country() -> None:
    """wa_id traz o DDI sem "+": sem a opção, um número dos EUA seria lido como brasileiro."""
    assert normalize_phone("14155552671", assume_international=True) == "+14155552671"


@pytest.mark.parametrize("raw", ["123", "abc", ""])
def test_normalize_phone_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


@pytest.mark.django_db
def test_contact_save_normalizes_fields() -> None:
    contact = Contact.objects.create(
        name="Ana",
        phone="(11) 98765-4321",
        email="  Ana@Exemplo.COM ",
        instagram_handle="@Ana.Cafe",
    )

    contact.refresh_from_db()
    assert contact.phone == "+5511987654321"
    assert contact.email == "ana@exemplo.com"
    assert contact.instagram_handle == "ana.cafe"


@pytest.mark.django_db
def test_contact_clean_reports_invalid_phone() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Contact(name="Ana", phone="123").full_clean()

    assert "phone" in excinfo.value.message_dict


@pytest.mark.django_db
def test_contact_phone_is_unique_but_blank_is_allowed() -> None:
    Contact.objects.create(phone="+5511987654321")
    Contact.objects.create(name="Sem telefone 1")
    Contact.objects.create(name="Sem telefone 2")

    with pytest.raises(IntegrityError):
        Contact.objects.create(phone="11987654321")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("channel", "hours_ago", "expected"),
    [
        (Channel.WHATSAPP, 23, True),
        (Channel.WHATSAPP, 25, False),
        (Channel.INSTAGRAM, 1, True),
        (Channel.EMAIL, 1000, True),
    ],
)
def test_service_window(channel: str, hours_ago: int, expected: bool) -> None:
    now = timezone.now()
    conversation = Conversation(channel=channel, last_inbound_at=now - timedelta(hours=hours_ago))

    assert conversation.is_service_window_open(now) is expected


def test_service_window_closed_when_contact_never_wrote() -> None:
    assert Conversation(channel=Channel.WHATSAPP).is_service_window_open() is False


@pytest.mark.parametrize(
    ("current", "new", "accepted"),
    [
        (MessageStatus.SENT, MessageStatus.DELIVERED, True),
        (MessageStatus.DELIVERED, MessageStatus.READ, True),
        (MessageStatus.SENT, MessageStatus.READ, True),
        (MessageStatus.READ, MessageStatus.DELIVERED, False),
        (MessageStatus.DELIVERED, MessageStatus.DELIVERED, False),
        (MessageStatus.SENT, MessageStatus.FAILED, True),
        (MessageStatus.DELIVERED, MessageStatus.FAILED, False),
        (MessageStatus.RECEIVED, MessageStatus.READ, False),
        (MessageStatus.SIMULATED, MessageStatus.SENT, False),
    ],
)
def test_message_status_never_regresses(current: str, new: str, accepted: bool) -> None:
    message = Message(channel=Channel.WHATSAPP, direction=MessageDirection.OUTBOUND, status=current)

    assert message.advance_status(new) is accepted
    assert message.status == (new if accepted else current)


@pytest.mark.django_db
def test_message_external_id_is_unique_per_channel() -> None:
    contact = Contact.objects.create(name="Ana")
    conversation = Conversation.objects.create(contact=contact, channel=Channel.WHATSAPP)
    fields = {
        "conversation": conversation,
        "direction": MessageDirection.INBOUND,
        "status": "received",
    }
    Message.objects.create(channel=Channel.WHATSAPP, external_id="wamid.1", **fields)
    Message.objects.create(channel=Channel.WHATSAPP, external_id="", **fields)
    Message.objects.create(channel=Channel.WHATSAPP, external_id="", **fields)

    with pytest.raises(IntegrityError):
        Message.objects.create(channel=Channel.WHATSAPP, external_id="wamid.1", **fields)


@pytest.mark.django_db
def test_record_event_is_idempotent_with_external_id() -> None:
    first, created_first = record_event(
        "comment.created", channel=Channel.INSTAGRAM, external_id="c1"
    )
    second, created_second = record_event(
        "comment.created", channel=Channel.INSTAGRAM, external_id="c1"
    )

    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk
    assert Event.objects.count() == 1


@pytest.mark.django_db
def test_grant_consent_keeps_a_single_active_record() -> None:
    contact = Contact.objects.create(name="Ana")

    first = grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")
    second = grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")

    assert first.pk == second.pk
    assert has_active_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING)
    assert not has_active_consent(contact, Channel.EMAIL, ConsentPurpose.MARKETING)
