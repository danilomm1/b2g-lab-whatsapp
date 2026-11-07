# B2G Integrations Lab

Laboratório de prova de conceito para validar as integrações entre os canais digitais da Brave2Grow (WhatsApp, Instagram, Facebook, Threads, YouTube, voz e email) antes de levá-las ao site de produção brave2grow.com.

Visão completa, regras e roadmap: [CLAUDE.md](CLAUDE.md).

## Requisitos

- Python 3.12+
- Google Chrome
- VS Code com a extensão Python

## Primeira configuração (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
.\.venv\Scripts\python.exe manage.py generate_encryption_key   # cole em FIELD_ENCRYPTION_KEY
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser           # o painel exige login de staff
.\.venv\Scripts\python.exe manage.py tailwind build            # baixa o CLI do Tailwind na 1ª vez
```

No `.env`, preencha também `DJANGO_SECRET_KEY` e `LAB_WEBHOOK_SECRET` (qualquer texto aleatório longo).

## Ao abrir o projeto no VS Code

Três tarefas sobem sozinhas (`.vscode/tasks.json`):

| Tarefa | O que faz |
|---|---|
| Django: runserver 8602 | Servidor em http://localhost:8602 |
| Tailwind: watch | Regenera `static/css/tailwind.css` quando um template muda |
| Chrome: depuração 9997 | Abre o Chrome com depuração remota na porta 9997, com perfil dedicado |

Isso depende de `"task.allowAutomaticTasks": "on"` nas configurações de usuário do VS Code. Detalhes e motivos em [docs/decisions/0001-ambiente-de-desenvolvimento.md](docs/decisions/0001-ambiente-de-desenvolvimento.md).

Outras tarefas (menu Terminal > Run Task): `Huey: consumidor`, `Testes: pytest`, `Qualidade: ruff check`.

Configurações de depuração (aba Run and Debug):

- **Django: depurar no 8602**: roda o servidor com breakpoints. Pare antes a tarefa automática do runserver.
- **Chrome: anexar na 9997**: conecta o depurador do VS Code ao Chrome de testes.

## Comandos úteis

```powershell
.\.venv\Scripts\python.exe manage.py runserver 8602
.\.venv\Scripts\python.exe manage.py run_huey
.\.venv\Scripts\python.exe manage.py tailwind watch
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check . ; .\.venv\Scripts\python.exe -m ruff format .
```

## Automação do Chrome de testes

`scripts/dev/browser.py` se conecta ao Chrome da porta 9997 pelo DevTools Protocol (Playwright `connect_over_cdp`), sem abrir outro navegador. As abas que ele cria são fechadas ao final, e a sessão de login do perfil é reaproveitada.

```powershell
.\.venv\Scripts\python.exe scripts\dev\browser.py tabs                       # abas abertas
.\.venv\Scripts\python.exe scripts\dev\browser.py shot / --full              # screenshot em var\screens
.\.venv\Scripts\python.exe scripts\dev\browser.py shot / --mobile --full     # viewport 390x844
.\.venv\Scripts\python.exe scripts\dev\browser.py text /admin/               # texto visível da página
```

O `shot` também informa rolagem horizontal e erros de console, o que ajuda a pegar quebra de layout no celular.

## Testar a esteira de webhooks

Com o servidor e o consumidor do Huey rodando, o provedor de teste `lab` percorre todo o caminho (assinatura, gravação do bruto, fila, handler, evento) sem depender de nenhuma plataforma:

```powershell
.\.venv\Scripts\python.exe manage.py send_test_webhook                  # vira um evento no painel
.\.venv\Scripts\python.exe manage.py send_test_webhook --bad-signature  # 403, entrega rejeitada
.\.venv\Scripts\python.exe manage.py send_test_webhook --type outra     # entrega ignorada (sem handler)
```

As entregas ficam em Admin > Webhooks, com o payload bruto. Detalhes em [docs/decisions/0003-esteira-de-webhooks.md](docs/decisions/0003-esteira-de-webhooks.md).

## Meta (Graph API e webhooks)

O estado da integração está em [docs/integrations/meta.md](docs/integrations/meta.md), e o passo a passo do painel da Meta, tela por tela (portfólio, cadastro de desenvolvedor, app, usuário do sistema, token e webhook), em [docs/treinamento/configurar-meta-facebook-instagram.md](docs/treinamento/configurar-meta-facebook-instagram.md). No laboratório:

```powershell
.\.venv\Scripts\python.exe manage.py meta_check             # confere token, permissões e ativos
```

Webhooks reais da Meta só chegam no servidor de validação (EC2), nunca na máquina local: não usamos túneis ([ADR 0005](docs/decisions/0005-webhooks-reais-somente-na-ec2.md)). Localmente, os testes simulam eventos assinados. Servidor e deploy (`python deploy.py`) em [docs/deploy/ec2.md](docs/deploy/ec2.md).

## WhatsApp (Cloud API)

Estado, passo a passo do número de teste no painel, travas de envio, mídia, templates, formulários nativos, fluxos e custos em [docs/integrations/whatsapp.md](docs/integrations/whatsapp.md). Contatos são identificados pelo BSUID ([ADR 0006](docs/decisions/0006-identidade-whatsapp-por-bsuid.md)), e os fluxos conversacionais são definidos em código ([ADR 0007](docs/decisions/0007-motor-de-fluxo-do-whatsapp.md)). As conversas ficam em **Conversas**, no topo do painel. O roteiro de testes de ponta a ponta, com o resultado da última rodada, está em [docs/integrations/whatsapp-roteiro-de-testes.md](docs/integrations/whatsapp-roteiro-de-testes.md).

```powershell
.\.venv\Scripts\python.exe manage.py whatsapp_check                               # número, app assinado na WABA e templates
.\.venv\Scripts\python.exe manage.py whatsapp_templates list                        # catálogo comparado com a Meta
.\.venv\Scripts\python.exe manage.py whatsapp_forms list                            # formulários nativos (WhatsApp Flows)
.\.venv\Scripts\python.exe manage.py whatsapp_simulate_reply --contact +55... --text "oi"   # resposta simulada, assinada como a Meta
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --text "Oi"   # simulado enquanto LAB_DRY_RUN=True
```

## Estrutura

```
config/      settings por ambiente (base, dev, prod), urls, wsgi
apps/        um app Django por canal ou responsabilidade
             core: contatos, consentimentos, conversas, mensagens, eventos, travas de segurança, painel
             credentials: tokens criptografados por plataforma
             webhooks: endpoint único, assinatura, deduplicação e fila
             meta_business: Graph API, token do usuário do sistema e webhook da Meta
             whatsapp: Cloud API, recebimento, envio com travas, mídia, templates, formulários e fluxos
