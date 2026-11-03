"""Processamento das entregas de webhook (executado pela fila Huey)."""

import logging
import traceback

from django.db import transaction
from django.utils import timezone

from .models import DeliveryStatus, WebhookDelivery
from .registry import registry

logger = logging.getLogger(__name__)

_FINAL_STATUSES = {DeliveryStatus.PROCESSED, DeliveryStatus.IGNORED, DeliveryStatus.REJECTED}


def process_webhook_delivery(delivery_id: int) -> WebhookDelivery:
    """Executa os handlers da rota da entrega. Idempotente: entregas finalizadas são puladas.

    Em caso de erro, marca a entrega como falha e relança a exceção para o retry do Huey.
    """
    delivery = WebhookDelivery.objects.get(pk=delivery_id)
    if delivery.status in _FINAL_STATUSES:
        return delivery

    delivery.attempts += 1
    handlers = registry.get_handlers(delivery.provider, delivery.route_key)
    if not handlers:
        delivery.status = DeliveryStatus.IGNORED
        delivery.error = f"Nenhum handler para {delivery.provider}/{delivery.route_key}"
        delivery.processed_at = timezone.now()
        delivery.save(update_fields=["status", "error", "attempts", "processed_at"])
        logger.info("Webhook %s ignorado: %s", delivery.pk, delivery.error)
        return delivery

    try:
        with transaction.atomic():
            for handler in handlers:
                handler(delivery)
    except Exception:
        delivery.status = DeliveryStatus.FAILED
        delivery.error = traceback.format_exc()
        delivery.save(update_fields=["status", "error", "attempts"])
        logger.exception("Falha ao processar o webhook %s", delivery.pk)
        raise

    delivery.status = DeliveryStatus.PROCESSED
    delivery.error = ""
    delivery.processed_at = timezone.now()
    delivery.save(update_fields=["status", "error", "attempts", "processed_at"])
    return delivery
