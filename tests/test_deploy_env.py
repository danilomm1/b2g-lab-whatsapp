"""Testes do deploy.py: .env de produção e pacote enviado ao servidor.

O deploy.py não é versionado (.gitignore); sem ele, estes testes são pulados.
"""

import importlib.util
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

DEPLOY_SCRIPT = Path(__file__).resolve().parents[1] / "deploy.py"
if not DEPLOY_SCRIPT.exists():
    pytest.skip("deploy.py existe só na máquina de quem publica", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("deploy_script", DEPLOY_SCRIPT)
deploy_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy_script)

LOCAL = [
    "# comentário",
    "DJANGO_SECRET_KEY=chave-local",
    "DJANGO_DEBUG=True",
    "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1",
    "FIELD_ENCRYPTION_KEY=chave-fernet-local",
    "LAB_DRY_RUN=False",
    "META_APP_ID=123",
    "META_SYSTEM_USER_TOKEN=token-local",
]


def _parse(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and line[0] != "#")


def test_prod_env_overrides_environment_and_keeps_integrations() -> None:
    env = _parse(deploy_script.build_prod_env("lab.exemplo.com", LOCAL))

    assert env["DJANGO_DEBUG"] == "False"
    assert env["DJANGO_ALLOWED_HOSTS"] == "lab.exemplo.com"
    assert env["DJANGO_CSRF_TRUSTED_ORIGINS"] == "https://lab.exemplo.com"
    assert env["LAB_DRY_RUN"] == "True"
    assert env["META_APP_ID"] == "123"
    assert env["META_SYSTEM_USER_TOKEN"] == "token-local"


def test_prod_env_creates_new_secret_key_but_keeps_encryption_key() -> None:
    env = _parse(deploy_script.build_prod_env("lab.exemplo.com", LOCAL))

    assert env["DJANGO_SECRET_KEY"] != "chave-local"
    assert len(env["DJANGO_SECRET_KEY"]) >= 50
    # Mesma chave: o banco copiado com --replace-db precisa abrir as credenciais
    assert env["FIELD_ENCRYPTION_KEY"] == "chave-fernet-local"


def test_prod_env_adds_missing_keys() -> None:
    env = _parse(deploy_script.build_prod_env("lab.exemplo.com", ["META_APP_ID=1"]))

    assert env["DJANGO_CSRF_TRUSTED_ORIGINS"] == "https://lab.exemplo.com"
    assert "DJANGO_SECRET_KEY" in env


def test_domain_change_only_touches_domain_keys_of_server_env() -> None:
    server = [
        "DJANGO_SECRET_KEY=segredo-do-servidor",
        "DJANGO_ALLOWED_HOSTS=antigo.exemplo.com",
        "DJANGO_CSRF_TRUSTED_ORIGINS=https://antigo.exemplo.com",
        "# comentário",
        "META_SYSTEM_USER_TOKEN=token",
    ]
    text = deploy_script.set_env_values(server, deploy_script.domain_env("lab.exemplo.com"))

    assert _parse(text) == {
        "DJANGO_SECRET_KEY": "segredo-do-servidor",
        "DJANGO_ALLOWED_HOSTS": "lab.exemplo.com",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://lab.exemplo.com",
        "META_SYSTEM_USER_TOKEN": "token",
    }
    assert "# comentário" in text.splitlines()


def test_certificate_is_issued_before_caddy_gets_the_https_part() -> None:
    script = deploy_script.remote_deploy_script("lab.exemplo.com", "admin@exemplo.com")

    issue = script.index("certbot certonly --webroot -w /var/www/acme -d lab.exemplo.com")
    assert "--email admin@exemplo.com" in script
    # Na primeira emissão o Caddy sobe só com a porta 80; a parte HTTPS entra depois
    assert script.index("caddyfile /tmp/b2g-lab-release/deploy/Caddyfile\n") < issue
    assert issue < script.index("deploy/Caddyfile /tmp/b2g-lab-release/deploy/Caddyfile.https")


def test_release_has_lf_scripts_and_generated_css(monkeypatch, tmp_path) -> None:
    css = tmp_path / "static" / "css"
    css.mkdir(parents=True)
    (css / "tailwind.css").write_text("/* css */", encoding="utf-8")
    monkeypatch.setattr(deploy_script, "BASE_DIR", tmp_path)

    def fake_run(args, *, data=None):
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo("deploy/bootstrap.sh")
            content = b"#!/usr/bin/env bash\necho ok\n"
            info.size = len(content)
            tar.addfile(info, BytesIO(content))
        assert "core.autocrlf=false" in args
        return buffer.getvalue()

    monkeypatch.setattr(deploy_script, "run", fake_run)

    with tarfile.open(fileobj=BytesIO(deploy_script.build_release())) as tar:
        names = tar.getnames()
        script = tar.extractfile("deploy/bootstrap.sh").read()

    assert "static/css/tailwind.css" in names
    assert b"\r\n" not in script
