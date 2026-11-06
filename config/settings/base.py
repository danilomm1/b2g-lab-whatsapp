"""Configurações comuns a todos os ambientes do B2G Integrations Lab."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
VAR_DIR = BASE_DIR / "var"  # dados locais: banco SQLite e fila do Huey

env = environ.Env()
# overwrite: o .env é a fonte da configuração. Sem ele, o processo reiniciado pelo runserver
# herdaria do processo pai os valores antigos e ignoraria o que mudou no arquivo.
environ.Env.read_env(BASE_DIR / ".env", overwrite=True)

DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "huey.contrib.djhuey",
    "django_htmx",
    "django_tailwind_cli",
    "apps.core",
    "apps.credentials",
    "apps.webhooks",
    "apps.meta_business",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.lab_flags",
            ],
        },
    },
]

# SQLite em WAL com transações IMMEDIATE: o runserver e o consumidor do Huey
# escrevem no mesmo arquivo sem esbarrar em "database is locked".
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": VAR_DIR / "db.sqlite3",
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# O painel exige login de staff; o login usa a tela do admin
LOGIN_URL = "admin:login"

# Tailwind via CLI standalone (sem Node). O binário é baixado em .django_tailwind_cli/
# e o CSS gerado vai para static/css/tailwind.css (ADR 0002).
TAILWIND_CLI_VERSION = "4.3.3"
TAILWIND_CLI_SRC_CSS = "assets/css/tailwind.css"

# Fila de tarefas: Huey com SQLite, sem Redis
HUEY = {
    "huey_class": "huey.SqliteHuey",
    "name": "b2g_lab",
    "filename": str(VAR_DIR / "huey.sqlite3"),
    "immediate": False,
}

# Chaves Fernet para criptografar tokens em repouso (ADR 0004). Aceita uma lista
# separada por vírgula: a primeira criptografa, as demais só descriptografam (rotação).
FIELD_ENCRYPTION_KEY = env.list("FIELD_ENCRYPTION_KEY", default=[])

# Segurança operacional do laboratório (CLAUDE.md, seção 8)
LAB_DRY_RUN = env.bool("LAB_DRY_RUN", default=True)
LAB_ALLOWED_RECIPIENTS = env.list("LAB_ALLOWED_RECIPIENTS", default=[])
LAB_MAX_PROACTIVE_PER_WEEK = env.int("LAB_MAX_PROACTIVE_PER_WEEK", default=3)

# Segredo HMAC do provedor de webhook "lab", usado para testar a esteira de entrada
LAB_WEBHOOK_SECRET = env.str("LAB_WEBHOOK_SECRET", default="")

# Meta: Graph API (Facebook, Instagram, WhatsApp). Versão registrada em docs/integrations/meta.md
META_GRAPH_API_VERSION = env.str("META_GRAPH_API_VERSION", default="") or "v26.0"
META_APP_ID = env.str("META_APP_ID", default="")
META_APP_SECRET = env.str("META_APP_SECRET", default="")
META_SYSTEM_USER_TOKEN = env.str("META_SYSTEM_USER_TOKEN", default="")
META_WEBHOOK_VERIFY_TOKEN = env.str("META_WEBHOOK_VERIFY_TOKEN", default="")
FACEBOOK_PAGE_ID = env.str("FACEBOOK_PAGE_ID", default="")
INSTAGRAM_BUSINESS_ACCOUNT_ID = env.str("INSTAGRAM_BUSINESS_ACCOUNT_ID", default="")
WHATSAPP_BUSINESS_ACCOUNT_ID = env.str("WHATSAPP_BUSINESS_ACCOUNT_ID", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # O run_huey instala o próprio handler no logger "huey"; propagar duplicaria cada linha
        "huey": {"propagate": False},
        # O httpx loga a URL de cada requisição em INFO, e ela pode ter tokens na query string
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
