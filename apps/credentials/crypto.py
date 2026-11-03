"""Criptografia simétrica (Fernet) para segredos guardados no banco."""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def get_cipher() -> MultiFernet:
    """Monta o cifrador a partir de FIELD_ENCRYPTION_KEY.

    A primeira chave criptografa; as seguintes só descriptografam, o que permite rotação.
    """
    keys = settings.FIELD_ENCRYPTION_KEY
    if isinstance(keys, str):
        keys = keys.split(",")
    keys = [key.strip() for key in keys if key and key.strip()]
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY não configurada. Gere uma com: "
            "python manage.py generate_encryption_key"
        )
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except ValueError as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY inválida: cada chave deve ser uma chave Fernet (base64)."
        ) from exc


def encrypt(value: str) -> str:
    return get_cipher().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return get_cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Não foi possível descriptografar um valor do banco. Confira FIELD_ENCRYPTION_KEY: "
            "durante uma rotação, a chave antiga precisa continuar na lista."
        ) from exc


def generate_key() -> str:
    return Fernet.generate_key().decode()
