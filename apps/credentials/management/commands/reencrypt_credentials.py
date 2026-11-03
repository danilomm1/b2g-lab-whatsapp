from django.core.management.base import BaseCommand
from django.db import transaction

from apps.credentials.models import IntegrationCredential


class Command(BaseCommand):
    help = (
        "Regrava todas as credenciais com a primeira chave de FIELD_ENCRYPTION_KEY. "
        "Use na rotação: nova chave na frente da lista, rode este comando, remova a antiga."
    )

    def handle(self, *args, **options) -> None:
        with transaction.atomic():
            credentials = list(IntegrationCredential.objects.all())
            for credential in credentials:
                credential.save(update_fields=["access_token", "refresh_token"])
        self.stdout.write(self.style.SUCCESS(f"{len(credentials)} credenciais regravadas."))
