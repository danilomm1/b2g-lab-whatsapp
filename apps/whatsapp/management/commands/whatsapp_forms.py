from django.core.management.base import BaseCommand, CommandError

from apps.meta_business.client import GraphAPIError
from apps.whatsapp.form_sync import create_form, sync_forms
from apps.whatsapp.forms_catalog import FORMS, FormError, get_form
from apps.whatsapp.models import WhatsAppForm


class Command(BaseCommand):
    help = (
        "WhatsApp Flows (formulários nativos): 'list' compara o catálogo com a Meta, 'sync' "
        "atualiza o status (só leitura) e 'create <nome>' cria o Flow na Meta, publicado "
        "(ou em rascunho, com --draft)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("action", choices=["list", "sync", "create"])
        parser.add_argument("name", nargs="?", help="Nome do formulário (para create).")
        parser.add_argument("--draft", action="store_true", help="Cria sem publicar.")

    def handle(self, *args, **options) -> None:
        try:
            if options["action"] == "sync":
                forms = sync_forms()
                self.stdout.write(f"{len(forms)} formulários sincronizados.")
            elif options["action"] == "create":
                if not options["name"]:
                    raise CommandError("Informe o nome do formulário: create <nome>.")
                form = create_form(get_form(options["name"]), publish=not options["draft"])
                self.stdout.write(f"{form.name} criado: {form.status} ({form.meta_id})")
                for error in form.validation_errors:
                    self.stdout.write(self.style.WARNING(f"  {error.get('message', error)}"))
                return
        except (FormError, GraphAPIError) as exc:
            raise CommandError(str(exc)) from exc
        known = {form.name: form for form in WhatsAppForm.objects.all()}
        self.stdout.write("Catálogo")
        for name in FORMS:
            stored = known.pop(name, None)
            state = f"{stored.status} ({stored.meta_id})" if stored else "não criado"
            self.stdout.write(f"  {name}: {state}")
        if known:
            self.stdout.write("Só na Meta (fora do catálogo)")
            for form in known.values():
                self.stdout.write(f"  {form}")
