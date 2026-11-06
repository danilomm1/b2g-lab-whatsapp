from typing import Any

from django.apps import AppConfig
from django.conf import settings
from django.utils.autoreload import autoreload_started


def _watch_env_file(sender: Any, **kwargs: Any) -> None:
    """Faz o runserver reiniciar quando o .env muda (ex.: ao colar um token novo)."""
    sender.extra_files.add(settings.BASE_DIR / ".env")


class CoreConfig(AppConfig):
    """Núcleo: contatos, canais, eventos, consentimentos e painel."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Núcleo"

    def ready(self) -> None:
        autoreload_started.connect(_watch_env_file)
