"""Testes das travas de segurança operacional (CLAUDE.md, seção 8)."""

from datetime import timedelta
from typing import Any

import pytest
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
from apps.core.safety import (
    check_outbound,
    check_proactive_contact,
    effective_dry_run,
    is_opt_out_message,
)
from apps.core.services import apply_opt_out, grant_consent, has_active_consent
from apps.core.signals import contact_opted_out


@pytest.mark.parametrize("text", ["SAIR", "sair", "Parar!", "  stop. ", "Sair 🙏"])
def test_opt_out_keywords(text: str) -> None:
    assert is_opt_out_message(text)


@pytest.mark.parametrize("text", ["não quero sair agora", "parar de receber?", "", "ok"])
def test_messages_that_are_not_opt_out(text: str) -> None:
    assert not is_opt_out_message(text)


@pytest.mark.parametrize(
    ("global_flag", "param", "expected"),
    [
        (True, None, True),
        (True, False, True),  # a flag global sempre vence
        (False, None, False),
        (False, True, True),
        (False, False, False),
    ],
)
def test_effective_dry_run(
    settings: Any, global_flag: bool, param: bool | None, expected: bool
) -> None:
    settings.LAB_DRY_RUN = global_flag

    assert effective_dry_run(param) is expected


def test_check_outbound_simulates_in_dry_run() -> None:
    decision = check_outbound("+5511987654321")

    assert decision.dry_run
    assert not decision.send_for_real


def test_check_outbound_blocks_recipient_outside_allowlist(settings: Any) -> None:
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = ["+5511987654321"]

    decision = check_outbound("+5511912345678")

    assert not decision.allowed
    assert not decision.send_for_real


@pytest.mark.parametrize("recipient", ["(11) 98765-4321", "+5511987654321", "DANILO@Exemplo.com"])
def test_check_outbound_allows_allowlisted_in_any_format(settings: Any, recipient: str) -> None:
    settings.LAB_DRY_RUN = False
    settings.LAB_ALLOWED_RECIPIENTS = ["+55 11 98765-4321", "danilo@exemplo.com"]

    assert check_outbound(recipient).send_for_real


@pytest.fixture
def contact_with_consent(db: Any) -> Contact:
    contact = Contact.objects.create(name="Ana", phone="+5511987654321")
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING, source="teste")
    return contact


def _proactive_message(contact: Contact, status: str, days_ago: int = 0) -> Message:
    conversation, _ = Conversation.objects.get_or_create(contact=contact, channel=Channel.WHATSAPP)
    return Message.objects.create(
        conversation=conversation,
        channel=Channel.WHATSAPP,
        direction=MessageDirection.OUTBOUND,
        status=status,
        is_proactive=True,
        created_at=timezone.now() - timedelta(days=days_ago),
    )


@pytest.mark.django_db
def test_proactive_contact_requires_consent() -> None:
    contact = Contact.objects.create(name="Sem consentimento")

    decision = check_proactive_contact(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING)

    assert not decision.allowed
    assert "consentimento" in decision.reason


def test_proactive_contact_allowed_with_consent(contact_with_consent: Contact) -> None:
    assert check_proactive_contact(
        contact_with_consent, Channel.WHATSAPP, ConsentPurpose.MARKETING
    ).allowed


def test_proactive_weekly_limit(contact_with_consent: Contact) -> None:
    for _ in range(3):
        _proactive_message(contact_with_consent, MessageStatus.SENT)

    decision = check_proactive_contact(
        contact_with_consent, Channel.WHATSAPP, ConsentPurpose.MARKETING
    )

    assert not decision.allowed
    assert "limite" in decision.reason


def test_proactive_limit_ignores_simulated_and_old(contact_with_consent: Contact) -> None:
    for _ in range(3):
        _proactive_message(contact_with_consent, MessageStatus.SIMULATED)
    _proactive_message(contact_with_consent, MessageStatus.SENT, days_ago=8)
    _proactive_message(contact_with_consent, MessageStatus.SENT, days_ago=8)
    _proactive_message(contact_with_consent, MessageStatus.SENT, days_ago=8)

    assert check_proactive_contact(
        contact_with_consent, Channel.WHATSAPP, ConsentPurpose.MARKETING
    ).allowed


def test_opt_out_revokes_channel_consents_and_notifies(
    contact_with_consent: Contact, django_capture_on_commit_callbacks: Any
) -> None:
    contact = contact_with_consent
    grant_consent(contact, Channel.WHATSAPP, ConsentPurpose.SERVICE, source="teste")
    grant_consent(contact, Channel.EMAIL, ConsentPurpose.MARKETING, source="teste")
    received: list[dict[str, Any]] = []

    def listener(**kwargs: Any) -> None:
        received.append(kwargs)

    contact_opted_out.connect(listener)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            revoked = apply_opt_out(contact, Channel.WHATSAPP, source="whatsapp:SAIR")
    finally:
        contact_opted_out.disconnect(listener)

    assert revoked == 2
    assert not has_active_consent(contact, Channel.WHATSAPP, ConsentPurpose.MARKETING)
    assert not has_active_consent(contact, Channel.WHATSAPP, ConsentPurpose.SERVICE)
    assert has_active_consent(contact, Channel.EMAIL, ConsentPurpose.MARKETING)
    assert Event.objects.filter(contact=contact, event_type="consent.revoked").exists()
    assert received and received[0]["channel"] == Channel.WHATSAPP
