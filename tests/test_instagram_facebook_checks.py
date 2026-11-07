"""Testes do facebook_check e do instagram_check, com a Graph API mockada."""

from io import StringIO
from typing import Any

import httpx
import pytest
import respx
from django.core.management import CommandError, call_command

from apps.credentials.models import IntegrationCredential, Platform
from apps.facebook.services import PAGE_WEBHOOK_FIELDS, page_access_token
from apps.instagram.services import INSTAGRAM_WEBHOOK_FIELDS
from apps.meta_business.services import app_subscription

GRAPH = "https://graph.facebook.com/v27.0"
PAGE_ID = "111"
IG_ID = "222"
PAGE_TOKEN = "token-de-teste-da-pagina"
APP_ID = "1234567890"

PAGE_DATA = {
    "id": PAGE_ID,
    "name": "Brave2Grow",
    "access_token": PAGE_TOKEN,
    "instagram_business_account": {"id": IG_ID},
}
ALL_TASKS = ["MANAGE", "CREATE_CONTENT", "MODERATE", "MESSAGING", "ADVERTISE", "ANALYZE"]
PAGE_TOKEN_DEBUG = {
    "app_id": APP_ID,
    "type": "PAGE",
    "application": "B2G Integrations Lab",
    "expires_at": 0,
    "is_valid": True,
    "scopes": ["pages_messaging", "pages_show_list"],
    "profile_id": PAGE_ID,
}


def _page_subscribed(fields: list[str]) -> dict[str, Any]:
    return {"data": [{"name": "B2G Integrations Lab", "id": APP_ID, "subscribed_fields": fields}]}


def _mock_page(fields: list[str] | None = None, *, tasks: list[str] | None = None) -> respx.Route:
    """Mocka a Página, me/accounts, o debug_token e o GET de subscribed_apps (devolvido)."""
    respx.get(f"{GRAPH}/{PAGE_ID}").mock(return_value=httpx.Response(200, json=PAGE_DATA))
    accounts = {"data": [{"id": "999", "tasks": ALL_TASKS}]}
    accounts["data"].append({"id": PAGE_ID, "tasks": ALL_TASKS if tasks is None else tasks})
    respx.get(f"{GRAPH}/me/accounts").mock(return_value=httpx.Response(200, json=accounts))
    respx.get(f"{GRAPH}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": PAGE_TOKEN_DEBUG})
    )
    body = _page_subscribed(list(PAGE_WEBHOOK_FIELDS) if fields is None else fields)
    return respx.get(f"{GRAPH}/{PAGE_ID}/subscribed_apps").mock(
        return_value=httpx.Response(200, json=body if fields != [] else {"data": []})
    )


def test_app_subscription_reads_page_and_instagram_formats() -> None:
    assert app_subscription(_page_subscribed(["feed"])) == ["feed"]
    instagram = {"data": [{"app_id": APP_ID, "subscribed_fields": ["comments"]}]}
    assert app_subscription(instagram) == ["comments"]
    assert app_subscription({"data": [{"id": "42", "subscribed_fields": ["feed"]}]}) is None


@pytest.mark.django_db
@respx.mock
def test_facebook_check_saves_page_token_and_reports() -> None:
    _mock_page()
    out = StringIO()

    call_command("facebook_check", stdout=out)

    output = out.getvalue()
    assert "nome: Brave2Grow" in output
    assert f"Instagram conectado: {IG_ID}" in output
    assert "válido: sim | expira: nunca" in output
    assert "campos: feed, messages" in output
    assert PAGE_TOKEN not in output
    credential = IntegrationCredential.objects.get(platform=Platform.FACEBOOK, label="page")
    assert (credential.account_id, credential.token_type) == (PAGE_ID, "page")
    assert page_access_token() == PAGE_TOKEN


@pytest.mark.django_db
@respx.mock
def test_facebook_check_uses_page_token_for_subscribed_apps() -> None:
    route = _mock_page()

    call_command("facebook_check", "--no-save", stdout=StringIO())

    call = route.calls.last
    assert call.request.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    assert not IntegrationCredential.objects.exists()


@pytest.mark.django_db
@respx.mock
def test_facebook_check_fails_when_app_is_not_subscribed() -> None:
    _mock_page(fields=[])

    with pytest.raises(CommandError, match="não está pronta"):
        call_command("facebook_check", "--no-save", stdout=StringIO())


