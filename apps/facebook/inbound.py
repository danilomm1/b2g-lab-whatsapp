"""Campo feed da Página: comentários e posts, vindos de entry[].changes[].

O from.id de um comentário no feed não é garantidamente o PSID do Messenger. Por isso o
comentário só se liga a um contato que já tenha esse ID como identidade; o vínculo com a
conversa vem quando a pessoa responde à resposta privada (docs/integrations/facebook.md).
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.models import Channel, Event
from apps.core.services import record_event
from apps.meta_business.messaging import find_identity, parse_timestamp

logger = logging.getLogger(__name__)

COMMENT_EVENTS = {
    "add": "facebook.comment_received",
    "edited": "facebook.comment_edited",
    "remove": "facebook.comment_removed",
    "hide": "facebook.comment_hidden",
    "unhide": "facebook.comment_unhidden",
}
POST_ITEMS = frozenset({"status", "post", "photo", "video", "share", "link"})


def process_feed_change(value: dict[str, Any], *, page_id: str) -> Event | None:
    """Comentário vira evento; post da própria Página vira facebook.post_published."""
    item = str(value.get("item") or "")
    verb = str(value.get("verb") or "")
    author = value.get("from") if isinstance(value.get("from"), dict) else {}
    author_id = str(author.get("id") or "")
    at = parse_timestamp(value.get("created_time"))
    own_page = bool(author_id) and author_id == page_id

    if item == "comment":
        comment_id = str(value.get("comment_id") or "")
        if not comment_id:
            return None
        identity = find_identity(Channel.FACEBOOK, page_id, author_id) if author_id else None
        external_id = (
            comment_id if verb == "add" else f"{comment_id}:{verb}:{value.get('created_time', '')}"
        )
        name = str(author.get("name") or "")
        text = str(value.get("message") or "")
        event, _ = record_event(
            COMMENT_EVENTS.get(verb, f"facebook.comment_{verb or 'event'}"),
            contact=identity.contact if identity and not own_page else None,
            channel=Channel.FACEBOOK,
            external_id=external_id,
            occurred_at=at,
            summary=f"{name}: {text}" if name else text,
            data={
                "comment_id": comment_id,
                "post_id": value.get("post_id"),
                "parent_id": value.get("parent_id"),
                "text": text,
                "from": author,
                "own_page": own_page,
                "verb": verb,
            },
        )
        return event

    if item in POST_ITEMS and verb == "add" and own_page:
        post_id = str(value.get("post_id") or "")
        event, _ = record_event(
            "facebook.post_published",
            channel=Channel.FACEBOOK,
            external_id=post_id,
            occurred_at=at,
            summary=str(value.get("message") or item),
            data={"post_id": post_id, "item": item, "link": value.get("link")},
        )
        return event

    logger.info("Feed da Página sem tratamento: item=%s verb=%s", item, verb)
    return None
