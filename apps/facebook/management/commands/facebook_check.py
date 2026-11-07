from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.facebook.services import (
    PAGE_WEBHOOK_FIELDS,
    fetch_page,
    page_subscription,
    save_page_token,
    subscribe_page,
)
from apps.meta_business.client import GraphAPIError, GraphClient
from apps.meta_business.services import inspect_token


class Command(BaseCommand):
    help = (
        "Confere a Página: tarefas do usuário do sistema, token da Página (gravado "
        "criptografado) e campos de webhook assinados. Só faz leituras na Graph API, "
        "exceto com --subscribe."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--subscribe",
            action="store_true",
            help="Inscreve o app na Página com os campos do laboratório (POST subscribed_apps).",
        )
        parser.add_argument(
            "--no-save", action="store_true", help="Não grava o token da Página no banco."
        )

    def handle(self, *args, **options) -> None:
        page_id = settings.FACEBOOK_PAGE_ID
        self.stdout.write(f"Graph API {settings.META_GRAPH_API_VERSION}\n")
        self.stdout.write(f"  FACEBOOK_PAGE_ID: {page_id or 'FALTA'}")
        if not page_id:
            raise CommandError("Copie o ID da Página (Configurações da Página > Transparência).")

        problems = []
        try:
            with GraphClient() as system_user:
                page = fetch_page(system_user, page_id)
            if not page.access_token:
                raise CommandError(
                    "A Graph API não devolveu o token da Página: atribua a Página ao usuário "
                    "do sistema e gere um token com pages_show_list."
                )
            info = inspect_token(page.access_token)
            with GraphClient(access_token=page.access_token) as page_client:
                if options["subscribe"]:
                    subscribe_page(page_client, page.page_id)
                fields = page_subscription(page_client, page.page_id)
        except GraphAPIError as exc:
            raise CommandError(f"Graph API recusou: {exc} (code={exc.code})") from exc

        self.stdout.write("\nPágina")
        self.stdout.write(f"  nome: {page.name or '-'}")
        self.stdout.write(f"  tarefas do usuário do sistema: {', '.join(page.tasks) or '-'}")
        self.stdout.write(f"  Instagram conectado: {page.instagram_account_id or 'nenhum'}")
        if page.missing_tasks:
            problems.append(
                f"Faltam tarefas na Página ({', '.join(page.missing_tasks)}): dê acesso total à "
                "Página ao usuário do sistema no Business Manager."
            )

        expires = info.expires_at.strftime("%d/%m/%Y %H:%M UTC") if info.expires_at else "nunca"
        self.stdout.write("\nToken da Página")
        self.stdout.write(f"  válido: {'sim' if info.is_valid else 'NÃO'} | expira: {expires}")
        if not info.is_valid:
            problems.append("O token da Página não é válido.")
        if not options["no_save"]:
            credential = save_page_token(page, info)
            self.stdout.write(f"  gravado: {credential} ({credential.status().label})")

        self.stdout.write("\nWebhooks da Página (app inscrito)")
        if fields is None:
            self.stdout.write("  o app NÃO está inscrito na Página")
            problems.append("O app não está inscrito na Página: rode de novo com --subscribe.")
        else:
            self.stdout.write(f"  campos: {', '.join(fields) or 'nenhum'}")
            missing = [field for field in PAGE_WEBHOOK_FIELDS if field not in fields]
            if missing:
                problems.append(
                    f"Campos não assinados na Página: {', '.join(missing)}. Rode com --subscribe."
                )

        for problem in problems:
            self.stdout.write(self.style.WARNING(f"\n{problem}"))
        if problems:
            raise CommandError("A Página ainda não está pronta.")
