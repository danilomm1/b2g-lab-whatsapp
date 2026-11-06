"""Chamadas da WhatsApp Cloud API sobre o GraphClient da Fase 1.

Este módulo só fala com a API. As travas (dry-run, allowlist, janela de 24h,
consentimento) ficam em services.py, que é o único ponto de envio do app.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.meta_business.client import GraphClient

PHONE_NUMBER_FIELDS = (
    "display_phone_number,verified_name,quality_rating,code_verification_status,"
    "name_status,platform_type,throughput"
)
TEMPLATE_FIELDS = "id,name,status,category,language,components,rejected_reason"


def default_phone_number_id() -> str:
    if not settings.WHATSAPP_PHONE_NUMBER_ID:
        raise ImproperlyConfigured("Defina WHATSAPP_PHONE_NUMBER_ID no .env.")
    return settings.WHATSAPP_PHONE_NUMBER_ID


class WhatsAppClient:
    """Envio pelo número configurado e consultas de leitura ao número e à WABA."""

    def __init__(self, phone_number_id: str | None = None, *, graph: GraphClient | None = None):
        self.phone_number_id = phone_number_id or default_phone_number_id()
        self._own_graph = graph is None
        self.graph = graph or GraphClient()

    def __enter__(self) -> WhatsAppClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._own_graph:
            self.graph.close()

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        """POST /<PHONE_NUMBER_ID>/messages. Não é repetido se a Meta puder ter enviado."""
        return self.graph.post(f"{self.phone_number_id}/messages", request)

    def mark_as_read(self, wamid: str, *, typing: bool = False) -> dict[str, Any]:
        """Marca como lida (tique azul) e, se typing, mostra "digitando..." por até 25 s."""
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wamid,
        }
        if typing:
            body["typing_indicator"] = {"type": "text"}
        return self.graph.post(f"{self.phone_number_id}/messages", body, idempotent=True)

    def phone_number(self) -> dict[str, Any]:
        return self.graph.get(self.phone_number_id, {"fields": PHONE_NUMBER_FIELDS})

    def subscribed_apps(self, waba_id: str) -> list[dict[str, Any]]:
        return self.graph.get(f"{waba_id}/subscribed_apps").get("data", [])

    def message_templates(self, waba_id: str) -> list[dict[str, Any]]:
        response = self.graph.get(
            f"{waba_id}/message_templates",
            {"fields": TEMPLATE_FIELDS, "limit": 100},
        )
        return response.get("data", [])

    def create_template(self, waba_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /<WABA_ID>/message_templates: envia o template para a análise da Meta."""
        return self.graph.post(f"{waba_id}/message_templates", payload)

    def upload_media(self, content: bytes, mime_type: str, filename: str) -> str:
        """POST /<PHONE_NUMBER_ID>/media (multipart). A mídia fica 30 dias na Meta."""
        response = self.graph.request(
            "POST",
            f"{self.phone_number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (filename, content, mime_type)},
            idempotent=False,
        )
        return str(response["id"])

    def media_info(self, media_id: str) -> dict[str, Any]:
        """GET /<MEDIA_ID>: URL (válida por 5 minutos), tipo, tamanho e sha256."""
        return self.graph.get(media_id, {"phone_number_id": self.phone_number_id})

    def download_media(self, media_id: str) -> tuple[bytes, dict[str, Any]]:
        """Baixa uma mídia recebida: consulta a URL e baixa com o token."""
        info = self.media_info(media_id)
        content, _ = self.graph.download(info["url"])
        return content, info

    def create_form(
        self, waba_id: str, name: str, categories: list[str], flow_json: str, *, publish: bool
    ) -> dict[str, Any]:
        """POST /<WABA_ID>/flows: cria um WhatsApp Flow (formulário nativo), publicado ou não."""
        return self.graph.request(
            "POST",
            f"{waba_id}/flows",
            json_body={
                "name": name,
                "categories": categories,
                "flow_json": flow_json,
                "publish": publish,
            },
            idempotent=False,
        )

    def forms(self, waba_id: str) -> list[dict[str, Any]]:
        response = self.graph.get(
            f"{waba_id}/flows", {"fields": "id,name,status,categories,validation_errors"}
        )
        return response.get("data", [])
