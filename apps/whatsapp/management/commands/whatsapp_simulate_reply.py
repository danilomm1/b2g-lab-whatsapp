import json
import time
import uuid

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Channel, ChannelIdentity, Contact
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.meta_business.webhook import SIGNATURE_HEADER
from apps.webhooks.signatures import sign_body
from apps.whatsapp.services import SIMULATED_WAMID_PREFIX


class Command(BaseCommand):
    help = (
        "Simula uma resposta do contato com um webhook assinado como a Meta: texto ou toque "
        "em botão de template. Valida respostas hipotéticas (ex.: botões de templates ainda "
        "em análise) pela esteira real. A mensagem fica marcada como simulada no bruto."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--contact", required=True, help="Telefone (E.164) do contato.")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--text", help="Texto enviado pelo contato.")
        group.add_argument("--template-button", help="Payload do botão de template tocado.")
        parser.add_argument("--title", default="", help="Rótulo do botão tocado.")
        parser.add_argument("--url", default="http://127.0.0.1:8602/webhooks/meta/")

    def handle(self, *args, **options) -> None:
        if not settings.META_APP_SECRET or not settings.WHATSAPP_PHONE_NUMBER_ID:
            raise CommandError("Defina META_APP_SECRET e WHATSAPP_PHONE_NUMBER_ID no .env.")
        try:
            phone = normalize_phone(options["contact"])
        except InvalidPhoneNumber as exc:
            raise CommandError(str(exc)) from exc
        contact = Contact.objects.filter(phone=phone).first()
        if contact is None:
            raise CommandError(f"Nenhum contato com {phone}.")
        identity = (
            ChannelIdentity.objects.filter(contact=contact, channel=Channel.WHATSAPP)
            .order_by("-last_seen_at")
            .first()
        )
        user_id = identity.external_id if identity and "." in identity.external_id else ""
        wa_id = phone.lstrip("+")

        message = {
            "from": wa_id,
            "id": f"{SIMULATED_WAMID_PREFIX}{uuid.uuid4().hex}",
            "timestamp": str(int(time.time())),
            "simulated": True,
        }
        if user_id:
            message["from_user_id"] = user_id
        if options["text"] is not None:
            message |= {"type": "text", "text": {"body": options["text"]}}
        else:
            button = {"payload": options["template_button"], "text": options["title"]}
            message |= {"type": "button", "button": button}
        contact_block = {"profile": {"name": contact.name}, "wa_id": wa_id}
        if user_id:
            contact_block["user_id"] = user_id
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": settings.WHATSAPP_BUSINESS_ACCOUNT_ID,
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID},
                                "contacts": [contact_block],
                                "messages": [message],
                            },
                        }
                    ],
                }
            ],
        }
        body = json.dumps(payload).encode()
        try:
            response = httpx.post(
                options["url"],
                content=body,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: sign_body(settings.META_APP_SECRET, body),
                },
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise CommandError(f"Falha ao conectar em {options['url']}: {exc}") from exc
        self.stdout.write(f"HTTP {response.status_code}: {response.text} ({message['id']})")
