"""Testes dos arquivos de deploy versionados: logs do servidor sem segredos da query string."""

import runpy
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"


def test_gunicorn_access_log_has_path_without_query_or_referer() -> None:
    log_format = runpy.run_path(str(DEPLOY_DIR / "gunicorn.conf.py"))["access_log_format"]

    assert "%(U)s" in log_format
    for with_query in ("%(r)s", "%(q)s", "%(f)s"):
        assert with_query not in log_format


def test_web_service_loads_gunicorn_config() -> None:
    service = (DEPLOY_DIR / "systemd" / "b2g-lab-web.service").read_text(encoding="utf-8")

    assert "--config /srv/b2g-lab/app/deploy/gunicorn.conf.py" in service


def test_caddy_access_log_redacts_meta_verify_token() -> None:
    caddyfile = (DEPLOY_DIR / "Caddyfile.https").read_text(encoding="utf-8")

    assert "replace hub.verify_token REDACTED" in caddyfile
    assert "replace hub_verify_token REDACTED" in caddyfile
