"""Testes do provedor de webhook da Meta: handshake, assinatura e roteamento por object."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.test import Client

from apps.meta_business.webhook import SIGNATURE_HEADER
from apps.webhooks.models import DeliveryStatus, WebhookDelivery
from apps.webhooks.registry import registry
from apps.webhooks.signatures import sign_body

WHATSAPP_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "333",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "444"},
                        "messages": [{"from": "5511987654321", "id": "wamid.A", "type": "text"}],
                    },
                }
            ],
        }
    ],
}


@pytest.fixture
def meta_post(client: Client, django_capture_on_commit_callbacks: Any) -> Any:
    def post(payload: dict[str, Any], *, secret: str | None = None) -> Any:
        body = json.dumps(payload).encode()
        signature = sign_body(settings.META_APP_SECRET if secret is None else secret, body)
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(
                "/webhooks/meta/",
                data=body,
                content_type="application/json",
                headers={SIGNATURE_HEADER: signature},
            )

    return post


def _handshake(client: Client, **overrides: str) -> Any:
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": settings.META_WEBHOOK_VERIFY_TOKEN,
        "hub.challenge": "1158201444",
        **overrides,
    }
    return client.get("/webhooks/meta/", params)


@pytest.mark.django_db
def test_handshake_returns_challenge(client: Client) -> None:
    response = _handshake(client)

    assert response.status_code == 200
    assert response.content == b"1158201444"
    assert response["Content-Type"].startswith("text/plain")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"hub.verify_token": "errado"},
        {"hub.mode": "unsubscribe"},
        {"hub.challenge": ""},
    ],
)
def test_handshake_refused(client: Client, overrides: dict[str, str]) -> None:
    assert _handshake(client, **overrides).status_code == 403


@pytest.mark.django_db
def test_handshake_refused_when_verify_token_not_configured(client: Client, settings: Any) -> None:
    settings.META_WEBHOOK_VERIFY_TOKEN = ""

    assert _handshake(client, **{"hub.verify_token": ""}).status_code == 403


@pytest.mark.django_db
def test_signed_event_is_routed_by_object(meta_post: Any) -> None:
    response = meta_post(WHATSAPP_PAYLOAD)

    assert response.status_code == 200
    delivery = WebhookDelivery.objects.get()
    assert delivery.provider == "meta"
    assert delivery.signature_valid
    assert delivery.route_key == "whatsapp_business_account"
    # O handler do WhatsApp chega na Fase 2; até lá a entrega fica registrada e ignorada
    assert delivery.status == DeliveryStatus.IGNORED


@pytest.mark.django_db
def test_event_signed_with_wrong_secret_is_rejected(meta_post: Any) -> None:
    response = meta_post(WHATSAPP_PAYLOAD, secret="outro-segredo")

    assert response.status_code == 403
    assert WebhookDelivery.objects.get().status == DeliveryStatus.REJECTED


@pytest.mark.django_db
def test_meta_retry_of_same_body_is_discarded(meta_post: Any) -> None:
    meta_post(WHATSAPP_PAYLOAD)
    response = meta_post(WHATSAPP_PAYLOAD)

    assert response.json()["status"] == "duplicate"
    assert WebhookDelivery.objects.count() == 1


@pytest.fixture
def page_handler() -> Iterator[list[WebhookDelivery]]:
    received: list[WebhookDelivery] = []

    def handle(delivery: WebhookDelivery) -> None:
        received.append(delivery)

    registry.register_handler("meta", "page", handle)
    yield received
    registry._handlers[("meta", "page")].remove(handle)


@pytest.mark.django_db
def test_registered_channel_handler_receives_its_object(
    meta_post: Any, page_handler: list[WebhookDelivery]
) -> None:
    meta_post({"object": "page", "entry": [{"id": "111", "messaging": []}]})
    meta_post(WHATSAPP_PAYLOAD)

    assert [d.route_key for d in page_handler] == ["page"]
    statuses = dict(WebhookDelivery.objects.values_list("route_key", "status"))
    assert statuses == {
        "page": DeliveryStatus.PROCESSED,
        "whatsapp_business_account": DeliveryStatus.IGNORED,
    }
