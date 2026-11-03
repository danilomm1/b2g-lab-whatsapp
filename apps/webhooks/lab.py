"""Provedor "lab": valida a esteira de webhooks sem depender de nenhuma plataforma externa.

Assina como a Meta (HMAC-SHA256 do corpo, prefixo "sha256="), com LAB_WEBHOOK_SECRET,
no cabeçalho X-Lab-Signature-256. Teste com: python manage.py send_test_webhook
"""

from typing import Any

from django.conf import settings
from django.http import HttpRequest

from apps.core.services import record_event

from .models import WebhookDelivery
from .registry import WebhookProvider, registry
from .signatures import verify_hmac_sha256

SIGNATURE_HEADER = "X-Lab-Signature-256"


class LabProvider(WebhookProvider):
    slug = "lab"

    def verify_signature(self, request: HttpRequest) -> bool:
        return verify_hmac_sha256(
            settings.LAB_WEBHOOK_SECRET, request.body, request.headers.get(SIGNATURE_HEADER, "")
        )

    def route_key(self, payload: dict[str, Any] | list[Any]) -> str:
        if isinstance(payload, dict):
            return str(payload.get("type", "ping"))
        return "ping"

    def dedupe_key(self, payload: dict[str, Any] | list[Any], body: bytes) -> str:
        if isinstance(payload, dict) and payload.get("id"):
            return str(payload["id"])[:128]
        return super().dedupe_key(payload, body)


def handle_ping(delivery: WebhookDelivery) -> None:
    """Registra o ping como evento na linha do tempo."""
    payload = delivery.raw_payload if isinstance(delivery.raw_payload, dict) else {}
    record_event(
        "lab.webhook_ping",
        external_id=f"lab-{delivery.dedupe_key}",
        summary=str(payload.get("message", "ping")),
        data={"delivery_id": delivery.pk, "payload": payload},
    )


def register() -> None:
    registry.register_provider(LabProvider())
    registry.register_handler("lab", "ping", handle_ping)
