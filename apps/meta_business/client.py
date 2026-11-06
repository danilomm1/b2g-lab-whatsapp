"""Cliente da Graph API da Meta, com retry e registro completo dos erros.

O token vai no cabeçalho Authorization, nunca na URL, e cada chamada leva o
appsecret_proof quando o App Secret está configurado. Chamadas com efeito no mundo
real (enviar, publicar) devem passar antes por apps.core.safety.check_outbound.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.facebook.com"

# Códigos das páginas "Error handling" e "Rate limiting" da Graph API; 130429 é o limite
# de vazão de mensagens da WhatsApp Cloud API
TRANSIENT_CODES = frozenset({1, 2})
RATE_LIMIT_CODES = frozenset({4, 17, 32, 341, 613, 130429, *range(80000, 80015)})
AUTH_CODES = frozenset({10, 102, 190, *range(200, 300)})


class GraphAPIError(Exception):
    """Erro da Graph API ou falha de rede que persistiu depois das novas tentativas."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        error_type: str = "",
        fbtrace_id: str = "",
        payload: dict[str, Any] | None = None,
        retry_after: float | None = None,
        network: bool = False,
        request_sent: bool = True,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.subcode = subcode
        self.error_type = error_type
        self.fbtrace_id = fbtrace_id
        self.payload = payload or {}
        self.retry_after = retry_after
        self.network = network
        # False só quando a conexão nem chegou a ser aberta: a Meta não recebeu nada
        self.request_sent = request_sent

    @property
    def is_rate_limit(self) -> bool:
        return self.code in RATE_LIMIT_CODES or self.status == 429

    @property
    def is_auth_error(self) -> bool:
        return self.code in AUTH_CODES

    @property
    def is_transient(self) -> bool:
        """Vale tentar de novo: rede, erro 5xx, códigos transitórios ou limite de volume."""
        error = self.payload.get("error", {}) if isinstance(self.payload, dict) else {}
        return (
            self.network
            or self.code in TRANSIENT_CODES
            or self.is_rate_limit
            or (self.status is not None and self.status >= 500)
            or (isinstance(error, dict) and error.get("is_transient") is True)
        )


def appsecret_proof(access_token: str, app_secret: str) -> str:
    """HMAC-SHA256 do token com o App Secret, em hex (doc "Securing requests")."""
    return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


