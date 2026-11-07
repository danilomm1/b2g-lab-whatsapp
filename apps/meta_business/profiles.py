"""Nome e @ de quem escreve no Instagram ou no Messenger (User Profile API).

O webhook não traz o nome. A consulta GET /<IGSID ou PSID> usa o token da Página (o
token do usuário do sistema é recusado nos dois canais) e o recurso Business Asset User
Profile Access. Testado em 07/11/2026: o Messenger devolve nome e sobrenome; o Instagram,
o @ (e o nome, quando a pessoa preencheu).
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.models import Channel, ChannelIdentity
from apps.credentials.services import CredentialNotFound

from .client import GraphAPIError, GraphClient
from .services import page_access_token

logger = logging.getLogger(__name__)

# Só o necessário para identificar a pessoa (CLAUDE.md, seção 13: minimização)
PROFILE_FIELDS = {
    Channel.INSTAGRAM: "name,username",
    Channel.FACEBOOK: "first_name,last_name,name",
}


def apply_profile(identity: ChannelIdentity, profile: dict[str, Any]) -> None:
    """Grava o @ na identidade e completa nome e @ vazios do contato, sem sobrescrever."""
    contact = identity.contact
    name = str(profile.get("name") or "").strip()
    if not name:
        parts = (profile.get("first_name"), profile.get("last_name"))
        name = " ".join(str(part) for part in parts if part)
    username = str(profile.get("username") or "")
    if username and identity.handle != username:
        identity.handle = username
        identity.save(update_fields=["handle"])
    changed = False
    if name and not contact.name:
        contact.name = name
        changed = True
    if identity.channel == Channel.INSTAGRAM and username and not contact.instagram_handle:
        contact.instagram_handle = username
        changed = True
    if changed:
        contact.save()


def fetch_profile(identity_id: int, *, client: GraphClient | None = None) -> bool:
    """Busca o perfil e completa o contato. Retorna se a Meta devolveu o perfil.

    Sem token da Página (facebook_check ainda não rodou) ou com erro da Graph API, só
    registra no log: o perfil é um complemento e não pode travar o recebimento.
    """
    identity = ChannelIdentity.objects.select_related("contact").filter(pk=identity_id).first()
    if identity is None or identity.channel not in PROFILE_FIELDS:
        return False
    try:
        token = page_access_token()
    except CredentialNotFound:
        logger.info("Perfil de %s não buscado: rode o facebook_check", identity)
        return False
    own_client = client is None
    client = client or GraphClient(access_token=token)
    try:
        profile = client.get(identity.external_id, {"fields": PROFILE_FIELDS[identity.channel]})
    except GraphAPIError as exc:
        logger.warning("Perfil de %s indisponível: %s (code=%s)", identity, exc, exc.code)
        return False
    finally:
        if own_client:
            client.close()
    apply_profile(identity, profile)
    return True
