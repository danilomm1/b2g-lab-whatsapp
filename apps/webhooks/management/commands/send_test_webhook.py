import json
import uuid

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.webhooks.lab import SIGNATURE_HEADER
from apps.webhooks.signatures import sign_body


class Command(BaseCommand):
    help = "Envia um webhook assinado para o provedor lab do servidor local (testa a esteira)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--url", default="http://127.0.0.1:8602/webhooks/lab/")
        parser.add_argument("--message", default="ping do laboratório")
        parser.add_argument(
            "--type", default="ping", help="Rota; algo diferente de ping é ignorado."
        )
        parser.add_argument(
            "--bad-signature", action="store_true", help="Assina com segredo errado."
        )

    def handle(self, *args, **options) -> None:
        secret = settings.LAB_WEBHOOK_SECRET
        if not secret:
            raise CommandError("Defina LAB_WEBHOOK_SECRET no .env antes de testar.")
        body = json.dumps(
            {
                "id": uuid.uuid4().hex,
                "type": options["type"],
                "message": options["message"],
                "sent_at": timezone.now().isoformat(),
            }
        ).encode()
        signing_secret = "segredo-errado" if options["bad_signature"] else secret
        try:
            response = httpx.post(
                options["url"],
                content=body,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: sign_body(signing_secret, body),
                },
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise CommandError(f"Falha ao conectar em {options['url']}: {exc}") from exc
        self.stdout.write(f"HTTP {response.status_code}: {response.text}")
