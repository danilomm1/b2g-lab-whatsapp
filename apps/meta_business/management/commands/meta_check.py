from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.meta_business.client import GraphAPIError
from apps.meta_business.services import (
    check_assets,
    inspect_token,
    sync_system_user_credential,
)

REQUIRED_SETTINGS = (
    "META_APP_ID",
    "META_APP_SECRET",
    "META_SYSTEM_USER_TOKEN",
    "META_WEBHOOK_VERIFY_TOKEN",
)


class Command(BaseCommand):
    help = (
        "Confere a configuração da Meta: variáveis, token do System User (debug_token) e "
        "acesso aos ativos do .env. Só faz leituras na Graph API."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--no-save", action="store_true", help="Não grava a credencial no banco."
        )

    def handle(self, *args, **options) -> None:
        self.stdout.write(f"Graph API {settings.META_GRAPH_API_VERSION}\n")
        self.stdout.write("Variáveis")
        missing = []
        for name in REQUIRED_SETTINGS:
            filled = bool(getattr(settings, name))
            if not filled:
                missing.append(name)
            self.stdout.write(f"  {name}: {'ok' if filled else 'FALTA'}")
        if {"META_APP_ID", "META_APP_SECRET", "META_SYSTEM_USER_TOKEN"} & set(missing):
            raise CommandError("Preencha App ID, App Secret e token do System User no .env.")

        token = settings.META_SYSTEM_USER_TOKEN
        try:
            info = inspect_token(token)
        except GraphAPIError as exc:
            raise CommandError(f"debug_token falhou: {exc} (code={exc.code})") from exc

        expires = info.expires_at.strftime("%d/%m/%Y %H:%M UTC") if info.expires_at else "nunca"
        app_check = "confere" if info.matches_configured_app else "NÃO confere com META_APP_ID"
        self.stdout.write("\nToken do System User")
        self.stdout.write(f"  válido: {'sim' if info.is_valid else 'NÃO'}")
        self.stdout.write(f"  app: {info.application} ({info.app_id}), {app_check}")
        self.stdout.write(f"  tipo: {info.token_type or '-'} | usuário: {info.user_id or '-'}")
        self.stdout.write(f"  expira: {expires}")
        self.stdout.write(f"  permissões: {', '.join(info.scopes) or 'nenhuma'}")
        if info.error:
            self.stdout.write(self.style.ERROR(f"  erro: {info.error}"))

        self.stdout.write("\nAtivos do .env")
        for check in check_assets(info):
            if not check.is_configured:
                self.stdout.write(f"  {check.setting}: não configurado")
            elif check.reachable_scopes:
                self.stdout.write(
                    f"  {check.setting} {check.asset_id}: alcançado por "
                    f"{', '.join(check.reachable_scopes)}"
                )
            elif not check.granted_scopes:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {check.setting} {check.asset_id}: o token não tem nenhuma das "
                        f"permissões deste ativo ({', '.join(check.missing_scopes)}). Adicione-as "
                        "ao caso de uso no painel do app e gere um token novo."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {check.setting} {check.asset_id}: o token NÃO alcança este ativo. "
                        "Atribua-o ao System User no Business Manager."
                    )
                )

        if not options["no_save"]:
            credential = sync_system_user_credential(token, info)
            self.stdout.write(f"\nCredencial gravada: {credential} ({credential.status().label})")

        verify_token = "definido" if settings.META_WEBHOOK_VERIFY_TOKEN else "AUSENTE"
        self.stdout.write(
            "\nWebhook: callback https://<host-do-servidor>/webhooks/meta/ com o "
            f"META_WEBHOOK_VERIFY_TOKEN {verify_token}"
        )
        if not info.is_valid or not info.matches_configured_app:
            raise CommandError("O token não está pronto para uso.")
