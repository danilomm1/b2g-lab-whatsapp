"""Testes do app credentials: criptografia em repouso, validade e renovação."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.credentials import services
from apps.credentials.models import CredentialStatus, IntegrationCredential, Platform
from apps.credentials.services import (
    CredentialNotFound,
    get_credential,
    refresh_expiring,
    save_token,
)

pytestmark = pytest.mark.django_db

TOKEN = "EAAG-token-de-teste-1234567890"


def _raw_access_token(credential_id: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT access_token FROM credentials_integrationcredential WHERE id = %s",
            [credential_id],
        )
        return cursor.fetchone()[0]


def test_token_is_encrypted_at_rest() -> None:
    credential = save_token(Platform.META, access_token=TOKEN)

    raw = _raw_access_token(credential.pk)
    assert TOKEN not in raw
    assert raw.startswith("gAAAAA")  # prefixo de um token Fernet
    assert IntegrationCredential.objects.get(pk=credential.pk).access_token == TOKEN


def test_key_rotation_keeps_tokens_readable(settings: Any) -> None:
    old_key = settings.FIELD_ENCRYPTION_KEY[0]
    new_key = Fernet.generate_key().decode()
    credential = save_token(Platform.META, access_token=TOKEN)

    settings.FIELD_ENCRYPTION_KEY = [new_key, old_key]
    assert IntegrationCredential.objects.get(pk=credential.pk).access_token == TOKEN
    call_command("reencrypt_credentials", stdout=None)

    settings.FIELD_ENCRYPTION_KEY = [new_key]
    assert IntegrationCredential.objects.get(pk=credential.pk).access_token == TOKEN


def test_missing_key_fails_loudly(settings: Any) -> None:
    settings.FIELD_ENCRYPTION_KEY = []

    with pytest.raises(ImproperlyConfigured, match="FIELD_ENCRYPTION_KEY"):
        save_token(Platform.META, access_token=TOKEN)


def test_save_token_with_expires_in() -> None:
    credential = save_token(
        Platform.GOOGLE, access_token=TOKEN, expires_in=3600, scopes=["youtube"]
    )

    assert credential.expires_at is not None
    assert timedelta(minutes=59) < credential.expires_at - timezone.now() <= timedelta(hours=1)
    assert credential.scopes == ["youtube"]


@pytest.mark.parametrize(
    ("expires_in_days", "is_active", "expected"),
    [
        (None, True, CredentialStatus.OK),
        (30, True, CredentialStatus.OK),
        (3, True, CredentialStatus.EXPIRING),
        (-1, True, CredentialStatus.EXPIRED),
        (30, False, CredentialStatus.INACTIVE),
    ],
)
def test_credential_status(expires_in_days: int | None, is_active: bool, expected: str) -> None:
    expires_at = (
        None if expires_in_days is None else timezone.now() + timedelta(days=expires_in_days)
    )
    credential = IntegrationCredential(
        platform=Platform.META, expires_at=expires_at, is_active=is_active
    )

    assert credential.status() == expected


def test_get_credential_ignores_inactive() -> None:
    save_token(Platform.THREADS, access_token=TOKEN)
    IntegrationCredential.objects.update(is_active=False)

    with pytest.raises(CredentialNotFound):
        get_credential(Platform.THREADS)


@pytest.fixture
def isolated_refreshers() -> Iterator[None]:
    original = dict(services._refreshers)
    yield
    services._refreshers.clear()
    services._refreshers.update(original)


@pytest.mark.usefixtures("isolated_refreshers")
def test_refresh_expiring_uses_registered_refresher() -> None:
    save_token(Platform.THREADS, access_token="antigo", expires_in=3600)
    save_token(Platform.GOOGLE, access_token="sem-renovacao", expires_in=3600)
    save_token(Platform.META, access_token="longe", expires_at=timezone.now() + timedelta(days=60))

    @services.register_refresher(Platform.THREADS)
    def refresh(credential: IntegrationCredential) -> None:
        credential.access_token = "novo"
        credential.expires_at = timezone.now() + timedelta(days=60)

    report = refresh_expiring()

    refreshed = get_credential(Platform.THREADS)
    assert refreshed.access_token == "novo"
    assert refreshed.last_refreshed_at is not None
    assert len(report.refreshed) == 1
    assert len(report.without_refresher) == 1


@pytest.mark.usefixtures("isolated_refreshers")
def test_refresh_failure_is_recorded() -> None:
    save_token(Platform.THREADS, access_token="antigo", expires_in=3600)

    @services.register_refresher(Platform.THREADS)
    def refresh(credential: IntegrationCredential) -> None:
        raise RuntimeError("token revogado")

    report = refresh_expiring()

    credential = get_credential(Platform.THREADS)
    assert len(report.failed) == 1
    assert "token revogado" in credential.last_error
    assert credential.access_token == "antigo"


def test_admin_never_renders_token(admin_client: Client) -> None:
    credential = save_token(Platform.META, access_token=TOKEN)

    url = reverse("admin:credentials_integrationcredential_change", args=[credential.pk])
    content = admin_client.get(url).content.decode()

    assert TOKEN not in content
    assert "••••7890" in content


def test_admin_blank_token_field_keeps_current(admin_client: Client) -> None:
    credential = save_token(Platform.META, access_token=TOKEN)
    url = reverse("admin:credentials_integrationcredential_change", args=[credential.pk])
    form = {
        "platform": Platform.META,
        "label": "default",
        "account_id": "123",
        "is_active": "on",
        "new_access_token": "",
        "new_refresh_token": "",
        "token_type": "system_user",
        "scopes": "[]",
        "metadata": "{}",
    }

    response = admin_client.post(url, form)
    assert response.status_code == 302
    assert IntegrationCredential.objects.get(pk=credential.pk).access_token == TOKEN

    admin_client.post(url, {**form, "new_access_token": "token-novo"})
    assert IntegrationCredential.objects.get(pk=credential.pk).access_token == "token-novo"
