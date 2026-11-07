"""Handler da rota instagram do provedor de webhook da Meta.

A entrega já chegou assinada e foi gravada pela esteira (ADR 0003). DMs, ecos, reações,
leituras e botões vêm em entry[].messaging[] e passam pelo recebimento comum da
Messenger Platform. Comentários e menções vêm em entry[].changes[].
"""

import logging

from apps.core.models import Channel
from apps.meta_business.messaging import (
    is_messaging_value,
    parse_timestamp,
    process_messaging_event,
)
from apps.webhooks.models import WebhookDelivery
from apps.webhooks.registry import registry

from .inbound import process_comment, process_mention

logger = logging.getLogger(__name__)

ROUTE = "instagram"


def handle_delivery(delivery: WebhookDelivery) -> None:
    payload = delivery.raw_payload if isinstance(delivery.raw_payload, dict) else {}
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        account_id = str(entry.get("id", ""))
        at = parse_timestamp(entry.get("time"))
        for event in entry.get("messaging") or []:
            if isinstance(event, dict):
                process_messaging_event(event, channel=Channel.INSTAGRAM, account_id=account_id)
        for change in entry.get("changes") or []:
            field = change.get("field")
            value = change.get("value") or {}
            if is_messaging_value(value):  # eventos do botão "Teste" do painel
                process_messaging_event(value, channel=Channel.INSTAGRAM, account_id=account_id)
            elif field in ("comments", "live_comments"):
                process_comment(value, account_id=account_id, at=at, field=field)
            elif field == "mentions":
                process_mention(value, at=at)
            else:
                logger.info("Campo %s do Instagram sem tratamento (entrega %s)", field, delivery.pk)


def register() -> None:
    registry.register_handler("meta", ROUTE, handle_delivery)
