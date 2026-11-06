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
            {"fields": "name,status,category,language", "limit": 100},
        )
        return response.get("data", [])
