from django.core.management.base import BaseCommand

from apps.credentials.crypto import generate_key


class Command(BaseCommand):
    help = "Gera uma chave Fernet para FIELD_ENCRYPTION_KEY (não grava em lugar nenhum)."

    def handle(self, *args, **options) -> None:
        self.stdout.write(generate_key())
