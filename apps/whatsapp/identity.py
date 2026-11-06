"""Identificação de contatos do WhatsApp pelo BSUID e pelo telefone (ADR 0006).

Desde abril de 2026 os webhooks trazem o BSUID (user_id), estável por portfólio e
sempre presente. O telefone (wa_id/from) pode faltar para quem adotou nome de usuário.
Por isso a identidade do canal é o BSUID, e o telefone vai para Contact.phone quando vier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.core.models import Channel, ChannelIdentity, Contact
from apps.core.phone import InvalidPhoneNumber, normalize_phone

INBOUND_SOURCE = "whatsapp_inbound"


def normalize_wa_id(wa_id: str) -> str | None:
    """Converte o wa_id (DDI sem "+") em E.164, ou None se não for um telefone válido.

    Celulares brasileiros cadastrados antes do nono dígito chegam como 55 + DDD + 8
    dígitos; nesse caso o 9 é inserido, que é o número que a pessoa reconhece como seu.
    """
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if not digits:
        return None
    candidates = [digits]
    if len(digits) == 12 and digits.startswith("55") and digits[4] in "6789":
        candidates.append(f"{digits[:4]}9{digits[4:]}")
    for candidate in candidates:
        try:
            return normalize_phone(candidate, assume_international=True)
        except InvalidPhoneNumber:
            continue
    return None


@dataclass(frozen=True)
class Sender:
    """Quem escreveu, como a Meta informa no webhook."""

    user_id: str = ""  # BSUID, ex.: BR.13491208655302741918
    wa_id: str = ""
    name: str = ""
    username: str = ""

    @property
    def external_id(self) -> str:
        """Chave da identidade: o BSUID; o wa_id só para payloads anteriores ao BSUID."""
        return self.user_id or self.wa_id


def _find_identity(waba_id: str, external_id: str) -> ChannelIdentity | None:
    return (
        ChannelIdentity.objects.select_related("contact")
        .filter(channel=Channel.WHATSAPP, account_id=waba_id, external_id=external_id)
        .first()
    )


def _fill_missing_contact_data(contact: Contact, *, name: str, phone: str | None) -> None:
    """Completa nome e telefone vazios, sem sobrescrever o que já existe."""
    changed = []
    if name and not contact.name:
        contact.name = name
        changed.append("name")
    if (
        phone
        and not contact.phone
        and not Contact.objects.filter(phone=phone).exclude(pk=contact.pk).exists()
    ):
        contact.phone = phone
        changed.append("phone")
    if changed:
        contact.save()


def resolve_sender(sender: Sender, *, waba_id: str, seen_at: datetime) -> ChannelIdentity:
    """Encontra ou cria o contato e a identidade de quem escreveu."""
    phone = normalize_wa_id(sender.wa_id) if sender.wa_id else None
    identity = _find_identity(waba_id, sender.external_id)
    if identity is None and sender.user_id and sender.wa_id:
        # Identidade gravada antes do BSUID, pela chave wa_id: passa a usar o BSUID
        identity = _find_identity(waba_id, sender.wa_id)
        if identity is not None:
            identity.external_id = sender.user_id

    if identity is None:
        contact = Contact.objects.filter(phone=phone).first() if phone else None
        if contact is None:
            contact = Contact.objects.create(
                name=sender.name, phone=phone or "", source=INBOUND_SOURCE
            )
        identity = ChannelIdentity(
            contact=contact,
            channel=Channel.WHATSAPP,
            account_id=waba_id,
            external_id=sender.external_id,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )

    if sender.username:
        identity.handle = sender.username
    identity.last_seen_at = max(identity.last_seen_at or seen_at, seen_at)
    identity.save()
    _fill_missing_contact_data(identity.contact, name=sender.name, phone=phone)
    return identity


def apply_identity_change(system: dict[str, object], *, waba_id: str) -> ChannelIdentity | None:
    """Trata user_changed_number e user_changed_user_id: o BSUID antigo passa a valer o novo.

    O telefone novo, quando vem, substitui o do contato se nenhum outro contato o usa.
    Retorna a identidade atualizada, ou None se o BSUID antigo não é conhecido.
    """
    previous = str(system.get("previous_user_id") or "")
    current = str(system.get("user_id") or "")
    if not previous or not current:
        return None
    identity = _find_identity(waba_id, previous)
    if identity is None:
        return None
    if _find_identity(waba_id, current) is None:
        identity.external_id = current
        identity.save(update_fields=["external_id"])

    new_phone = normalize_wa_id(str(system.get("wa_id") or ""))
    contact = identity.contact
    if (
        new_phone
        and contact.phone != new_phone
        and not Contact.objects.filter(phone=new_phone).exclude(pk=contact.pk).exists()
    ):
        contact.phone = new_phone
        contact.save()
    return identity
