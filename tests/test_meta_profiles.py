"""Testes da busca de perfil (nome e @) de quem escreve no Instagram e no Messenger."""

from typing import Any

import httpx
import pytest
import respx

from apps.core.models import Channel, ChannelIdentity, Contact
from apps.credentials.models import Platform
from apps.credentials.services import save_token
from apps.meta_business.profiles import fetch_profile
from apps.webhooks.models import DeliveryStatus, WebhookDelivery

GRAPH = "https://graph.facebook.com/v27.0"
IG_ID = "17840000000000001"
IGSID = "2860000000000001"
PAGE_ID = "111"
PSID = "3970000000000001"
PAGE_TOKEN = "token-de-teste-da-pagina"
TS = 1_794_047_902_403


@pytest.fixture
def page_token() -> None:
    save_token(Platform.FACEBOOK, label="page", access_token=PAGE_TOKEN, account_id=PAGE_ID)


def _message(obj: str, account_id: str, user_id: str, mid: str) -> dict[str, Any]:
    event = {
        "sender": {"id": user_id},
        "recipient": {"id": account_id},
        "timestamp": TS,
        "message": {"mid": mid, "text": "Oi"},
    }
    return {"object": obj, "entry": [{"id": account_id, "time": TS, "messaging": [event]}]}


@pytest.mark.django_db
@respx.mock
def test_new_instagram_contact_gets_username_from_profile(meta_post: Any, page_token: None) -> None:
    route = respx.get(f"{GRAPH}/{IGSID}").mock(
        return_value=httpx.Response(200, json={"username": "jose.teste", "id": IGSID})
    )

    meta_post(_message("instagram", IG_ID, IGSID, "aWdfZAG1"))

    assert route.calls.last.request.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    assert route.calls.last.request.url.params["fields"] == "name,username"
    contact = Contact.objects.get()
    assert contact.instagram_handle == "jose.teste"
    assert contact.name == ""
    assert ChannelIdentity.objects.get().handle == "jose.teste"


@pytest.mark.django_db
@respx.mock
def test_new_messenger_contact_gets_name_once(meta_post: Any, page_token: None) -> None:
    route = respx.get(f"{GRAPH}/{PSID}").mock(
        return_value=httpx.Response(
            200, json={"first_name": "Bravo", "last_name": "To Grow", "name": "Bravo To Grow"}
        )
    )

    meta_post(_message("page", PAGE_ID, PSID, "m_1"))
    meta_post(_message("page", PAGE_ID, PSID, "m_2"))

    assert route.call_count == 1  # só quando a identidade nasce
    assert Contact.objects.get().name == "Bravo To Grow"


@pytest.mark.django_db
@respx.mock
def test_profile_error_does_not_break_the_delivery(meta_post: Any, page_token: None) -> None:
    respx.get(f"{GRAPH}/{PSID}").mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "No profile available", "code": 100}}
        )
    )

    meta_post(_message("page", PAGE_ID, PSID, "m_1"))

    assert WebhookDelivery.objects.get().status == DeliveryStatus.PROCESSED
    assert Contact.objects.get().name == ""


@pytest.mark.django_db
@respx.mock
def test_without_page_token_no_request_is_made(meta_post: Any) -> None:
    # respx.mock sem rotas: qualquer chamada à Graph API falharia o teste
    meta_post(_message("instagram", IG_ID, IGSID, "aWdfZAG1"))

    assert Contact.objects.count() == 1
    assert not respx.calls


@pytest.mark.django_db
@respx.mock
def test_profile_does_not_overwrite_existing_name(page_token: None) -> None:
    contact = Contact.objects.create(name="Danilo")
    identity = ChannelIdentity.objects.create(
        contact=contact, channel=Channel.FACEBOOK, account_id=PAGE_ID, external_id=PSID
    )
    respx.get(f"{GRAPH}/{PSID}").mock(
        return_value=httpx.Response(200, json={"name": "Bravo To Grow"})
    )

    assert fetch_profile(identity.pk) is True
    contact.refresh_from_db()
    assert contact.name == "Danilo"