def app_access_token() -> str:
    """Token de app (app_id|app_secret), usado no debug_token."""
    if not settings.META_APP_ID or not settings.META_APP_SECRET:
        raise ImproperlyConfigured("Defina META_APP_ID e META_APP_SECRET no .env.")
    return f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Tempo de espera indicado pela Meta (Retry-After ou estimated_time_to_regain_access)."""
    if response.headers.get("Retry-After", "").isdigit():
        return float(response.headers["Retry-After"])
    raw = response.headers.get("X-Business-Use-Case-Usage")
    if not raw:
        return None
    try:
        usage = json.loads(raw)
    except ValueError:
        return None
    minutes = [
        entry.get("estimated_time_to_regain_access") or 0
        for entries in usage.values()
        if isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict)
    ]
    return max(minutes) * 60 if minutes and max(minutes) > 0 else None


def _error_from_response(response: httpx.Response) -> GraphAPIError:
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:2000]}
    error = body.get("error", {}) if isinstance(body, dict) else {}
    return GraphAPIError(
        error.get("message") or f"HTTP {response.status_code}",
        status=response.status_code,
        code=error.get("code"),
        subcode=error.get("error_subcode"),
        error_type=error.get("type", ""),
        fbtrace_id=error.get("fbtrace_id", ""),
        payload=body,
        retry_after=_retry_after_seconds(response),
    )


class GraphClient:
    """Chamadas à Graph API com retry exponencial para erros transitórios e de limite."""

    def __init__(
        self,
        access_token: str | None = None,
        *,
        version: str | None = None,
        app_secret: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        max_wait: float = 30.0,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.access_token = (
            settings.META_SYSTEM_USER_TOKEN if access_token is None else access_token
        )
        self.version = version or settings.META_GRAPH_API_VERSION
        self.app_secret = settings.META_APP_SECRET if app_secret is None else app_secret
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_wait = max_wait
        self.sleep = sleep
        self.last_usage: dict[str, Any] = {}
        self._http = httpx.Client(base_url=f"{GRAPH_BASE_URL}/{self.version}", timeout=timeout)

    def __enter__(self) -> GraphClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def post(
        self, path: str, json_body: dict[str, Any], *, idempotent: bool = False
    ) -> dict[str, Any]:
        """POST com corpo JSON. Por padrão, tratado como não idempotente (ex.: enviar mensagem)."""
        return self.request("POST", path, json_body=json_body, idempotent=idempotent)

    def download(self, url: str, *, max_bytes: int = 100 * 1024 * 1024) -> tuple[bytes, str]:
        """Baixa um arquivo da Meta (ex.: URL de mídia, que exige o token): (bytes, tipo)."""
        if not self.access_token:
            raise ImproperlyConfigured("Token da Graph API ausente (META_SYSTEM_USER_TOKEN).")
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            response = self._http.get(url, headers=headers, follow_redirects=True)
        except httpx.TransportError as exc:
            raise GraphAPIError(f"Falha de rede ao baixar mídia: {exc}", network=True) from exc
        if not response.is_success:
            raise _error_from_response(response)
        if len(response.content) > max_bytes:
            raise GraphAPIError(f"Arquivo maior que {max_bytes} bytes", status=response.status_code)
        return response.content, response.headers.get("Content-Type", "")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        idempotent: bool = True,
    ) -> dict[str, Any]:
        """Faz a chamada; erros transitórios são repetidos, os demais viram GraphAPIError.

        Com idempotent=False (envios), só repete quando a Meta com certeza não executou a
        chamada: limite de volume ou falha antes de abrir a conexão. Repetir depois de um
        timeout de leitura ou de um erro 5xx poderia mandar a mesma mensagem duas vezes.
        """
        if not self.access_token:
            raise ImproperlyConfigured("Token da Graph API ausente (META_SYSTEM_USER_TOKEN).")
        params = dict(params or {})
        # O token de app (id|secret) já carrega o segredo; o proof só vale para os demais
        if self.app_secret and "|" not in self.access_token:
            params["appsecret_proof"] = appsecret_proof(self.access_token, self.app_secret)
        headers = {"Authorization": f"Bearer {self.access_token}"}

        attempt = 0
        while True:
            try:
                response = self._http.request(
                    method,
                    path.lstrip("/"),
                    params=params,
                    data=data,
                    json=json_body,
                    files=files,
                    headers=headers,
                )
            except httpx.TransportError as exc:
                error = GraphAPIError(
                    f"Falha de rede: {exc}",
                    network=True,
                    request_sent=not isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout),
                )
            else:
                self._store_usage(response)
                if response.is_success:
                    return response.json()
                error = _error_from_response(response)

            logger.warning(
                "Graph API %s %s falhou (tentativa %d): status=%s code=%s subcode=%s "
                "fbtrace_id=%s resposta=%s",
                method,
                path,
                attempt + 1,
                error.status,
                error.code,
                error.subcode,
                error.fbtrace_id,
                json.dumps(error.payload, ensure_ascii=False)[:4000],
            )
            wait = self._wait_before_retry(error, attempt, idempotent=idempotent)
            if wait is None:
                raise error
            self.sleep(wait)
            attempt += 1

    def _wait_before_retry(
        self, error: GraphAPIError, attempt: int, *, idempotent: bool = True
    ) -> float | None:
        """Espera da próxima tentativa, ou None para desistir.

        Se a Meta pede para esperar mais que max_wait, desiste na hora: a tarefa do Huey
        que chamou decide quando tentar de novo, usando error.retry_after.
        """
        if not error.is_transient or attempt >= self.max_retries:
            return None
        if not idempotent and not (error.is_rate_limit or not error.request_sent):
            return None
        wait = self.backoff_base * (2**attempt)
        if error.retry_after:
            wait = max(wait, error.retry_after)
        return wait if wait <= self.max_wait else None

    def _store_usage(self, response: httpx.Response) -> None:
        for header in ("X-App-Usage", "X-Business-Use-Case-Usage"):
            if header in response.headers:
                try:
                    self.last_usage[header] = json.loads(response.headers[header])
                except ValueError:
                    self.last_usage[header] = response.headers[header]
