"""Tarefas Huey de webhooks."""

from huey.contrib.djhuey import db_task

from .services import process_webhook_delivery


@db_task(retries=3, retry_delay=30)
def process_delivery(delivery_id: int) -> None:
    """Processa uma entrega fora da requisição, com até 3 novas tentativas."""
    process_webhook_delivery(delivery_id)
