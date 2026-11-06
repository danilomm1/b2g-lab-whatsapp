from django.apps import AppConfig


class WhatsAppConfig(AppConfig):
    """WhatsApp Cloud API: recebimento, envio, templates e fluxos conversacionais."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.whatsapp"
    label = "whatsapp"
    verbose_name = "WhatsApp"

    def ready(self) -> None:
        from .flows import brave2grow  # noqa: F401  registra os fluxos
        from .webhook import register

        register()
