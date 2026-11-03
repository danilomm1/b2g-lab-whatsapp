"""Configurações do deploy de validação (EC2 com Gunicorn atrás do Caddy)."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env.str("DJANGO_SECRET_KEY")

# O Caddy termina o TLS e repassa o esquema original
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
