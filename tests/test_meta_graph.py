"""Testes do cliente da Graph API, do debug_token e do comando meta_check (tudo mockado)."""

import json
import logging
from io import StringIO
from typing import Any

import httpx
import pytest
import respx
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command

from apps.credentials.models import IntegrationCredential, Platform
from apps.meta_business.client import GraphAPIError, GraphClient, appsecret_proof
from apps.meta_business.services import (
    TokenInfo,
    check_assets,
    inspect_token,
    sync_system_user_credential,
)

GRAPH = "https://graph.facebook.com/v26.0"
TOKEN = "token-de-teste-do-system-user"

DEBUG_TOKEN_DATA = {
    "app_id": "1234567890",
    "application": "B2G Integrations Lab",
    "type": "SYSTEM_USER",
    "is_valid": True,
    "expires_at": 0,
    "data_access_expires_at": 0,
    "scopes": ["pages_messaging", "pages_manage_metadata", "whatsapp_business_messaging"],
    "granular_scopes": [
        {"scope": "pages_messaging", "target_ids": ["111"]},
        {"scope": "pages_manage_metadata"},
        {"scope": "whatsapp_business_messaging", "target_ids": ["999"]},
    ],
    "user_id": "61550000000000",
}


def _client(**kwargs: Any) -> tuple[GraphClient, list[float]]:
    sleeps: list[float] = []
    return GraphClient(sleep=sleeps.append, **kwargs), sleeps


def _graph_error(code: int, status: int = 400, **extra: Any) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {"message": f"erro {code}", "type": "OAuthException", "code": code, **extra}
        },
    )


@respx.mock
def test_get_sends_token_in_header_and_appsecret_proof() -> None:
    route = respx.get(f"{GRAPH}/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    client, _ = _client()

    assert client.get("me", {"fields": "id"}) == {"id": "1"}

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert request.url.params["appsecret_proof"] == appsecret_proof(
        TOKEN, "segredo-do-app-de-teste"
    )


@respx.mock
def test_app_token_goes_without_appsecret_proof() -> None:
    route = respx.get(f"{GRAPH}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": DEBUG_TOKEN_DATA})
    )

    inspect_token(TOKEN)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer 1234567890|segredo-do-app-de-teste"
    assert "appsecret_proof" not in request.url.params
    assert request.url.params["input_token"] == TOKEN


@respx.mock
def test_transient_error_is_retried_with_exponential_backoff() -> None:
    respx.get(f"{GRAPH}/me").mock(
        side_effect=[_graph_error(2), _graph_error(1), httpx.Response(200, json={"id": "1"})]
    )
    client, sleeps = _client()

    assert client.get("me") == {"id": "1"}
    assert sleeps == [1.0, 2.0]


@respx.mock
def test_network_error_gives_up_after_max_retries() -> None:
    route = respx.get(f"{GRAPH}/me").mock(side_effect=httpx.ConnectError("sem rede"))
    client, sleeps = _client(max_retries=2)

    with pytest.raises(GraphAPIError) as excinfo:
        client.get("me")

    assert excinfo.value.network
    assert route.call_count == 3
    assert sleeps == [1.0, 2.0]


@respx.mock
def test_server_error_without_json_is_transient() -> None:
    respx.get(f"{GRAPH}/me").mock(
        side_effect=[httpx.Response(503, text="indisponível"), httpx.Response(200, json={})]
    )
    client, sleeps = _client()

    assert client.get("me") == {}
    assert sleeps == [1.0]


@respx.mock
def test_rate_limit_with_long_wait_is_handed_back_to_the_caller() -> None:
    usage = {"999": [{"type": "messenger", "estimated_time_to_regain_access": 5}]}
    route = respx.get(f"{GRAPH}/me").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"message": "limite", "code": 80006}},
            headers={"X-Business-Use-Case-Usage": json.dumps(usage)},
        )
    )
    client, sleeps = _client()

    with pytest.raises(GraphAPIError) as excinfo:
        client.get("me")

    assert excinfo.value.is_rate_limit
    assert excinfo.value.retry_after == 300
    assert route.call_count == 1  # 5 minutos passa de max_wait: não fica bloqueado esperando
    assert sleeps == []


