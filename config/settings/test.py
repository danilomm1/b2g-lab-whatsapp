"""Configurações dos testes automatizados (pytest)."""

from .base import *  # noqa: F403
from .base import HUEY

SECRET_KEY = "somente-para-testes"
DEBUG = False

# Huey em modo imediato: as tarefas rodam na hora, em memória, sem consumidor
HUEY = {**HUEY, "immediate": True}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Valores fixos para que os testes não dependam do .env local
LAB_DRY_RUN = True
LAB_ALLOWED_RECIPIENTS: list[str] = []
LAB_MAX_PROACTIVE_PER_WEEK = 3
LAB_WEBHOOK_SECRET = "segredo-de-teste"
# Chave gerada só para os testes; não protege nenhum dado real
FIELD_ENCRYPTION_KEY = ["VnKG7mLsQdOeZfRFad5j59yysvi-2lVFWSDV9id07vs="]

# Meta com valores fictícios; toda chamada à Graph API nos testes é mockada (respx)
META_GRAPH_API_VERSION = "v26.0"
META_APP_ID = "1234567890"
META_APP_SECRET = "segredo-do-app-de-teste"
META_SYSTEM_USER_TOKEN = "token-de-teste-do-system-user"
META_WEBHOOK_VERIFY_TOKEN = "verify-token-de-teste"
FACEBOOK_PAGE_ID = "111"
INSTAGRAM_BUSINESS_ACCOUNT_ID = ""
WHATSAPP_BUSINESS_ACCOUNT_ID = "333"
