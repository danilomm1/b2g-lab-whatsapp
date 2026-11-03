"""Conecta no Chrome de depuração do laboratório (porta 9997) pelo DevTools Protocol.

O Chrome é aberto pela tarefa "Chrome: depuração 9997" do VS Code, com perfil dedicado
(ADR 0001). Este utilitário se liga a ele com o Playwright (connect_over_cdp): não abre
outro navegador e não baixa nenhum. As abas que ele cria são fechadas ao final; as abas
já abertas não são tocadas.

Exemplos:
    python scripts/dev/browser.py tabs
    python scripts/dev/browser.py shot / --full
    python scripts/dev/browser.py shot / --mobile --full --out var/screens/painel-mobile.png
    python scripts/dev/browser.py text /admin/
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

DEFAULT_CDP_URL = "http://127.0.0.1:9997"
DEFAULT_BASE_URL = "http://localhost:8602"
SCREENS_DIR = Path(__file__).resolve().parents[2] / "var" / "screens"
DESKTOP = {"width": 1280, "height": 900}
MOBILE = {"width": 390, "height": 844}


@contextmanager
def connect(cdp_url: str) -> Iterator[Browser]:
    """Liga no Chrome já aberto. Ao sair só desconecta; o Chrome continua aberto."""
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
        except PlaywrightError as exc:
            raise SystemExit(
                f"Chrome de depuração não encontrado em {cdp_url}. Abra a pasta no VS Code "
                "(tarefa 'Chrome: depuração 9997') ou rode scripts/dev/chrome_debug.ps1."
            ) from exc
        yield browser


@contextmanager
def new_tab(browser: Browser, viewport: dict[str, int]) -> Iterator[Page]:
    """Abre uma aba no perfil do laboratório (com os cookies de login) e a fecha ao final."""
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    page.set_viewport_size(viewport)
    try:
        yield page
    finally:
        page.close()


def resolve_url(target: str, base_url: str) -> str:
    if target.startswith(("http://", "https://", "file:")):
        return target
    return f"{base_url.rstrip('/')}/{target.lstrip('/')}"


def cmd_tabs(args: argparse.Namespace) -> None:
    with connect(args.cdp) as browser:
        for context in browser.contexts:
            for page in context.pages:
                print(f"{page.title() or '(sem título)'} | {page.url}")


def cmd_shot(args: argparse.Namespace) -> None:
    out = Path(args.out) if args.out else SCREENS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    with connect(args.cdp) as browser, new_tab(browser, MOBILE if args.mobile else DESKTOP) as page:
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        response = page.goto(resolve_url(args.target, args.base_url), wait_until="networkidle")
        page.screenshot(path=str(out), full_page=args.full)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        print(f"URL final: {page.url}")
        print(f"Título: {page.title()}")
        print(f"HTTP: {response.status if response else '-'}")
        print(f"Rolagem horizontal: {overflow}px")
        for error in errors:
            print(f"Erro no console: {error}")
        print(f"Screenshot: {out.resolve()}")


def cmd_text(args: argparse.Namespace) -> None:
    with connect(args.cdp) as browser, new_tab(browser, DESKTOP) as page:
        page.goto(resolve_url(args.target, args.base_url), wait_until="networkidle")
        print(f"URL final: {page.url}\n")
        print(page.inner_text("body"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cdp", default=DEFAULT_CDP_URL, help="Endereço do DevTools do Chrome.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base para caminhos como /.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("tabs", help="Lista as abas abertas.").set_defaults(func=cmd_tabs)

    shot = commands.add_parser("shot", help="Abre uma página em aba nova e tira um screenshot.")
    shot.add_argument("target", help="Caminho (ex.: /admin/) ou URL completa.")
    shot.add_argument("--out", help="Arquivo PNG. Padrão: var/screens/<data-hora>.png")
    shot.add_argument("--mobile", action="store_true", help="Viewport de celular (390x844).")
    shot.add_argument("--full", action="store_true", help="Página inteira, não só a tela.")
    shot.set_defaults(func=cmd_shot)

    text = commands.add_parser("text", help="Abre uma página e imprime o texto visível.")
    text.add_argument("target", help="Caminho (ex.: /admin/) ou URL completa.")
    text.set_defaults(func=cmd_text)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
