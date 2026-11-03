"""Normalização de telefones para E.164 (+5511...)."""

import phonenumbers


class InvalidPhoneNumber(ValueError):
    """Telefone que não pode ser convertido para um número válido em E.164."""


def normalize_phone(
    raw: str, *, default_region: str = "BR", assume_international: bool = False
) -> str:
    """Converte um telefone para E.164.

    Sem DDI, assume o Brasil. Para identificadores que já trazem o DDI sem o "+"
    (como o wa_id do WhatsApp), use assume_international=True, senão um número
    estrangeiro seria lido como brasileiro.
    """
    value = raw.strip()
    if assume_international and not value.startswith("+"):
        value = f"+{value}"
    try:
        parsed = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneNumber(f"Telefone inválido: {raw!r}") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber(f"Telefone inválido: {raw!r}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
