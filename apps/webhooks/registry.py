"""Registro de provedores de webhook e dos handlers de cada rota.

Cada app de canal cria um WebhookProvider (assinatura, handshake, rota) e registra
handlers no ready() do seu AppConfig. Exemplo para a Fase 1:

    registry.register_provider(MetaProvider())          # rota = campo "object"

    @registry.handler("meta", "whatsapp_business_account")
    def handle_whatsapp(delivery): ...
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, QueryDict

if TYPE_CHECKING:
    from .models import WebhookDelivery

Handler = Callable[["WebhookDelivery"], None]


class WebhookProvider:
    """Base dos provedores. Subclasses definem slug e verify_signature."""

    slug: str = ""

    def verify_signature(self, request: HttpRequest) -> bool:
        raise NotImplementedError

    def handshake(self, request: HttpRequest) -> HttpResponse | None:
        """Resposta ao GET de verificação (ex.: hub.challenge da Meta). None recusa o GET."""
        return None

    def parse_payload(self, body: bytes, content_type: str) -> dict[str, Any] | list[Any]:
        """Converte o corpo em JSON ou formulário (Twilio). Corpo ilegível vira {}."""
        if content_type == "application/x-www-form-urlencoded":
            form = QueryDict(body.decode("utf-8", "replace"))
            return {key: values[0] if len(values) == 1 else values for key, values in form.lists()}
        try:
            return json.loads(body or b"{}")
        except ValueError:
            return {}

    def dedupe_key(self, payload: dict[str, Any] | list[Any], body: bytes) -> str:
        """Por padrão, o hash do corpo: um reenvio idêntico do provedor é descartado."""
        return hashlib.sha256(body).hexdigest()

    def route_key(self, payload: dict[str, Any] | list[Any]) -> str:
        return "default"


class WebhookRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, WebhookProvider] = {}
        self._handlers: defaultdict[tuple[str, str], list[Handler]] = defaultdict(list)

    def register_provider(self, provider: WebhookProvider) -> None:
        if not provider.slug:
            raise ImproperlyConfigured(f"{type(provider).__name__} precisa de um slug")
        current = self._providers.get(provider.slug)
        if current is not None and type(current) is not type(provider):
            raise ImproperlyConfigured(f"Slug de webhook já registrado: {provider.slug}")
        self._providers[provider.slug] = provider

    def get_provider(self, slug: str) -> WebhookProvider | None:
        return self._providers.get(slug)

    def register_handler(self, provider_slug: str, route_key: str, handler: Handler) -> None:
        handlers = self._handlers[(provider_slug, route_key)]
        if handler not in handlers:
            handlers.append(handler)

    def handler(self, provider_slug: str, route_key: str) -> Callable[[Handler], Handler]:
        """Decorator equivalente a register_handler."""

        def decorator(func: Handler) -> Handler:
            self.register_handler(provider_slug, route_key, func)
            return func

        return decorator

    def get_handlers(self, provider_slug: str, route_key: str) -> list[Handler]:
        return list(self._handlers.get((provider_slug, route_key), []))


registry = WebhookRegistry()
