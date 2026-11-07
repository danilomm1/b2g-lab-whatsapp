"""Leituras de conferência da conta do Instagram e inscrição do app nos webhooks dela.

Login unificado (ADR 0008): as chamadas vão para graph.facebook.com com o token do
usuário do sistema, que tem as permissões instagram_*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.meta_business.client import GraphAPIError, GraphClient
from apps.meta_business.services import app_subscription

INSTAGRAM_WEBHOOK_FIELDS = (
    "comments",
    "mentions",
    "messages",
    "messaging_postbacks",
    "message_reactions",
    "messaging_seen",
    "messaging_referral",
    "message_edit",
)


@dataclass(frozen=True)
class MessagingAccess:
    ok: bool
    error: str = ""


def fetch_account(client: GraphClient, account_id: str) -> dict[str, Any]:
    """Perfil público da conta: @, nome, seguidores e número de publicações."""
    return client.get(account_id, {"fields": "id,username,name,followers_count,media_count"})


def check_messaging_access(client: GraphClient, account_id: str) -> MessagingAccess:
    """Testa a leitura de conversas do Direct (erro 200 indica acesso às mensagens desligado)."""
    try:
        client.get(f"{account_id}/conversations", {"platform": "instagram", "limit": 1})
    except GraphAPIError as exc:
        return MessagingAccess(False, f"{exc} (code={exc.code})")
    return MessagingAccess(True)


def publishing_limit(client: GraphClient, account_id: str) -> dict[str, Any]:
    """Uso da cota de publicação nas últimas 24h e o limite configurado."""
    response = client.get(
        f"{account_id}/content_publishing_limit", {"fields": "config,quota_usage"}
    )
    data = response.get("data") or [{}]
    return data[0] if isinstance(data[0], dict) else {}


def account_subscription(client: GraphClient, account_id: str) -> list[str] | None:
    """Campos que o app assina na conta, ou None se não está inscrito."""
    return app_subscription(client.get(f"{account_id}/subscribed_apps"))


def subscribe_account(client: GraphClient, account_id: str) -> dict[str, Any]:
    """Inscreve o app na conta com os campos do laboratório."""
    return client.request(
        "POST",
        f"{account_id}/subscribed_apps",
        data={"subscribed_fields": ",".join(INSTAGRAM_WEBHOOK_FIELDS)},
    )
