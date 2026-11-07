"""Comentários e menções da conta do Instagram, vindos de entry[].changes[].

O comentário traz o IGSID e o @ de quem comentou: o mesmo IGSID das DMs, então o
comentário cai no mesmo contato da conversa (base da jornada "comentário vira conversa").
Comentários por webhook exigem acesso avançado; sem ele, só chegam os do botão "Teste"
(docs/integrations/instagram.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.core.models import Channel, Contact, Event
from apps.core.services import record_event
from apps.meta_business.messaging import resolve_user

COMMENT_SOURCE = "instagram_comment"


def _fill_instagram_handle(contact: Contact, username: str) -> None:
    if username and not contact.instagram_handle:
        contact.instagram_handle = username
        contact.save()


def process_comment(
    value: dict[str, Any], *, account_id: str, at: datetime, field: str = "comments"
) -> Event | None:
    """Comentário em post, Reels, story ou Live: evento na linha do tempo do contato.

    Comentário da própria conta (resposta da @brave2grow) fica sem contato.
    """
    comment_id = str(value.get("id") or "")
    if not comment_id:
        return None
    author = value.get("from") if isinstance(value.get("from"), dict) else {}
    user_id = str(author.get("id") or author.get("self_ig_scoped_id") or "")
    username = str(author.get("username") or "")
    contact = None
    if user_id and user_id != account_id:
        identity = resolve_user(
            Channel.INSTAGRAM,
            account_id,
            user_id,
            seen_at=at,
            source=COMMENT_SOURCE,
            handle=username,
        )
        contact = identity.contact
        _fill_instagram_handle(contact, username)
    media = value.get("media") if isinstance(value.get("media"), dict) else {}
    text = str(value.get("text") or "")
    event, _ = record_event(
        "instagram.comment_received",
        contact=contact,
        channel=Channel.INSTAGRAM,
        external_id=comment_id,
        occurred_at=at,
        summary=f"@{username}: {text}" if username else text,
        data={
            "comment_id": comment_id,
            "text": text,
            "parent_id": value.get("parent_id"),
            "media_id": media.get("id"),
            "media_product_type": media.get("media_product_type"),
            "from": author,
            "own_account": user_id == account_id,
            "field": field,
        },
    )
    return event


def process_mention(value: dict[str, Any], *, at: datetime) -> Event | None:
    """Menção à @brave2grow em legenda ou comentário de outra conta."""
    external_id = str(value.get("comment_id") or value.get("media_id") or "")
    if not external_id:
        return None
    event, _ = record_event(
        "instagram.mention_received",
        channel=Channel.INSTAGRAM,
        external_id=external_id,
        occurred_at=at,
        summary="Menção em comentário" if value.get("comment_id") else "Menção em legenda",
        data=value,
    )
    return event
