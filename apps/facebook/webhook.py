"""Handler da rota page do provedor de webhook da Meta.

A entrega já chegou assinada e foi gravada pela esteira (ADR 0003). Mensagens do
Messenger, ecos, reações, entregas e leituras vêm em entry[].messaging[] e passam pelo
recebimento comum da Messenger Platform. O campo feed (posts e comentários) vem em
entry[].changes[].
"""

import logging

from apps.core.models import Channel
from apps.meta_business.messaging import is_messaging_value, process_messaging_event
from apps.webhooks.models import WebhookDelivery
from apps.webhooks.registry import registry

from .inbound import process_feed_change

logger = logging.getLogger(__name__)

ROUTE = "page"


def handle_delivery(delivery: WebhookDelivery) -> None:
    payload = delivery.raw_payload if isinstance(delivery.raw_payload, dict) else {}
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("id", ""))
        for event in entry.get("messaging") or []:
            if isinstance(event, dict):
                process_messaging_event(event, channel=Channel.FACEBOOK, account_id=page_id)
        for change in entry.get("changes") or []:
            field = change.get("field")
            value = change.get("value") or {}
            if is_messaging_value(value):  # eventos do botão "Teste" do painel
                process_messaging_event(value, channel=Channel.FACEBOOK, account_id=page_id)
            elif field == "feed":
                process_feed_change(value, page_id=page_id)
            else:
                logger.info("Campo %s da Página sem tratamento (entrega %s)", field, delivery.pk)


def register() -> None:
    registry.register_handler("meta", ROUTE, handle_delivery)
