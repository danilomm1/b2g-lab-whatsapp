from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    """Endpoint único de entrada, verificação de assinatura e roteamento."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.webhooks"
    label = "webhooks"
    verbose_name = "Webhooks"

    def ready(self) -> None:
        from . import lab

        lab.register()
