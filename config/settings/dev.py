"""Configurações de desenvolvimento local."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
SECRET_KEY = env.str(
    "DJANGO_SECRET_KEY", default="django-insecure-somente-para-desenvolvimento-local"
)