@pytest.mark.django_db
@respx.mock
def test_facebook_check_reports_missing_fields_and_tasks() -> None:
    _mock_page(fields=["feed", "messages"], tasks=["ANALYZE"])
    out = StringIO()

    with pytest.raises(CommandError):
        call_command("facebook_check", "--no-save", stdout=out)

    output = out.getvalue()
    assert "Faltam tarefas na Página (MESSAGING, MODERATE, CREATE_CONTENT)" in output
    assert "Campos não assinados na Página: messaging_postbacks" in output


@pytest.mark.django_db
@respx.mock
def test_facebook_check_subscribe_posts_the_lab_fields() -> None:
    _mock_page()
    route = respx.post(f"{GRAPH}/{PAGE_ID}/subscribed_apps").mock(
        return_value=httpx.Response(200, json={"success": True})
    )

    call_command("facebook_check", "--subscribe", "--no-save", stdout=StringIO())

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    assert b"subscribed_fields=feed%2Cmessages%2C" in request.content


@pytest.mark.django_db
def test_facebook_check_requires_page_id(settings: Any) -> None:
    settings.FACEBOOK_PAGE_ID = ""

    with pytest.raises(CommandError, match="ID da Página"):
        call_command("facebook_check", stdout=StringIO())


def _mock_instagram(*, fields: list[str] | None = None, conversations_status: int = 200) -> None:
    respx.get(f"{GRAPH}/{IG_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": IG_ID,
                "username": "brave2grow",
                "name": "Brave2Grow Tecnologia",
                "followers_count": 31,
                "media_count": 0,
            },
        )
    )
    error = {"error": {"message": "Access to messages is disabled", "code": 200}}
    respx.get(f"{GRAPH}/{IG_ID}/conversations").mock(
        return_value=httpx.Response(conversations_status, json={"data": []})
        if conversations_status == 200
        else httpx.Response(conversations_status, json=error)
    )
    subscribed = list(INSTAGRAM_WEBHOOK_FIELDS) if fields is None else fields
    respx.get(f"{GRAPH}/{IG_ID}/subscribed_apps").mock(
        return_value=httpx.Response(
            200, json={"data": [{"app_id": APP_ID, "subscribed_fields": subscribed}]}
        )
    )
    respx.get(f"{GRAPH}/{IG_ID}/content_publishing_limit").mock(
        return_value=httpx.Response(
            200, json={"data": [{"config": {"quota_total": 100}, "quota_usage": 2}]}
        )
    )


@pytest.mark.django_db
@respx.mock
def test_instagram_check_reports_account(settings: Any) -> None:
    settings.INSTAGRAM_BUSINESS_ACCOUNT_ID = IG_ID
    _mock_instagram()
    out = StringIO()

    call_command("instagram_check", stdout=out)

    output = out.getvalue()
    assert "@brave2grow (Brave2Grow Tecnologia)" in output
    assert "leitura de conversas: ok" in output
    assert "campos: comments, mentions, messages" in output
    assert "cota usada nas últimas 24h: 2 de 100" in output


@pytest.mark.django_db
@respx.mock
def test_instagram_check_explains_disabled_message_access(settings: Any) -> None:
    settings.INSTAGRAM_BUSINESS_ACCOUNT_ID = IG_ID
    _mock_instagram(conversations_status=403)
    out = StringIO()

    with pytest.raises(CommandError, match="não está pronto"):
        call_command("instagram_check", stdout=out)

    assert "Permitir acesso às mensagens" in out.getvalue()


@pytest.mark.django_db
@respx.mock
def test_instagram_check_subscribe_posts_the_lab_fields(settings: Any) -> None:
    settings.INSTAGRAM_BUSINESS_ACCOUNT_ID = IG_ID
    _mock_instagram(fields=["comments"])
    route = respx.post(f"{GRAPH}/{IG_ID}/subscribed_apps").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    out = StringIO()

    with pytest.raises(CommandError):  # o GET mockado continua só com comments
        call_command("instagram_check", "--subscribe", stdout=out)

    assert b"subscribed_fields=comments%2Cmentions%2Cmessages" in route.calls.last.request.content
    assert "Campos não assinados na conta: mentions" in out.getvalue()


@pytest.mark.django_db
def test_instagram_check_requires_account_id(settings: Any) -> None:
    settings.INSTAGRAM_BUSINESS_ACCOUNT_ID = ""

    with pytest.raises(CommandError, match="ID da conta do Instagram"):
        call_command("instagram_check", stdout=StringIO())
