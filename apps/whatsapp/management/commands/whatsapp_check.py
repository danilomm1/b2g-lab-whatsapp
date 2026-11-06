from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.meta_business.client import GraphAPIError
from apps.whatsapp.client import WhatsAppClient


class Command(BaseCommand):
    help = (
        "Confere o WhatsApp: número da Cloud API, app assinado na WABA e templates. "
        "Só faz leituras na Graph API."
    )

    def handle(self, *args, **options) -> None:
        waba_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.stdout.write(f"Graph API {settings.META_GRAPH_API_VERSION}\n")
        self.stdout.write(f"  WHATSAPP_BUSINESS_ACCOUNT_ID: {waba_id or 'FALTA'}")
        self.stdout.write(f"  WHATSAPP_PHONE_NUMBER_ID: {phone_number_id or 'FALTA'}")
        if not waba_id or not phone_number_id:
            raise CommandError(
                "Copie os dois IDs de WhatsApp > Configuração da API no painel do app."
            )

        problems = []
        with WhatsAppClient(phone_number_id) as client:
            try:
                number = client.phone_number()
                apps = client.subscribed_apps(waba_id)
                templates = client.message_templates(waba_id)
            except GraphAPIError as exc:
                raise CommandError(f"Graph API recusou: {exc} (code={exc.code})") from exc

        self.stdout.write("\nNúmero")
        for field in ("display_phone_number", "verified_name", "quality_rating", "name_status"):
            self.stdout.write(f"  {field}: {number.get(field, '-')}")
        throughput = (number.get("throughput") or {}).get("level", "-")
        self.stdout.write(f"  throughput: {throughput}")

        self.stdout.write("\nApps assinados na WABA (recebem os webhooks)")
        app_ids = [
            str((item.get("whatsapp_business_api_data") or {}).get("id", "")) for item in apps
        ]
        for item, app_id in zip(apps, app_ids, strict=True):
            name = (item.get("whatsapp_business_api_data") or {}).get("name", "")
            self.stdout.write(f"  {name or '-'} ({app_id or '-'})")
        if str(settings.META_APP_ID) not in app_ids:
            problems.append(
                "O app do laboratório não está assinado na WABA: os webhooks de mensagens não "
                "vão chegar. Assine pelo painel do app (webhook do WhatsApp) ou com "
                "POST /<WABA_ID>/subscribed_apps (docs/integrations/whatsapp.md)."
            )

        self.stdout.write(f"\nTemplates ({len(templates)})")
        for item in templates:
            self.stdout.write(
                f"  {item.get('name')} [{item.get('language')}] "
                f"{item.get('category')} {item.get('status')}"
            )

        for problem in problems:
            self.stdout.write(self.style.WARNING(f"\n{problem}"))
        if problems:
            raise CommandError("WhatsApp ainda não está pronto para receber mensagens.")
