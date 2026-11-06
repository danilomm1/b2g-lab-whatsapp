"""Montagem das mensagens de saída da Cloud API, com os limites validados antes do envio.

Limites das páginas "Interactive reply buttons messages" e "Interactive list messages".
Validar aqui evita gastar uma chamada (e um registro de falha) com um erro previsível.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

MAX_BODY = 4096
MAX_INTERACTIVE_BODY = 1024
MAX_HEADER_FOOTER = 60
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_REPLY_ID = 256
MAX_LIST_ROWS = 10
MAX_LIST_SECTIONS = 10
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72


class InvalidPayload(ValueError):
    """Mensagem que a Cloud API recusaria pelos limites documentados."""


def _check_length(label: str, value: str, limit: int, *, required: bool = True) -> None:
    if required and not value.strip():
        raise InvalidPayload(f"{label} não pode ficar vazio")
    if len(value) > limit:
        raise InvalidPayload(f"{label} passa de {limit} caracteres: {value[:30]!r}...")


@dataclass(frozen=True)
class OutboundPayload:
    """Parte específica do tipo de mensagem; o destinatário é acrescentado no envio."""

    kind: str  # text, interactive, template
    body: str  # texto legível, gravado em Message.body
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_template(self) -> bool:
        return self.kind == "template"


def text(body: str, *, preview_url: bool = False) -> OutboundPayload:
    _check_length("Texto", body, MAX_BODY)
    return OutboundPayload(
        "text", body, {"type": "text", "text": {"body": body, "preview_url": preview_url}}
    )


def _header_footer(header: str, footer: str) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if header:
        _check_length("Cabeçalho", header, MAX_HEADER_FOOTER)
        extra["header"] = {"type": "text", "text": header}
    if footer:
        _check_length("Rodapé", footer, MAX_HEADER_FOOTER)
        extra["footer"] = {"text": footer}
    return extra


def _check_ids(ids: Sequence[str]) -> None:
    for reply_id in ids:
        _check_length("ID de resposta", reply_id, MAX_REPLY_ID)
    if len(set(ids)) != len(ids):
        raise InvalidPayload("IDs de resposta repetidos")


def buttons(
    body: str, options: Sequence[tuple[str, str]], *, header: str = "", footer: str = ""
) -> OutboundPayload:
    """Até 3 botões de resposta; options são pares (id, título)."""
    _check_length("Corpo", body, MAX_INTERACTIVE_BODY)
    if not 1 <= len(options) <= MAX_BUTTONS:
        raise InvalidPayload(f"Use de 1 a {MAX_BUTTONS} botões")
    _check_ids([reply_id for reply_id, _ in options])
    for _, title in options:
        _check_length("Título do botão", title, MAX_BUTTON_TITLE)
    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": reply_id, "title": title}}
                for reply_id, title in options
            ]
        },
        **_header_footer(header, footer),
    }
    return OutboundPayload("interactive", body, {"type": "interactive", "interactive": interactive})


@dataclass(frozen=True)
class ListRow:
    id: str
    title: str
    description: str = ""


@dataclass(frozen=True)
class ListSection:
    title: str
    rows: Sequence[ListRow]


def list_message(
    body: str,
    button: str,
    sections: Sequence[ListSection],
    *,
    header: str = "",
    footer: str = "",
) -> OutboundPayload:
    """Lista com até 10 linhas no total; com mais de uma seção, cada uma precisa de título."""
    _check_length("Corpo", body, MAX_INTERACTIVE_BODY)
    _check_length("Texto do botão da lista", button, MAX_BUTTON_TITLE)
    rows = [row for section in sections for row in section.rows]
    if not sections or len(sections) > MAX_LIST_SECTIONS:
        raise InvalidPayload(f"Use de 1 a {MAX_LIST_SECTIONS} seções")
    if not 1 <= len(rows) <= MAX_LIST_ROWS:
        raise InvalidPayload(f"Use de 1 a {MAX_LIST_ROWS} linhas no total")
    _check_ids([row.id for row in rows])
    for section in sections:
        _check_length("Título da seção", section.title, MAX_ROW_TITLE, required=len(sections) > 1)
        if not section.rows:
            raise InvalidPayload("Seção sem linhas")
    for row in rows:
        _check_length("Título da linha", row.title, MAX_ROW_TITLE)
        _check_length("Descrição da linha", row.description, MAX_ROW_DESCRIPTION, required=False)

    def _row(row: ListRow) -> dict[str, str]:
        data = {"id": row.id, "title": row.title}
        if row.description:
            data["description"] = row.description
        return data

    def _section(section: ListSection) -> dict[str, Any]:
        data: dict[str, Any] = {"rows": [_row(row) for row in section.rows]}
        if section.title:
            data["title"] = section.title
        return data

    interactive = {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button, "sections": [_section(s) for s in sections]},
        **_header_footer(header, footer),
    }
    return OutboundPayload("interactive", body, {"type": "interactive", "interactive": interactive})


def template(
    name: str,
    *,
    language: str = "pt_BR",
    components: list[dict[str, Any]] | None = None,
    preview: str = "",
) -> OutboundPayload:
    """Template aprovado; preview é o texto legível gravado na mensagem (opcional)."""
    _check_length("Nome do template", name, 512)
    data: dict[str, Any] = {"name": name, "language": {"code": language}}
    if components:
        data["components"] = components
    return OutboundPayload(
        "template", preview or f"[template {name}]", {"type": "template", "template": data}
    )


MEDIA_KINDS = ("image", "document", "audio", "video")
MAX_CAPTION = 1024
MAX_FORM_CTA = 20
# Tipos aceitos pela Cloud API e o limite de cada um (página "Media")
MEDIA_LIMITS = {
    "image": (frozenset({"image/jpeg", "image/png", "image/webp"}), 5 * 1024 * 1024),
    "audio": (
        frozenset({"audio/aac", "audio/amr", "audio/mpeg", "audio/mp4", "audio/ogg"}),
        16 * 1024 * 1024,
    ),
    "video": (frozenset({"video/mp4", "video/3gpp"}), 16 * 1024 * 1024),
    "document": (frozenset(), 100 * 1024 * 1024),  # vazio: qualquer tipo de documento
}


def media_kind_for(mime_type: str) -> str:
    """Tipo de mensagem para um arquivo: imagem, áudio e vídeo aceitos; o resto vira documento."""
    for kind in ("image", "audio", "video"):
        if mime_type in MEDIA_LIMITS[kind][0]:
            return kind
    return "document"


def check_media(kind: str, mime_type: str, size: int) -> None:
    accepted, limit = MEDIA_LIMITS[kind]
    if accepted and mime_type not in accepted:
        raise InvalidPayload(f"Tipo {mime_type} não é aceito como {kind}")
    if size > limit:
        raise InvalidPayload(f"Arquivo de {size} bytes passa do limite de {limit} para {kind}")


def media(
    kind: str,
    *,
    media_id: str = "",
    link: str = "",
    caption: str = "",
    filename: str = "",
) -> OutboundPayload:
    """Imagem, documento, áudio ou vídeo, por ID de mídia enviada à Meta ou por link público."""
    if kind not in MEDIA_KINDS:
        raise InvalidPayload(f"Tipo de mídia desconhecido: {kind}")
    if bool(media_id) == bool(link):
        raise InvalidPayload("Informe o ID da mídia ou o link, um dos dois")
    _check_length("Legenda", caption, MAX_CAPTION, required=False)
    if caption and kind == "audio":
        raise InvalidPayload("Áudio não aceita legenda")
    content: dict[str, Any] = {"id": media_id} if media_id else {"link": link}
    if caption:
        content["caption"] = caption
    if filename and kind == "document":
        content["filename"] = filename
    return OutboundPayload(kind, caption or filename or f"[{kind}]", {"type": kind, kind: content})


def form(
    body: str,
    cta: str,
    *,
    flow_id: str,
    token: str,
    screen: str,
    header: str = "",
    footer: str = "",
    mode: str = "published",
) -> OutboundPayload:
    """Mensagem que abre um WhatsApp Flow (formulário nativo); a resposta volta como nfm_reply."""
    _check_length("Corpo", body, MAX_INTERACTIVE_BODY)
    _check_length("Botão do formulário", cta, MAX_FORM_CTA)
    interactive = {
        "type": "flow",
        "body": {"text": body},
        "action": {
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_token": token,
                "flow_id": flow_id,
                "flow_cta": cta,
                "flow_action": "navigate",
                "flow_action_payload": {"screen": screen},
                "mode": mode,
            },
        },
        **_header_footer(header, footer),
    }
    return OutboundPayload("interactive", body, {"type": "interactive", "interactive": interactive})
