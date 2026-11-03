"""Testes da esteira de webhooks: assinatura, bruto, deduplicação, fila e roteamento."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from django.core.management import call_command

from apps.core.models import Event
from apps.webhooks.lab import SIGNATURE_HEADER, LabProvider
from apps.webhooks.models import DeliveryStatus, WebhookDelivery
from apps.webhooks.registry import registry
from apps.webhooks.signatures import sign_body, verify_hmac_sha256

SECRET = "segredo"
BODY = b'{"object":"page"}'


def test_signature_valid() -> None:
    assert verify_hmac_sha256(SECRET, BODY, sign_body(SECRET, BODY))


@pytest.mark.parametrize(
    ("secret", "header"),
    [
        ("outro", sign_body(SECRET, BODY)),  # segredo errado
        (SECRET, sign_body(SECRET, BODY)[len("sha256=") :]),  # sem prefixo
        ("", sign_body("", BODY)),  # segredo vazio nunca valida
        (SECRET, ""),
        (SECRET, "sha256=ção"),  # cabeçalho com caracteres não ASCII
    ],
)
def test_signature_invalid(secret: str, header: str) -> None:
    assert not verify_hmac_sha256(secret, BODY, header)


@pytest.mark.django_db
def test_valid_webhook_is_stored_processed_and_recorded(lab_post: Any) -> None:
    response = lab_post({"id": "evt-1", "type": "ping", "message": "olá"})

    assert response.status_code == 200
    assert response.json()["status"] == "received"
    delivery = WebhookDelivery.objects.get()
    assert delivery.signature_valid
    assert delivery.status == DeliveryStatus.PROCESSED
    assert delivery.route_key == "ping"
    assert delivery.dedupe_key == "evt-1"
    assert delivery.raw_payload["message"] == "olá"
    assert json.loads(delivery.raw_body)["id"] == "evt-1"
    event = Event.objects.get(event_type="lab.webhook_ping")
    assert event.summary == "olá"


@pytest.mark.django_db
def test_invalid_signature_is_rejected_but_kept_for_debugging(lab_post: Any) -> None:
    response = lab_post({"id": "evt-1"}, secret="segredo-errado")

    assert response.status_code == 403
    delivery = WebhookDelivery.objects.get()
    assert delivery.status == DeliveryStatus.REJECTED
    assert not delivery.signature_valid
    assert not Event.objects.exists()


@pytest.mark.django_db
def test_duplicate_delivery_is_discarded(lab_post: Any) -> None:
    lab_post({"id": "evt-1"})
    response = lab_post({"id": "evt-1"})

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
    assert WebhookDelivery.objects.count() == 1
    assert Event.objects.count() == 1


@pytest.mark.django_db
def test_forged_delivery_does_not_block_the_real_one(lab_post: Any) -> None:
    lab_post({"id": "evt-1"}, secret="segredo-errado")
    response = lab_post({"id": "evt-1"})

    assert response.json()["status"] == "received"
    assert Event.objects.count() == 1


@pytest.mark.django_db
def test_route_without_handler_is_ignored(lab_post: Any) -> None:
    lab_post({"id": "evt-1", "type": "sem_handler"})

    delivery = WebhookDelivery.objects.get()
    assert delivery.status == DeliveryStatus.IGNORED
    assert "sem_handler" in delivery.error


@pytest.fixture
def failing_handler() -> Iterator[None]:
    def boom(delivery: WebhookDelivery) -> None:
        raise RuntimeError("falha simulada")

    registry.register_handler("lab", "boom", boom)
    yield
    registry._handlers[("lab", "boom")].remove(boom)


@pytest.mark.django_db
@pytest.mark.usefixtures("failing_handler")
def test_handler_failure_is_recorded(lab_post: Any) -> None:
    response = lab_post({"id": "evt-1", "type": "boom"})

    assert response.status_code == 200  # a falha acontece na fila, não na requisição
    delivery = WebhookDelivery.objects.get()
    assert delivery.status == DeliveryStatus.FAILED
    assert "falha simulada" in delivery.error
    assert delivery.attempts >= 1


@pytest.mark.django_db
def test_sensitive_headers_are_not_stored(lab_post: Any) -> None:
    lab_post({"id": "evt-1"}, Authorization="Bearer segredo", Cookie="sessionid=abc")

    headers = {key.lower() for key in WebhookDelivery.objects.get().headers}
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert SIGNATURE_HEADER.lower() in headers


@pytest.mark.django_db
def test_unknown_provider_returns_404(client: Any) -> None:
    assert client.post("/webhooks/desconhecido/", data={}).status_code == 404


@pytest.mark.django_db
def test_get_without_handshake_is_not_allowed(client: Any) -> None:
    assert client.get("/webhooks/lab/").status_code == 405


def test_form_encoded_payload_is_parsed() -> None:
    payload = LabProvider().parse_payload(
        b"From=whatsapp%3A%2B5511987654321&Body=Oi", "application/x-www-form-urlencoded"
    )

    assert payload == {"From": "whatsapp:+5511987654321", "Body": "Oi"}


@respx.mock
def test_send_test_webhook_command_signs_the_body(settings: Any) -> None:
    route = respx.post("http://127.0.0.1:8602/webhooks/lab/").mock(
        return_value=httpx.Response(200, json={"status": "received"})
    )

    call_command("send_test_webhook", stdout=None)

    request = route.calls.last.request
    assert verify_hmac_sha256(
        settings.LAB_WEBHOOK_SECRET, request.content, request.headers[SIGNATURE_HEADER]
    )
    assert json.loads(request.content)["type"] == "ping"
