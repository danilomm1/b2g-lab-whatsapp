"""Variáveis disponíveis em todos os templates."""

from typing import Any

from django.conf import settings
from django.http import HttpRequest


def lab_flags(request: HttpRequest) -> dict[str, Any]:
    """Expõe o modo dry-run para o aviso fixo no topo das páginas."""
    return {"lab_dry_run": settings.LAB_DRY_RUN}
