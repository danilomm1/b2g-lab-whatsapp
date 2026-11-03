"""Testes de fumaça da fundação do projeto."""

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.core.services import record_event


def test_system_check_passes() -> None:
    """O check do Django não aponta erros de configuração."""
    call_command("check", fail_level="WARNING")


@pytest.mark.django_db
def test_home_requires_staff_login(client: Client) -> None:
    """Visitante anônimo é mandado para o login do admin."""
    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("admin:login"))


@pytest.mark.django_db
def test_home_renders_for_staff(admin_client: Client) -> None:
    """O painel responde para staff, com Tailwind, HTMX e o aviso de dry-run."""
    response = admin_client.get(reverse("core:home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "B2G Integrations Lab" in content
    assert "css/tailwind.css" in content
    assert "vendor/htmx/htmx.min.js" in content
    assert "dry-run ativo" in content


@pytest.mark.django_db
def test_home_never_shows_env_values(admin_client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """O checklist de integrações mostra só nomes de variáveis, nunca valores."""
    monkeypatch.setenv("META_APP_ID", "valor-que-nao-pode-aparecer")

    response = admin_client.get(reverse("core:home"))

    assert "valor-que-nao-pode-aparecer" not in response.content.decode()


@pytest.mark.django_db
def test_recent_events_partial(admin_client: Client) -> None:
    """O parcial do HTMX lista os eventos mais recentes."""
    record_event("lead.created", summary="Lead de teste")

    response = admin_client.get(reverse("core:recent_events"), headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert b"lead.created" in response.content
    assert b"<html" not in response.content
