"""Endpoint único de entrada de webhooks."""

import logging

from django.db import IntegrityError, transaction
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import DeliveryStatus, WebhookDelivery
from .registry import registry
from .tasks import process_delivery

logger = logging.getLogger(__name__)

# Cabeçalhos que não guardamos junto com o payload bruto
_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization"}


def _safe_headers(request: HttpRequest) -> dict[str, str]:
    return {k: v for k, v in request.headers.items() if k.lower() not in _SENSITIVE_HEADERS}


@csrf_exempt
@require_http_methods(["GET", "POST"])
def receive(request: HttpRequest, provider: str) -> HttpResponse:
    """Valida a assinatura, guarda o bruto e responde na hora; o processamento vai para a fila."""
    webhook_provider = registry.get_provider(provider)
    if webhook_provider is None:
        raise Http404("Provedor de webhook desconhecido")

    if request.method == "GET":
        response = webhook_provider.handshake(request)
        return response if response is not None else HttpResponseNotAllowed(["POST"])

    body = request.body
    payload = webhook_provider.parse_payload(body, request.content_type or "")
    delivery = WebhookDelivery(
        provider=provider,
        headers=_safe_headers(request),
        raw_body=body.decode("utf-8", "replace"),
        raw_payload=payload,
        signature_valid=webhook_provider.verify_signature(request),
    )

    if not delivery.signature_valid:
        delivery.status = DeliveryStatus.REJECTED
        delivery.save()
        logger.warning(
            "Webhook %s rejeitado: assinatura inválida (entrega %s)", provider, delivery.pk
        )
        return HttpResponseForbidden("assinatura inválida")

    delivery.dedupe_key = webhook_provider.dedupe_key(payload, body)
    delivery.route_key = webhook_provider.route_key(payload)
    try:
        with transaction.atomic():
            delivery.save()
    except IntegrityError:
        logger.info("Webhook %s duplicado descartado (chave %s)", provider, delivery.dedupe_key)
        return JsonResponse({"status": "duplicate"})

    transaction.on_commit(lambda: process_delivery(delivery.pk))
    return JsonResponse({"status": "received", "id": delivery.pk})
