"""Catálogo versionado dos WhatsApp Flows (formulários nativos) da Brave2Grow.

São Flows estáticos, sem endpoint de dados: a última tela termina com a ação "complete"
e as respostas voltam no webhook como mensagem interativa nfm_reply. Na Meta, um Flow
nasce como rascunho (DRAFT); publicado, não pode mais ser editado, só clonado ou
descontinuado. O estado na Meta fica em WhatsAppForm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

FLOW_JSON_VERSION = "6.0"
CATEGORIES = frozenset(
    {
        "SIGN_UP",
        "SIGN_IN",
        "APPOINTMENT_BOOKING",
        "LEAD_GENERATION",
        "CONTACT_US",
        "CUSTOMER_SUPPORT",
        "SURVEY",
        "OTHER",
    }
)


class FormError(ValueError):
    """Formulário inexistente no catálogo ou mal definido."""


@dataclass(frozen=True)
class FormSpec:
    name: str
    categories: tuple[str, ...]
    first_screen: str
    flow_json: dict[str, Any]
    purpose: str = ""

    def __post_init__(self) -> None:
        if not self.categories or not set(self.categories) <= CATEGORIES:
            raise FormError(f"{self.name}: categorias inválidas {self.categories}")
        screens = [screen["id"] for screen in self.flow_json.get("screens", [])]
        if self.first_screen not in screens or "SUCCESS" in screens:
            raise FormError(f"{self.name}: telas inválidas {screens}")

    def flow_json_text(self) -> str:
        return json.dumps(self.flow_json, ensure_ascii=False)


INTEREST_OPTIONS = [
    {"id": "servicos", "title": "Conhecer os serviços"},
    {"id": "agendar", "title": "Agendar uma conversa"},
    {"id": "conteudo", "title": "Receber conteúdos"},
]
NEWS_OPT_IN_LABEL = "Quero receber novidades da Brave2Grow pelo WhatsApp (posso cancelar com SAIR)."

CADASTRO = FormSpec(
    name="b2g_cadastro",
    categories=("LEAD_GENERATION",),
    first_screen="CADASTRO",
    purpose="Cadastro de lead com nome, email, interesse e opt-in explícito de novidades.",
    flow_json={
        "version": FLOW_JSON_VERSION,
        "screens": [
            {
                "id": "CADASTRO",
                "title": "Seus dados",
                "terminal": True,
                "success": True,
                "layout": {
                    "type": "SingleColumnLayout",
                    "children": [
                        {
                            "type": "TextBody",
                            "text": "Preencha para a Brave2Grow te atender melhor.",
                        },
                        {
                            "type": "TextInput",
                            "name": "nome",
                            "label": "Nome",
                            "input-type": "text",
                            "required": True,
                        },
                        {
                            "type": "TextInput",
                            "name": "email",
                            "label": "Email",
                            "input-type": "email",
                            "required": True,
                        },
                        {
                            "type": "RadioButtonsGroup",
                            "name": "interesse",
                            "label": "O que você procura?",
                            "required": True,
                            "data-source": INTEREST_OPTIONS,
                        },
                        {
                            "type": "OptIn",
                            "name": "novidades",
                            "label": NEWS_OPT_IN_LABEL,
                            "required": False,
                        },
                        {
                            "type": "Footer",
                            "label": "Enviar",
                            "on-click-action": {
                                "name": "complete",
                                "payload": {
                                    "nome": "${form.nome}",
                                    "email": "${form.email}",
                                    "interesse": "${form.interesse}",
                                    "novidades": "${form.novidades}",
                                },
                            },
                        },
                    ],
                },
            }
        ],
    },
)

FORMS: dict[str, FormSpec] = {spec.name: spec for spec in (CADASTRO,)}


def get_form(name: str) -> FormSpec:
    try:
        return FORMS[name]
    except KeyError as exc:
        raise FormError(f"Formulário {name} não está no catálogo") from exc
