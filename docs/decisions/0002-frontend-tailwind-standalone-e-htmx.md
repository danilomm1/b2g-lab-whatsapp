# ADR 0002: Tailwind pelo CLI standalone e HTMX servido localmente

**Status:** aceito
**Data:** 2026-11-03

## Contexto

O CLAUDE.md prevê Tailwind e HTMX no front. A máquina de desenvolvimento não tem Node.js, e a instância de validação na EC2 é pequena. Queremos evitar npm, node_modules e um build de front separado.

## Decisão

- Tailwind via **django-tailwind-cli**, que baixa o binário standalone do Tailwind (sem Node). Versão fixada em `TAILWIND_CLI_VERSION = "4.3.3"` nos settings.
- Entrada do CSS em `assets/css/tailwind.css`, com `source(none)` e `@source` explícitos para `templates/` e `apps/`. Saída em `static/css/tailwind.css`.
- O binário (`.django_tailwind_cli/`) e o CSS gerado não são versionados. Em desenvolvimento, a tarefa "Tailwind: watch" do VS Code regenera o CSS a cada mudança de template. No deploy, rodar `python manage.py tailwind build` antes do `collectstatic`.
- HTMX **2.0.11** copiado para `static/vendor/htmx/htmx.min.js` (conferido por hash em jsDelivr e unpkg), sem CDN. O pacote **django-htmx** fornece `request.htmx` pelo middleware.
- Classes do Tailwind sempre escritas por extenso nos templates (ex.: o parcial `core/partials/badge.html` tem um ramo por tom), nunca montadas por concatenação, para o scanner do Tailwind encontrá-las.

## Motivos

- Sem Node, o CLI standalone é o caminho oficial do Tailwind. O django-tailwind-cli só precisa do Python e já traz `build`, `watch` e a template tag `{% tailwind_css %}`.
- A versão 4.3.4 saiu um dia antes desta decisão; fixamos a 4.3.3 por estar madura. A linha 4.x do HTMX ainda está marcada como `next` no npm, então ficamos na 2.x estável.
- Servir o HTMX localmente evita dependência de CDN e funciona offline.

## Consequências

- O primeiro `tailwind build` ou `watch` baixa cerca de 110 MB (binário do Windows).
- Atualizar o Tailwind é trocar `TAILWIND_CLI_VERSION`; atualizar o HTMX é substituir o arquivo em `static/vendor/htmx/`.
