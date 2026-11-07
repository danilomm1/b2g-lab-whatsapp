"""Token da Página e inscrição do app nos webhooks da Página.

Envio no Messenger, resposta privada, publicação e moderação exigem o token da Página,
não o do usuário do sistema. Ele sai de GET /<PAGE_ID>?fields=access_token chamado com o
token do usuário do sistema; derivado de um token que não expira, também não expira.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.credentials.models import IntegrationCredential, Platform
from apps.credentials.services import get_credential, save_token
from apps.meta_business.client import GraphClient
from apps.meta_business.services import TokenInfo, app_subscription

PAGE_TOKEN_LABEL = "page"

# Campos assinados no painel (Messenger > Configurações da API) e na inscrição da Página
PAGE_WEBHOOK_FIELDS = (
    "feed",
    "messages",
    "messaging_postbacks",
    "message_echoes",
    "message_deliveries",
    "message_reads",
    "message_reactions",
    "message_edits",
    "messaging_referrals",
)

# Tarefas do usuário do sistema na Página usadas pelo laboratório
REQUIRED_TASKS = ("MESSAGING", "MODERATE", "CREATE_CONTENT")


@dataclass(frozen=True)
class PageInfo:
    page_id: str
    name: str
    tasks: tuple[str, ...]
    access_token: str
    instagram_account_id: str

    @property
    def missing_tasks(self) -> tuple[str, ...]:
        return tuple(task for task in REQUIRED_TASKS if task not in self.tasks)


def _page_tasks(client: GraphClient, page_id: str) -> tuple[str, ...]:
    """Tarefas do usuário do sistema na Página. O nó da Página não tem o campo tasks; ele
    só aparece em me/accounts, que lista as Páginas atribuídas ao usuário do sistema."""
    response = client.get("me/accounts", {"fields": "id,tasks", "limit": 100})
    for item in response.get("data") or []:
        if isinstance(item, dict) and str(item.get("id")) == page_id:
            return tuple(str(task) for task in item.get("tasks") or [])
    return ()


def fetch_page(client: GraphClient, page_id: str | None = None) -> PageInfo:
    """Lê a Página com o token do usuário do sistema, incluindo o token da Página."""
    page_id = page_id or settings.FACEBOOK_PAGE_ID
    data = client.get(page_id, {"fields": "id,name,access_token,instagram_business_account"})
    instagram = data.get("instagram_business_account")
    page_id = str(data.get("id") or page_id)
    return PageInfo(
        page_id=page_id,
        name=str(data.get("name") or ""),
        tasks=_page_tasks(client, page_id),
        access_token=str(data.get("access_token") or ""),
        instagram_account_id=str(instagram.get("id") or "") if isinstance(instagram, dict) else "",
    )


def save_page_token(page: PageInfo, info: TokenInfo | None = None) -> IntegrationCredential:
    """Grava o token da Página criptografado, com a validade informada pelo debug_token."""
    credential = save_token(
        Platform.FACEBOOK,
        label=PAGE_TOKEN_LABEL,
        access_token=page.access_token,
        account_id=page.page_id,
        token_type="page",
        expires_at=info.expires_at if info else None,
        scopes=list(info.scopes) if info else None,
    )
    credential.metadata = {"page_name": page.name, "tasks": list(page.tasks)}
    if info is not None:
        credential.is_active = info.is_valid
    credential.save()
    return credential


def page_access_token() -> str:
    """Token da Página gravado pelo facebook_check (CredentialNotFound se ainda não rodou)."""
    return get_credential(Platform.FACEBOOK, PAGE_TOKEN_LABEL).access_token


def page_subscription(client: GraphClient, page_id: str) -> list[str] | None:
    """Campos que o app assina na Página, ou None se não está inscrito. Usa o token da Página."""
    return app_subscription(client.get(f"{page_id}/subscribed_apps"))


def subscribe_page(client: GraphClient, page_id: str) -> dict[str, Any]:
    """Inscreve o app na Página com os campos do laboratório. Usa o token da Página."""
    return client.request(
        "POST",
        f"{page_id}/subscribed_apps",
        data={"subscribed_fields": ",".join(PAGE_WEBHOOK_FIELDS)},
    )
