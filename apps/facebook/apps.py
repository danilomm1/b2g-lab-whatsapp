from django.apps import AppConfig


class FacebookConfig(AppConfig):
    """Página da Brave2Grow: Messenger, comentários e, depois, publicação e insights."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.facebook"
    label = "facebook"
    verbose_name = "Facebook"

    def ready(self) -> None:
        from .webhook import register

        register()
