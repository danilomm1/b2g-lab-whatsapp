from django.apps import AppConfig


class CredentialsConfig(AppConfig):
    """Tokens OAuth e Graph de cada plataforma, criptografados em repouso."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.credentials"
    label = "credentials"
    verbose_name = "Credenciais"
