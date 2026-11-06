from django.core.management.base import BaseCommand, CommandError

from apps.meta_business.client import GraphAPIError
from apps.whatsapp.models import MessageTemplate
from apps.whatsapp.template_sync import submit_template, sync_templates
from apps.whatsapp.templates_catalog import CATALOG_ENTRIES, TemplateError, get_template


class Command(BaseCommand):
    help = (
        "Templates do WhatsApp: 'list' compara o catálogo com a Meta, 'sync' atualiza o status "
        "(só leitura) e 'submit <nome>' envia um template do catálogo para aprovação."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("action", choices=["list", "sync", "submit"])
        parser.add_argument("name", nargs="?", help="Nome do template (para submit).")
        parser.add_argument("--language", help="Idioma, se o nome existir em mais de um.")

    def handle(self, *args, **options) -> None:
        try:
            if options["action"] == "sync":
                templates = sync_templates()
                self.stdout.write(f"{len(templates)} templates sincronizados.")
            elif options["action"] == "submit":
                if not options["name"]:
                    raise CommandError("Informe o nome do template: submit <nome>.")
                spec = get_template(options["name"], options["language"])
                template = submit_template(spec)
                self.stdout.write(
                    f"{template.name} [{template.language}] enviado: {template.status} "
                    f"({template.category})"
                )
                return
        except (TemplateError, GraphAPIError) as exc:
            raise CommandError(str(exc)) from exc
        self._list()

    def _list(self) -> None:
        known = {(t.name, t.language): t for t in MessageTemplate.objects.all()}
        self.stdout.write("Catálogo")
        for spec in CATALOG_ENTRIES:
            stored = known.pop((spec.name, spec.language), None)
            state = f"{stored.status} ({stored.category})" if stored else "não enviado"
            if stored and stored.rejected_reason:
                state += f", motivo: {stored.rejected_reason}"
            self.stdout.write(f"  {spec.name} [{spec.language}] {spec.category}: {state}")
        if known:
            self.stdout.write("Só na Meta (fora do catálogo)")
            for template in known.values():
                self.stdout.write(f"  {template}")
