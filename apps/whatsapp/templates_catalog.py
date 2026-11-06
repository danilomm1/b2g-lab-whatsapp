"""Catálogo versionado dos templates do WhatsApp (CLAUDE.md, seção 12).

Cada TemplateSpec descreve categoria, idioma, texto com variáveis posicionais ({{1}},
{{2}}...) e botões de resposta rápida. O status de aprovação vem da Meta e fica em
MessageTemplate (sync e webhook message_template_status_update).

Templates são obrigatórios fora da janela de 24h. A categoria define o preço; a Meta
pode reclassificar um template enviado como utilidade se julgar que é marketing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .payloads import OutboundPayload, template

NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,512}$")
_VARIABLE = re.compile(r"\{\{(\d+)\}\}")


class TemplateError(ValueError):
    """Template inexistente no catálogo ou chamado com variáveis erradas."""


@dataclass(frozen=True)
class QuickReply:
    text: str  # rótulo do botão, até 25 caracteres
    payload: str  # volta no webhook como button.payload (reply_id)


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    category: str  # UTILITY, MARKETING ou AUTHENTICATION
    language: str
    body: str
    variables: tuple[str, ...] = ()  # o que cada {{n}} significa, na ordem
    examples: tuple[str, ...] = ()  # exemplos exigidos pela Meta na criação
    footer: str = ""
    quick_replies: tuple[QuickReply, ...] = ()
    purpose: str = ""
    # Templates de exemplo criados pela própria Meta: não são enviados para aprovação
    managed_by_meta: bool = False

    def __post_init__(self) -> None:
        if not NAME_PATTERN.match(self.name):
            raise TemplateError(f"Nome inválido para a Meta: {self.name!r}")
        numbers = sorted({int(n) for n in _VARIABLE.findall(self.body)})
        if numbers != list(range(1, len(numbers) + 1)):
            raise TemplateError(f"{self.name}: variáveis precisam ser {{1}}, {{2}}... em sequência")
        if len(numbers) != len(self.variables) or len(numbers) != len(self.examples):
            raise TemplateError(f"{self.name}: descreva e exemplifique cada variável")
        for button in self.quick_replies:
            if not 1 <= len(button.text) <= 25:
                raise TemplateError(f"{self.name}: botão {button.text!r} fora de 1 a 25 caracteres")

    def creation_payload(self) -> dict[str, Any]:
        """Corpo do POST /<WABA_ID>/message_templates."""
        body: dict[str, Any] = {"type": "BODY", "text": self.body}
        if self.examples:
            body["example"] = {"body_text": [list(self.examples)]}
        components: list[dict[str, Any]] = [body]
        if self.footer:
            components.append({"type": "FOOTER", "text": self.footer})
        if self.quick_replies:
            components.append(
                {
                    "type": "BUTTONS",
                    "buttons": [
                        {"type": "QUICK_REPLY", "text": b.text} for b in self.quick_replies
                    ],
                }
            )
        return {
            "name": self.name,
            "language": self.language,
            "category": self.category,
            "parameter_format": "POSITIONAL",
            "components": components,
        }

    def render(self, values: Sequence[str]) -> str:
        """Texto legível com as variáveis preenchidas, para gravar em Message.body."""
        text = self.body
        for index, value in enumerate(values, start=1):
            text = text.replace(f"{{{{{index}}}}}", value)
        return text

    def build(self, *values: str) -> OutboundPayload:
        """Mensagem pronta para send_message, com variáveis e payloads dos botões."""
        if len(values) != len(self.variables):
            raise TemplateError(
                f"{self.name} espera {len(self.variables)} variáve"
                f"{'l' if len(self.variables) == 1 else 'is'}: {', '.join(self.variables)}"
            )
        components: list[dict[str, Any]] = []
        if values:
            components.append(
                {"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}
            )
        for index, button in enumerate(self.quick_replies):
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(index),
                    "parameters": [{"type": "payload", "payload": button.payload}],
                }
            )
        return template(
            self.name,
            language=self.language,
            components=components or None,
            preview=self.render(values),
        )


CATALOG_ENTRIES: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        name="hello_world",
        category="UTILITY",
        language="en_US",
        body="Hello World",
        purpose="Exemplo da Meta, já aprovado na conta de teste.",
        managed_by_meta=True,
    ),
    TemplateSpec(
        name="b2g_retomar_conversa",
        category="UTILITY",
        language="pt_BR",
        body=(
            "Olá, {{1}}! Aqui é o assistente automático da Brave2Grow. Você conversou com a "
            "gente por aqui e ficou um assunto pendente. Quer continuar o atendimento?"
        ),
        variables=("primeiro nome do contato",),
        examples=("Ana",),
        footer="Envie SAIR para não receber mais mensagens",
        quick_replies=(
            QuickReply("Sim, continuar", "retomar_sim"),
            QuickReply("Agora não", "retomar_nao"),
        ),
        purpose="Reabrir a janela de 24h com quem já conversou e tem consentimento.",
    ),
    TemplateSpec(
        name="b2g_confirmacao_reuniao",
        category="UTILITY",
        language="pt_BR",
        body=(
            "Olá, {{1}}! Sua conversa com a Brave2Grow está marcada para {{2}}. "
            "Você confirma a presença?"
        ),
        variables=("primeiro nome do contato", "data e hora da reunião"),
        examples=("Ana", "quinta-feira, 12/11, às 10h"),
        footer="Brave2Grow",
        quick_replies=(
            QuickReply("Confirmo", "reuniao_confirmar"),
            QuickReply("Reagendar", "reuniao_reagendar"),
            QuickReply("Cancelar", "reuniao_cancelar"),
        ),
        purpose="Confirmação de presença D-1 (F02).",
    ),
)

CATALOG: dict[tuple[str, str], TemplateSpec] = {
    (spec.name, spec.language): spec for spec in CATALOG_ENTRIES
}


def get_template(name: str, language: str | None = None) -> TemplateSpec:
    """Busca no catálogo; sem idioma, aceita o nome se ele existir em um só idioma."""
    if language:
        spec = CATALOG.get((name, language))
        if spec is None:
            raise TemplateError(f"Template {name} [{language}] não está no catálogo")
        return spec
    matches = [spec for (spec_name, _), spec in CATALOG.items() if spec_name == name]
    if len(matches) != 1:
        raise TemplateError(f"Template {name} não está no catálogo (ou existe em vários idiomas)")
    return matches[0]
