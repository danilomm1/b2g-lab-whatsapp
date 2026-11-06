"""Tarefas Huey do WhatsApp."""

from typing import Any

from huey.contrib.djhuey import db_task

from .services import deliver_outbox


@db_task()  # sem novas tentativas: repetir um envio pode duplicar mensagens
def send_outbox(
    conversation_id: int, items: list[dict[str, Any]], reply_to_id: int | None = None
) -> None:
    """Envia, em ordem, as mensagens decididas pelo motor de fluxo."""
    deliver_outbox(conversation_id, items, reply_to_id=reply_to_id)