@respx.mock
def test_auth_error_is_not_retried_and_is_logged_without_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = respx.get(f"{GRAPH}/me").mock(
        return_value=_graph_error(190, error_subcode=463, fbtrace_id="AbC123")
    )
    client, sleeps = _client()

    with caplog.at_level(logging.WARNING), pytest.raises(GraphAPIError) as excinfo:
        client.get("me")

    error = excinfo.value
    assert error.is_auth_error and not error.is_transient
    assert (error.code, error.subcode, error.fbtrace_id) == (190, 463, "AbC123")
    assert route.call_count == 1
    assert sleeps == []
    assert "AbC123" in caplog.text  # resposta completa registrada
    assert TOKEN not in caplog.text


def test_missing_token_fails_before_calling(settings: Any) -> None:
    settings.META_SYSTEM_USER_TOKEN = ""

    with pytest.raises(ImproperlyConfigured):
        GraphClient().get("me")


def _info(**overrides: Any) -> TokenInfo:
    return TokenInfo.from_debug_token({**DEBUG_TOKEN_DATA, **overrides})


def test_token_info_interprets_debug_token() -> None:
    info = _info()

    assert info.is_valid
    assert info.token_type == "SYSTEM_USER"
    assert info.expires_at is None  # expires_at = 0: não expira
    assert info.matches_configured_app


def test_check_assets_uses_granular_target_ids() -> None:
    checks = {check.setting: check for check in check_assets(_info())}

    page = checks["FACEBOOK_PAGE_ID"]
    assert set(page.reachable_scopes) == {"pages_messaging", "pages_manage_metadata"}
    # A permissão do WhatsApp só vale para a WABA 999, e o .env aponta para a 333
    assert checks["WHATSAPP_BUSINESS_ACCOUNT_ID"].reachable_scopes == ()
    assert not checks["INSTAGRAM_BUSINESS_ACCOUNT_ID"].is_configured


@pytest.mark.django_db
def test_sync_system_user_credential() -> None:
    credential = sync_system_user_credential(TOKEN, _info())

    stored = IntegrationCredential.objects.get(platform=Platform.META, label="system_user")
    assert stored.pk == credential.pk
    assert stored.access_token == TOKEN
    assert stored.expires_at is None
    assert stored.account_id == "61550000000000"
    assert stored.metadata["app_id"] == "1234567890"
    assert stored.is_active


@pytest.mark.django_db
def test_sync_marks_invalid_token_inactive() -> None:
    info = _info(is_valid=False, error={"code": 190, "message": "Session has expired"})

    credential = sync_system_user_credential(TOKEN, info)

    assert not credential.is_active
    assert "expired" in credential.last_error


@pytest.mark.django_db
@respx.mock
def test_meta_check_command_reports_and_saves() -> None:
    respx.get(f"{GRAPH}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": DEBUG_TOKEN_DATA})
    )
    out = StringIO()

    call_command("meta_check", stdout=out)

    output = out.getvalue()
    assert "válido: sim" in output
    assert "expira: nunca" in output
    assert "FACEBOOK_PAGE_ID 111: alcançado por" in output
    assert "WHATSAPP_BUSINESS_ACCOUNT_ID 333: o token NÃO alcança" in output
    assert TOKEN not in output
    assert IntegrationCredential.objects.filter(label="system_user").exists()


@pytest.mark.django_db
@respx.mock
def test_meta_check_tells_missing_scope_apart_from_unassigned_asset(settings: Any) -> None:
    # O token não tem nenhuma permissão de Instagram: o problema é o caso de uso, não a atribuição
    settings.INSTAGRAM_BUSINESS_ACCOUNT_ID = "222"
    respx.get(f"{GRAPH}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": DEBUG_TOKEN_DATA})
    )
    out = StringIO()

    call_command("meta_check", "--no-save", stdout=out)

    output = out.getvalue()
    assert "INSTAGRAM_BUSINESS_ACCOUNT_ID 222: o token não tem nenhuma das permissões" in output
    assert "WHATSAPP_BUSINESS_ACCOUNT_ID 333: o token NÃO alcança" in output


@pytest.mark.django_db
@respx.mock
def test_meta_check_fails_when_token_belongs_to_another_app() -> None:
    respx.get(f"{GRAPH}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": {**DEBUG_TOKEN_DATA, "app_id": "42"}})
    )

    with pytest.raises(CommandError, match="não está pronto"):
        call_command("meta_check", "--no-save", stdout=StringIO())

    assert not IntegrationCredential.objects.exists()


@pytest.mark.django_db
def test_meta_check_requires_settings(settings: Any) -> None:
    settings.META_APP_SECRET = ""

    with pytest.raises(CommandError, match="App Secret"):
        call_command("meta_check", stdout=StringIO())
