"""Leitura, gravação e renovação de credenciais."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone

from .models import EXPIRING_SOON, IntegrationCredential

logger = logging.getLogger(__name__)

# Função que renova a credencial no lugar (novo token, nova validade); o serviço grava.
Refresher = Callable[[IntegrationCredential], None]

_refreshers: dict[str, Refresher] = {}


class CredentialNotFound(LookupError):
    """Não há credencial ativa para a plataforma e o rótulo pedidos."""


def get_credential(platform: str, label: str = "default") -> IntegrationCredential:
    """Devolve a credencial ativa ou levanta CredentialNotFound."""
    try:
        return IntegrationCredential.objects.get(platform=platform, label=label, is_active=True)
    except IntegrationCredential.DoesNotExist as exc:
        raise CredentialNotFound(f"Sem credencial ativa para {platform}/{label}") from exc


def save_token(
    platform: str,
    *,
    access_token: str,
    label: str = "default",
    refresh_token: str | None = None,
    expires_in: int | None = None,
    expires_at: datetime | None = None,
    scopes: list[str] | None = None,
    account_id: str | None = None,
    token_type: str | None = None,
) -> IntegrationCredential:
    """Cria ou atualiza a credencial com um novo token. expires_in é em segundos, como no OAuth."""
    credential, _ = IntegrationCredential.objects.get_or_create(platform=platform, label=label)
    credential.access_token = access_token
    if refresh_token is not None:
        credential.refresh_token = refresh_token
    if expires_in is not None:
        expires_at = timezone.now() + timedelta(seconds=expires_in)
    credential.expires_at = expires_at
    if scopes is not None:
        credential.scopes = scopes
    if account_id is not None:
        credential.account_id = account_id
    if token_type is not None:
        credential.token_type = token_type
    credential.is_active = True
    credential.last_error = ""
    credential.save()
    return credential


def register_refresher(platform: str) -> Callable[[Refresher], Refresher]:
    """Registra a função de renovação de uma plataforma (usada pelos apps de canal)."""

    def decorator(func: Refresher) -> Refresher:
        _refreshers[platform] = func
        return func

    return decorator


@dataclass
class RefreshReport:
    refreshed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    without_refresher: list[str] = field(default_factory=list)


def refresh_expiring(within: timedelta = EXPIRING_SOON) -> RefreshReport:
    """Renova as credenciais ativas que expiram dentro do prazo e registra o resultado."""
    report = RefreshReport()
    limit = timezone.now() + within
    expiring = IntegrationCredential.objects.filter(
        is_active=True, expires_at__isnull=False, expires_at__lte=limit
    )
    for credential in expiring:
        name = str(credential)
        refresher = _refreshers.get(credential.platform)
        if refresher is None:
            report.without_refresher.append(name)
            logger.warning(
                "Credencial %s expira em %s e não tem renovação automática",
                name,
                credential.expires_at,
            )
            continue
        try:
            refresher(credential)
        except Exception as exc:
            credential.last_error = repr(exc)
            credential.save(update_fields=["last_error", "updated_at"])
            report.failed.append(name)
            logger.exception("Falha ao renovar a credencial %s", name)
            continue
        credential.last_refreshed_at = timezone.now()
        credential.last_error = ""
        credential.save()
        report.refreshed.append(name)
    return report
