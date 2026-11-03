"""Operações sobre o modelo central: eventos e consentimentos."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Consent, Contact, Event
from .signals import contact_opted_out


def record_event(
    event_type: str,
    *,
    contact: Contact | None = None,
    channel: str = "",
    external_id: str = "",
    occurred_at: datetime | None = None,
    summary: str = "",
    data: dict[str, Any] | None = None,
) -> tuple[Event, bool]:
    """Registra um evento na linha do tempo. Com external_id, é idempotente.

    Retorna (evento, criado).
    """
    defaults = {
        "contact": contact,
        "occurred_at": occurred_at or timezone.now(),
        "summary": summary[:255],
        "data": data or {},
    }
    if external_id:
        return Event.objects.get_or_create(
            channel=channel, event_type=event_type, external_id=external_id, defaults=defaults
        )
    return Event.objects.create(channel=channel, event_type=event_type, **defaults), True


def has_active_consent(contact: Contact, channel: str, purpose: str) -> bool:
    """Indica se o contato tem consentimento ativo para o canal e a finalidade."""
    return contact.consents.active().filter(channel=channel, purpose=purpose).exists()


def grant_consent(
    contact: Contact,
    channel: str,
    purpose: str,
    *,
    source: str,
    consent_text: str = "",
    evidence: dict[str, Any] | None = None,
) -> Consent:
    """Registra um consentimento. Se já houver um ativo para o mesmo par, devolve o existente."""
    existing = contact.consents.active().filter(channel=channel, purpose=purpose).first()
    if existing:
        return existing
    return Consent.objects.create(
        contact=contact,
        channel=channel,
        purpose=purpose,
        source=source,
        consent_text=consent_text,
        evidence=evidence or {},
    )


@transaction.atomic
def apply_opt_out(contact: Contact, channel: str, *, source: str) -> int:
    """Aplica a palavra de saída: revoga todos os consentimentos do canal e avisa os outros apps.

    Retorna quantos consentimentos foram revogados.
    """
    now = timezone.now()
    revoked = (
        contact.consents.active()
        .filter(channel=channel)
        .update(revoked_at=now, revocation_source=source)
    )
    record_event(
        "consent.revoked",
        contact=contact,
        channel=channel,
        occurred_at=now,
        summary=f"Saída pedida pelo contato ({source})",
        data={"revoked_count": revoked, "source": source},
    )
    transaction.on_commit(
        lambda: contact_opted_out.send(
            sender=Contact, contact=contact, channel=channel, source=source
        )
    )
    return revoked
