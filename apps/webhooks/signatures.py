"""Assinaturas HMAC-SHA256 de webhooks (mesmo esquema do X-Hub-Signature-256 da Meta)."""

import hashlib
import hmac


def compute_hmac_sha256(secret: str, body: bytes) -> str:
    """Hex do HMAC-SHA256 do corpo bruto."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def sign_body(secret: str, body: bytes, *, prefix: str = "sha256=") -> str:
    """Valor de cabeçalho de assinatura para um corpo (útil em testes e scripts)."""
    return f"{prefix}{compute_hmac_sha256(secret, body)}"


def verify_hmac_sha256(
    secret: str, body: bytes, header_value: str, *, prefix: str = "sha256="
) -> bool:
    """Confere a assinatura em tempo constante. Segredo ou cabeçalho vazio nunca validam."""
    if not secret or not header_value:
        return False
    received = header_value.strip()
    if prefix:
        if not received.startswith(prefix):
            return False
        received = received[len(prefix) :]
    expected = compute_hmac_sha256(secret, body)
    return hmac.compare_digest(expected.encode(), received.lower().encode("utf-8", "replace"))
