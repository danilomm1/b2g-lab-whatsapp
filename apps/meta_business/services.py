"""Inspeção do token do System User e dos ativos que ele alcança."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.credentials.models import IntegrationCredential, Platform
from apps.credentials.services import get_credential, save_token

from .client import GraphClient, app_access_token

SYSTEM_USER_LABEL = "system_user"
# Token da Página, gravado pelo facebook_check; serve também ao Instagram conectado a ela
PAGE_TOKEN_LABEL = "page"

# Permissões que dão acesso a cada ativo configurado no .env
ASSET_SCOPES: dict[str, tuple[str, ...]] = {
    "FACEBOOK_PAGE_ID": (
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_metadata",
        "pages_messaging",
        "pages_manage_posts",
    ),
    "INSTAGRAM_BUSINESS_ACCOUNT_ID": (
        "instagram_basic",
        "instagram_manage_comments",
        "instagram_manage_messages",
        "instagram_content_publish",
    ),
    "WHATSAPP_BUSINESS_ACCOUNT_ID": (
        "whatsapp_business_management",
        "whatsapp_business_messaging",
    ),
}


def _timestamp(value: Any) -> datetime | None:
    """Converte unixtime da Meta; 0 ou ausente significa "não expira"."""
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


@dataclass(frozen=True)
class TokenInfo:
    """Resposta do debug_token, já interpretada."""

    is_valid: bool
    app_id: str
    application: str
    token_type: str
    user_id: str
    scopes: tuple[str, ...]
    granular_scopes: tuple[dict[str, Any], ...]
    expires_at: datetime | None
    data_access_expires_at: datetime | None
    error: dict[str, Any]

    @classmethod
    def from_debug_token(cls, data: dict[str, Any]) -> TokenInfo:
        return cls(
            is_valid=bool(data.get("is_valid")),
            app_id=str(data.get("app_id", "")),
            application=str(data.get("application", "")),
            token_type=str(data.get("type", "")),
            user_id=str(data.get("user_id", "")),
            scopes=tuple(data.get("scopes", [])),
            granular_scopes=tuple(data.get("granular_scopes", [])),
            expires_at=_timestamp(data.get("expires_at")),
            data_access_expires_at=_timestamp(data.get("data_access_expires_at")),
            error=data.get("error", {}),
        )

    @property
    def matches_configured_app(self) -> bool:
        return self.app_id == str(settings.META_APP_ID)

    def can_reach(self, scope: str, target_id: str) -> bool:
        """Indica se a permissão vale para o ativo.

        Sem target_ids, a permissão vale para todos os ativos (doc do debug_token).
        """
        if scope not in self.scopes:
            return False
        for item in self.granular_scopes:
            if item.get("scope") == scope:
                targets = item.get("target_ids")
                return not targets or target_id in {str(t) for t in targets}
        return True


def inspect_token(token: str, *, client: GraphClient | None = None) -> TokenInfo:
    """Consulta o /debug_token com o token de app (somente leitura)."""
    own_client = client is None
    client = client or GraphClient(access_token=app_access_token())
    try:
        response = client.get("debug_token", {"input_token": token})
    finally:
        if own_client:
            client.close()
    return TokenInfo.from_debug_token(response.get("data", {}))


@dataclass(frozen=True)
class AssetCheck:
    setting: str
    asset_id: str
    reachable_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]
    # Permissões do ativo que o token tem, valendo ou não para este ativo
    granted_scopes: tuple[str, ...] = ()

    @property
    def is_configured(self) -> bool:
        return bool(self.asset_id)


def check_assets(info: TokenInfo) -> list[AssetCheck]:
    """Para cada ativo do .env, lista as permissões do token que o alcançam."""
    checks = []
    for setting, scopes in ASSET_SCOPES.items():
        asset_id = str(getattr(settings, setting, "") or "")
        reachable = tuple(s for s in scopes if asset_id and info.can_reach(s, asset_id))
        missing = tuple(s for s in scopes if s not in reachable)
        granted = tuple(s for s in scopes if s in info.scopes)
        checks.append(AssetCheck(setting, asset_id, reachable, missing, granted))
    return checks


def sync_system_user_credential(token: str, info: TokenInfo) -> IntegrationCredential:
    """Grava o token (criptografado) e o que o debug_token informou, para o painel."""
    credential = save_token(
        Platform.META,
        label=SYSTEM_USER_LABEL,
        access_token=token,
        expires_at=info.expires_at,
        scopes=list(info.scopes),
        account_id=info.user_id,
        token_type=info.token_type.lower() or "system_user",
    )
    credential.is_active = info.is_valid
    credential.last_error = info.error.get("message", "") if info.error else ""
    credential.metadata = {
        "app_id": info.app_id,
        "application": info.application,
        "granular_scopes": list(info.granular_scopes),
        "data_access_expires_at": (
            info.data_access_expires_at.isoformat() if info.data_access_expires_at else None
        ),
        "checked_at": timezone.now().isoformat(),
    }
    credential.save()
    return credential


def app_subscription(response: dict[str, Any]) -> list[str] | None:
    """Campos de webhook que o app do laboratório assina, numa resposta de subscribed_apps.

    None se o app não está inscrito. A Página identifica o app por "id"; o Instagram, por
    "app_id".
    """
    for item in response.get("data") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or item.get("app_id") or "") == str(settings.META_APP_ID):
            return [str(field) for field in item.get("subscribed_fields") or []]
    return None


def page_access_token() -> str:
    """Token da Página gravado pelo facebook_check (CredentialNotFound se ainda não rodou)."""
    return get_credential(Platform.FACEBOOK, PAGE_TOKEN_LABEL).access_token
