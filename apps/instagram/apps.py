from django.apps import AppConfig


class InstagramConfig(AppConfig):
    """Instagram (@brave2grow): Direct, comentários, menções e, depois, publicação e insights."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.instagram"
    label = "instagram"
    verbose_name = "Instagram"

    def ready(self) -> None:
        from .webhook import register

        register()
