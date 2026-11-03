"""Tarefas periódicas de credenciais."""

import logging

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from .services import refresh_expiring

logger = logging.getLogger(__name__)


# 06:00 UTC, ou 03:00 em São Paulo
@db_periodic_task(crontab(hour="6", minute="0"))
def refresh_expiring_credentials() -> None:
    """Renova diariamente os tokens que expiram nos próximos 7 dias."""
    report = refresh_expiring()
    logger.info(
        "Renovação de credenciais: %d renovadas, %d com falha, %d sem renovação automática",
        len(report.refreshed),
        len(report.failed),
        len(report.without_refresher),
    )
