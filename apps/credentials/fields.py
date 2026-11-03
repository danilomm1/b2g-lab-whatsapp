"""Campos de model criptografados em repouso."""

from typing import Any

from django.db import models

from .crypto import decrypt, encrypt


class EncryptedTextField(models.TextField):
    """TextField gravado criptografado (Fernet). Em memória, o valor fica em texto puro.

    A criptografia não é determinística: não dá para filtrar pelo conteúdo, só por vazio.
    """

    def from_db_value(self, value: str | None, expression: Any, connection: Any) -> str | None:
        if not value:
            return value
        return decrypt(value)

    def get_prep_value(self, value: Any) -> str | None:
        value = super().get_prep_value(value)
        if not value:
            return value
        return encrypt(value)