assets/      entrada do Tailwind (assets/css/tailwind.css)
templates/   templates compartilhados
static/      arquivos estáticos (htmx em static/vendor; o CSS gerado não é versionado)
docs/        integrações (um .md por canal) e decisões (ADRs)
scripts/     utilitários de desenvolvimento e operação
tests/       testes (pytest, chamadas externas sempre mockadas)
var/         dados locais: SQLite do Django e da fila Huey (não versionado)
```

## Segurança

O laboratório começa com `LAB_DRY_RUN=True`: nenhuma mensagem, publicação, email ou ligação real é feita. Envios reais, quando habilitados, só vão para quem está em `LAB_ALLOWED_RECIPIENTS`.

Essas regras estão centralizadas em `apps/core/safety.py`, que todo app de canal deve usar antes de chamar uma API externa:

- `check_outbound(destinatario, dry_run=...)`: decide entre simular, enviar de verdade ou bloquear (fora da allowlist).
- `check_proactive_contact(contato, canal, finalidade)`: exige consentimento ativo e respeita `LAB_MAX_PROACTIVE_PER_WEEK`, somando todos os canais.
- `is_opt_out_message(texto)` e `apply_opt_out(...)` (em `services.py`): SAIR, PARAR e STOP revogam o consentimento do canal e disparam o sinal `contact_opted_out`.

Tokens salvos no banco são criptografados com `FIELD_ENCRYPTION_KEY` ([ADR 0004](docs/decisions/0004-criptografia-de-credenciais.md)).
