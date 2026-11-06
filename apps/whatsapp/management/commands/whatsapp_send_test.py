from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Contact, MessageStatus
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.whatsapp import payloads
from apps.whatsapp.services import SendBlocked, send_message
from apps.whatsapp.templates_catalog import TemplateError, get_template


class Command(BaseCommand):
    help = (
        "Envia uma mensagem de teste pelo WhatsApp, passando por todas as travas. Com "
        "LAB_DRY_RUN=True o envio é só simulado. Texto livre exige a janela de 24h aberta "
        "(o contato escreveu antes); fora dela, use --template, que exige consentimento."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--to", required=True, help="Telefone do destinatário (E.164).")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--text", help="Texto livre (dentro da janela de 24h).")
        group.add_argument("--template", help="Nome de um template aprovado, ex.: hello_world.")
        parser.add_argument("--language", help="Idioma do template (padrão: o do catálogo).")
        parser.add_argument(
            "--var",
            action="append",
            default=[],
            help="Variável do template, na ordem de {{1}}, {{2}}... (repita a opção).",
        )

    def handle(self, *args, **options) -> None:
        try:
            phone = normalize_phone(options["to"])
        except InvalidPhoneNumber as exc:
            raise CommandError(str(exc)) from exc
        contact = Contact.objects.filter(phone=phone).first()
        if contact is None:
            raise CommandError(
                f"Nenhum contato com {phone}. Mande uma mensagem desse número para o número "
                "de teste antes: isso cria o contato e abre a janela de 24h."
            )

        if options["text"]:
            outbound = payloads.text(options["text"])
        else:
            try:
                spec = get_template(options["template"], options["language"])
                outbound = spec.build(*options["var"])
            except TemplateError as exc:
                raise CommandError(str(exc)) from exc

        mode = "simulado (LAB_DRY_RUN=True)" if settings.LAB_DRY_RUN else "real"
        self.stdout.write(f"Modo: {mode}")
        try:
            message = send_message(contact, outbound)
        except SendBlocked as exc:
            raise CommandError(f"Envio bloqueado: {exc}") from exc

        if message.status == MessageStatus.FAILED:
            raise CommandError(f"A Graph API recusou o envio: {message.error.get('message')}")
        self.stdout.write(
            f"Mensagem #{message.pk} {message.get_status_display()} "
            f"{message.external_id or ''}".rstrip()
        )
