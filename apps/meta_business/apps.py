from django.apps import AppConfig


class MetaBusinessConfig(AppConfig):
    """App Meta: webhooks assinados, Graph API e token do System User."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.meta_business"
    label = "meta_business"
    verbose_name = "Meta Business"

    def ready(self) -> None:
        from .webhook import register

        register()
