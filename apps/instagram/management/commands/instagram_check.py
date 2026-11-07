from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.instagram.services import (
    INSTAGRAM_WEBHOOK_FIELDS,
    account_subscription,
    check_messaging_access,
    fetch_account,
    publishing_limit,
    subscribe_account,
)
from apps.meta_business.client import GraphAPIError, GraphClient


class Command(BaseCommand):
    help = (
        "Confere a conta do Instagram: perfil, acesso ao Direct, campos de webhook assinados "
        "e cota de publicação. Só faz leituras na Graph API, exceto com --subscribe."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--subscribe",
            action="store_true",
            help="Inscreve o app na conta com os campos do laboratório (POST subscribed_apps).",
        )

    def handle(self, *args, **options) -> None:
        account_id = settings.INSTAGRAM_BUSINESS_ACCOUNT_ID
        self.stdout.write(f"Graph API {settings.META_GRAPH_API_VERSION}\n")
        self.stdout.write(f"  INSTAGRAM_BUSINESS_ACCOUNT_ID: {account_id or 'FALTA'}")
        if not account_id:
            raise CommandError(
                "Copie o ID da conta do Instagram (o facebook_check mostra o conectado à Página)."
            )

        problems = []
        try:
            with GraphClient() as client:
                account = fetch_account(client, account_id)
                access = check_messaging_access(client, account_id)
                if options["subscribe"]:
                    subscribe_account(client, account_id)
                fields = account_subscription(client, account_id)
                limit = publishing_limit(client, account_id)
        except GraphAPIError as exc:
            raise CommandError(f"Graph API recusou: {exc} (code={exc.code})") from exc

        self.stdout.write("\nConta")
        self.stdout.write(f"  @{account.get('username', '-')} ({account.get('name', '-')})")
        self.stdout.write(
            f"  seguidores: {account.get('followers_count', '-')} | "
            f"publicações: {account.get('media_count', '-')}"
        )

        self.stdout.write("\nDirect")
        if access.ok:
            self.stdout.write("  leitura de conversas: ok")
        else:
            self.stdout.write(f"  leitura de conversas: FALHOU ({access.error})")
            problems.append(
                "Sem acesso às mensagens: no app do Instagram da conta, ligue Configurações > "
                "Mensagens e respostas a stories > Ferramentas conectadas > Permitir acesso "
                "às mensagens."
            )

        self.stdout.write("\nWebhooks da conta (app inscrito)")
        if fields is None:
            self.stdout.write("  o app NÃO está inscrito na conta")
            problems.append("O app não está inscrito na conta: rode de novo com --subscribe.")
        else:
            self.stdout.write(f"  campos: {', '.join(fields) or 'nenhum'}")
            missing = [field for field in INSTAGRAM_WEBHOOK_FIELDS if field not in fields]
            if missing:
                problems.append(
                    f"Campos não assinados na conta: {', '.join(missing)}. Rode com --subscribe."
                )

        config = limit.get("config") or {}
        self.stdout.write("\nPublicação")
        self.stdout.write(
            f"  cota usada nas últimas 24h: {limit.get('quota_usage', '-')} de "
            f"{config.get('quota_total', '-')}"
        )

        for problem in problems:
            self.stdout.write(self.style.WARNING(f"\n{problem}"))
        if problems:
            raise CommandError("O Instagram ainda não está pronto.")
