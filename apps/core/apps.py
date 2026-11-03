from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Núcleo: contatos, canais, eventos, consentimentos e painel."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Núcleo"
