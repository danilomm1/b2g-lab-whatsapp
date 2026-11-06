"""Provedor de webhook da Meta: um único endpoint para WhatsApp, Instagram e Página.

Callback no App Dashboard: https://<host>/webhooks/meta/ (ADR 0003). A rota de cada
entrega é o campo "object" do payload (whatsapp_business_account, instagram, page...),
e os apps de canal registram handlers para a sua rota.
"""

import hmac
import logging
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden

from apps.webhooks.registry import WebhookProvider, registry
from apps.webhooks.signatures import verify_hmac_sha256

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Hub-Signature-256"


class MetaProvider(WebhookProvider):
    slug = "meta"

    def verify_signature(self, request: HttpRequest) -> bool:
        """HMAC-SHA256 do corpo bruto com o App Secret, no formato sha256=<hex>."""
        return verify_hmac_sha256(
            settings.META_APP_SECRET, request.body, request.headers.get(SIGNATURE_HEADER, "")
        )

    def handshake(self, request: HttpRequest) -> HttpResponse:
        """Verificação do App Dashboard: devolve hub.challenge se o verify token confere."""
        expected = settings.META_WEBHOOK_VERIFY_TOKEN
        received = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")
        if (
            expected
            and challenge
            and request.GET.get("hub.mode") == "subscribe"
            and hmac.compare_digest(received.encode(), expected.encode())
        ):
            logger.info("Webhook da Meta verificado pelo App Dashboard")
            return HttpResponse(challenge, content_type="text/plain")
        logger.warning("Verificação de webhook da Meta recusada")
        return HttpResponseForbidden("verificação recusada")

    def route_key(self, payload: dict[str, Any] | list[Any]) -> str:
        if isinstance(payload, dict):
            return str(payload.get("object", ""))
        return ""


def register() -> None:
    registry.register_provider(MetaProvider())
