# CLAUDE.md: B2G Integrations Lab

Este arquivo orienta o Claude (Claude Code no VS Code) sobre o propósito, a arquitetura, as regras e o roadmap deste projeto. Leia-o inteiro antes de qualquer tarefa.

## 1. Visão geral

**Nome do projeto:** B2G Integrations Lab
**Dono:** Danilo (CEO da Brave2Grow)
**Tipo:** laboratório de prova de conceito (PoC), separado do site de produção

O site **brave2grow.com** já possui o gerenciamento interno do funil de vendas. Este projeto NÃO substitui nem altera o site. Ele é um ambiente isolado para explorar, testar e validar todas as integrações possíveis entre os canais digitais da Brave2Grow, para depois levar ao site de produção apenas o que funcionar.

### Objetivos

1. Validar cada integração de forma isolada (um app Django por canal).
2. Criar uma camada de orquestração que una os canais em fluxos de jornada do cliente (ex.: comentário no Instagram vira conversa no WhatsApp, que vira ligação com IA, que vira sequência de email).
3. Construir uma caixa de entrada unificada (unified inbox) e um registro único de contatos e eventos.
4. Documentar limitações, custos, permissões e requisitos de aprovação de cada plataforma.
5. Expor uma ponte (API/webhooks) para que o funil do brave2grow.com possa consumir os resultados no futuro.

### Canais e ativos

| Canal | Ativo | API principal |
|---|---|---|
| Site | https://brave2grow.com | API própria / webhooks (ponte do funil) |
| Meta Business | Business Portfolio da Brave2Grow | Meta Graph API |
| Instagram | https://www.instagram.com/brave2grow/ | Instagram Graph API + Instagram Messaging |
| Facebook | Página da Brave2Grow | Pages API + Messenger Platform |
| Threads | Conta Brave2Grow no Threads | Threads API (graph.threads.net) |
| YouTube | https://www.youtube.com/@brave2grow | YouTube Data API v3 + YouTube Analytics API |
| WhatsApp | Número comercial configurado em `.env` (`WHATSAPP_BUSINESS_NUMBER`) | WhatsApp Cloud API (Meta) |
| Voz | Voz clonada do Danilo no ElevenLabs | ElevenLabs API / Agents Platform + provedor de telefonia (ex.: Twilio) |
| Email | Listas da Brave2Grow | Amazon SES (preferencial, por estar na AWS) |

## 2. Stack técnica

- **Linguagem:** Python 3.12+
- **Framework:** Django 5.x
- **Front:** Django templates + Tailwind CSS (via `django-tailwind` ou CLI standalone do Tailwind) + HTMX para interatividade leve
- **Banco:** SQLite (somente para PoC; manter os models compatíveis com PostgreSQL para migração futura)
- **Filas/tarefas assíncronas:** Huey com backend SQLite (`SqliteHuey`), sem Redis, para manter tudo simples
- **HTTP client:** `httpx`
- **Config/segredos:** `django-environ` + arquivo `.env` (nunca versionado)
- **Testes:** `pytest` + `pytest-django` + `respx` (mock de chamadas HTTP)
- **Qualidade:** `ruff` (lint e format)
- **Túnel local para webhooks:** `cloudflared` ou `ngrok`
- **Deploy de validação:** AWS EC2 (instância t3.micro ou equivalente elegível ao free tier da conta; confirmar elegibilidade no console AWS), Ubuntu, Gunicorn + Caddy (HTTPS automático)

### Por que essas escolhas

- SQLite e Huey com SQLite evitam infraestrutura extra numa instância pequena.
- Webhooks da Meta exigem HTTPS válido; Caddy resolve o certificado sozinho.
- Um app Django por canal mantém cada integração testável e descartável.

## 3. Estrutura do projeto

```
b2g-integrations-lab/
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── manage.py
├── config/                 # settings, urls, wsgi, huey
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   └── urls.py
├── apps/
│   ├── core/               # Contact, Channel, Event, Consent, modelos base, dashboard
│   ├── credentials/        # armazenamento e renovação de tokens OAuth/Graph
│   ├── webhooks/           # endpoint único de entrada, verificação de assinatura, roteamento
│   ├── meta_business/      # app Meta, System User, permissões, Business Portfolio
│   ├── instagram/          # publicação, comentários, DMs, insights
│   ├── facebook/           # posts da página, comentários, Messenger
│   ├── threads/            # publicação, respostas, insights
│   ├── youtube/            # upload, metadados, comentários, analytics
│   ├── whatsapp/           # Cloud API, templates, fluxos conversacionais, WhatsApp Flows
│   ├── voice/              # ElevenLabs, ligações com voz clonada, transcrições
│   ├── email_marketing/    # SES, listas, campanhas, sequências, bounces/complaints
│   ├── orchestrator/       # jornadas multicanal, regras de gatilho, máquina de estados
│   ├── inbox/              # caixa de entrada unificada
│   ├── funnel_bridge/      # ponte com o funil do brave2grow.com
│   ├── scheduling/         # Google Calendar, agendamentos, confirmações, briefings
│   ├── campaigns/          # campanhas, links rastreáveis, QR codes, indicações
│   ├── owner_console/      # comandos do Danilo via WhatsApp (Console CEO)
│   ├── enrichment/         # mapa social consentido dos contatos
│   └── site_builder/       # sites instantâneos e reserva de subdomínios
├── templates/
├── static/
├── docs/
│   ├── integrations/       # um .md por canal: permissões, limites, custos, aprendizados
│   └── decisions/          # ADRs curtos de decisões técnicas
├── scripts/                # utilitários (renovar token, enviar teste, seed)
└── tests/
```

## 4. Modelo de dados central (app `core`)

Toda integração deve gravar no modelo comum, não em estruturas isoladas.

- **Contact:** pessoa única (nome, email, telefone E.164, handles de Instagram/Facebook/Threads/YouTube, origem, tags).
- **ChannelIdentity:** vínculo de um Contact a um identificador em um canal (ex.: `wa_id`, IGSID, PSID, channel ID do YouTube).
- **Consent:** registro de consentimento por canal e finalidade (LGPD): canal, finalidade, data, origem, texto aceito, revogação.
- **Conversation:** conversa por canal, com status e janela de atendimento (ex.: janela de 24h do WhatsApp/Messenger/Instagram).
- **Message:** mensagem de entrada ou saída, com payload bruto (JSON), status de entrega e ID externo.
- **Event:** linha do tempo genérica (comentário, curtida, clique em email, ligação concluída, lead criado etc.).
- **Journey / JourneyStep / JourneyRun:** definição e execução de fluxos multicanal (app `orchestrator`).
- **IntegrationCredential:** tokens, escopos e validade por plataforma (app `credentials`), com tokens criptografados em repouso.

Modelos dos apps de ação (seção 12):

- **Appointment** (`scheduling`): contato, ID do evento no Google Calendar, início, fim, link do Meet, status (`proposed`, `confirmed`, `rescheduled`, `cancelled`, `no_show`, `done`), lembretes enviados, origem (campanha/link).
- **WaitlistEntry** (`scheduling`): contatos aguardando horário liberado.
- **MeetingBrief** (`scheduling`): dossiê gerado antes de uma reunião e notas pós-reunião.
- **Campaign** (`campaigns`): nome, objetivo, período, jornada vinculada, metas.
- **TrackedLink** (`campaigns`): código curto único, campanha, canal, contato (opcional, para links individuais), URL de destino, UTMs, texto pré-preenchido do wa.me.
- **LinkClick** (`campaigns`): clique com timestamp, hash de IP, user agent, canal de origem.
- **Referral** (`campaigns`): quem indicou, quem foi indicado, link usado, status, recompensa.
- **OwnerCommand** (`owner_console`): texto original, intenção interpretada, argumentos, exige confirmação, status, resultado.
- **SocialProfileMatch** (`enrichment`): contato, plataforma, handle, fonte (`self_declared`, `interaction`, `business_discovery`, `oauth_login`), confiança, confirmado pelo contato, data, consentimento vinculado.
- **SiteProject** (`site_builder`): solicitante, dados do negócio (JSON), status (`draft`, `preview`, `published`, `archived`), versão do conteúdo gerado.
- **ReservedSubdomain** (`site_builder`): slug único, projeto, reservado até, status.
- **DomainQuote** (`site_builder`): domínio próprio consultado, disponibilidade, preço, aprovação explícita (nunca compra automática).

Regras:
- Sempre salvar o payload bruto recebido de webhooks (`raw_payload` JSON) para depuração.
- Telefones sempre em E.164 (`+5511...`).
- IDs externos com `unique` por canal para garantir idempotência.

## 5. Integrações: escopo e notas de cada canal

### 5.1 Meta Business (base para Instagram, Facebook, Threads e WhatsApp)
- Criar app do tipo Business em developers.facebook.com, vinculado ao Business Portfolio da Brave2Grow.
- Usar **System User** com token de longa duração para chamadas servidor a servidor; tokens de usuário apenas para testes.
- Concluir a **verificação da empresa** no Meta Business Suite (necessária para produção do WhatsApp e permissões avançadas).
- Permissões precisam passar por **App Review** para uso fora do modo de desenvolvimento. Documentar cada permissão solicitada em `docs/integrations/meta.md`.
- Verificar a assinatura `X-Hub-Signature-256` em todo webhook recebido.

### 5.2 Instagram (@brave2grow)
- A conta precisa ser **profissional (Business ou Creator)** e vinculada à Página do Facebook.
- Explorar: publicação de imagem, carrossel e Reels; leitura e resposta de comentários; DMs via Instagram Messaging; insights de mídia e conta; webhooks de comentários, menções e mensagens.
- Caso de uso alvo: comentário com palavra-chave dispara DM automática com link ou convite para o WhatsApp.

### 5.3 Facebook (Página)
- Publicação de posts, leitura e resposta de comentários, Messenger com respostas automáticas, insights da página.
- Mesmo endpoint de webhook do app Meta, roteado pelo campo `object`.

### 5.4 Threads
- Threads API: publicação de texto, imagem, vídeo e carrossel; respostas; gestão de replies; insights.
- Fluxo de publicação em dois passos (criar container de mídia, depois publicar). Respeitar limites diários de publicação.

### 5.5 YouTube (@brave2grow)
- OAuth 2.0 via Google Cloud Console (projeto próprio, tela de consentimento configurada).
- Explorar: upload de vídeos e Shorts, atualização de título/descrição/tags/thumbnail, leitura e resposta de comentários, playlists, YouTube Analytics.
- Atenção à **cota diária** da YouTube Data API (upload consome muito). Registrar consumo de cota por chamada.

### 5.6 WhatsApp (fluxo de conversa automatizado)
- WhatsApp Cloud API. Começar SEMPRE com o **número de teste** fornecido pela Meta.
- O número comercial definitivo fica em `.env`. Antes de migrá-lo, verificar no painel da Meta as opções atuais (registro exclusivo na API ou coexistência com o app WhatsApp Business), pois um número registrado na API pode deixar de funcionar no app comum.
- Explorar: mensagens de texto, mídia, botões e listas interativas; **templates** aprovados (marketing, utilidade, autenticação); **WhatsApp Flows** (formulários nativos); status de entrega e leitura; janela de atendimento de 24h.
- Construir um **motor de fluxo conversacional** (máquina de estados com nós: mensagem, pergunta, condição, chamada de API, handoff humano).
- Integração opcional com LLM (Claude via API Anthropic) para respostas abertas, sempre com fallback para humano.
- O catálogo completo de ações e fluxos do WhatsApp conectados ao ecossistema está na **seção 12**.
- Custos: cobrança da Meta por categoria de mensagem; o modelo de preços mudou várias vezes. Consultar a página oficial de preços antes de qualquer disparo em volume e registrar em `docs/integrations/whatsapp.md`.

### 5.7 Voz (ligações com voz clonada no ElevenLabs)
- Usar a voz clonada do próprio Danilo (já existente na conta ElevenLabs).
- Explorar: geração de áudio (TTS) para mensagens de voz no WhatsApp; agentes de voz conversacionais do ElevenLabs conectados a um provedor de telefonia (ex.: Twilio) para ligações de saída e entrada; transcrição e resumo das ligações gravados em `Event`.
- Explorar também a **API de chamadas do WhatsApp Business** (se disponível para a conta) como alternativa à telefonia tradicional.
- **Regra obrigatória:** toda ligação deve começar informando que quem fala é uma inteligência artificial em nome da Brave2Grow, antes de qualquer outro conteúdo. Essa frase de abertura é fixa e não pode ser removida por configuração.
- Ligar apenas para contatos com `Consent` ativo para o canal voz. Respeitar horários comerciais e a lista de bloqueio de telemarketing aplicável (ex.: "Não Me Perturbe"). Validar requisitos atuais da Anatel e LGPD antes de qualquer teste com terceiros.

### 5.8 Email marketing
- Amazon SES (sandbox primeiro; pedir saída do sandbox apenas após validar).
- Configurar SPF, DKIM e DMARC no domínio brave2grow.com antes de enviar.
- Explorar: envio transacional, campanhas, sequências (drip) acionadas pelo `orchestrator`, rastreamento de abertura e clique, tratamento de bounces e complaints via SNS, link de descadastro obrigatório.
- Double opt-in para novas inscrições.

### 5.9 Ponte com o funil do brave2grow.com (app `funnel_bridge`)
- Este projeto NÃO escreve diretamente no banco do site.
- Comunicação somente por API REST e webhooks assinados (HMAC) entre os dois sistemas.
- Eventos enviados ao site: lead criado, lead qualificado, conversa iniciada, ligação concluída, inscrição em email.
- Eventos recebidos do site: novo lead no funil, mudança de etapa, compra.
- Em modo de desenvolvimento, usar um mock do site (`funnel_bridge/mock.py`).

## 6. Exemplos de jornadas a validar

1. **Comentário vira conversa:** comentário com palavra-chave no Instagram, DM automática, convite para o WhatsApp, fluxo de qualificação, lead enviado ao funil.
2. **Conteúdo multicanal:** um vídeo publicado no YouTube gera posts adaptados para Instagram (Reels), Facebook e Threads, com agendamento.
3. **Lead quente com ligação:** lead qualificado no WhatsApp que aceitou ser contatado recebe ligação com a voz clonada (com aviso de IA), e o resumo da ligação volta como evento.
4. **Nutrição por email:** inscrição com double opt-in inicia sequência de emails; clique em link específico dispara mensagem de utilidade no WhatsApp (se houver consentimento).
5. **Caixa de entrada unificada:** todas as mensagens de Instagram, Facebook, WhatsApp e respostas de email aparecem em uma única tela com histórico do contato.

## 7. Roadmap por fases

- **Fase 0: Fundação.** Projeto Django, settings por ambiente, Tailwind, Huey, app `core`, `webhooks`, `credentials`, dashboard básico, testes rodando.
- **Fase 1: Meta base.** App Meta, System User, verificação de webhook, roteamento por `object`.
- **Fase 2: WhatsApp.** Número de teste, envio e recebimento, templates, motor de fluxo conversacional.
- **Fase 3: Instagram e Facebook.** Comentários, DMs, Messenger, publicação.
- **Fase 4: Threads.** Publicação e respostas.
- **Fase 5: YouTube.** OAuth, upload, comentários, analytics.
- **Fase 6: Email.** SES sandbox, DNS, sequências, bounces.
- **Fase 7: Voz.** TTS com voz clonada, agente de voz, ligação de teste para o próprio número do Danilo.
- **Fase 8: Orquestração.** Jornadas multicanal e caixa de entrada unificada.
- **Fase 9: Console CEO.** Comandos do Danilo via WhatsApp, confirmação por botões e PIN (seção 12.1).
- **Fase 10: Agenda.** Google Calendar, agendamento conversacional, confirmação em cascata, lista de espera, briefings (F01 a F05).
- **Fase 11: Campanhas e atribuição.** Links rastreáveis, deep links wa.me com código, QR codes, indicações (F07 a F11).
- **Fase 12: Conteúdo a partir do WhatsApp.** Áudio vira conteúdo multicanal com aprovação por botões (F12 a F14).
- **Fase 13: Site instantâneo.** Comando `/site`, reserva de subdomínio, geração e publicação (F15).
- **Fase 14: Mapa social consentido.** Enriquecimento de perfis dentro das regras da seção 13 (F06).
- **Fase 15: Ponte com o funil.** API e webhooks com brave2grow.com (mock primeiro).
- **Fase 16: Deploy de validação na EC2.** Gunicorn, Caddy (incluindo TLS para subdomínios de sites), Huey como serviço systemd, backups do SQLite.

Ao concluir cada fase, atualizar o arquivo correspondente em `docs/integrations/` com: o que funcionou, limitações, permissões necessárias, custos observados e próximos passos.

## 8. Regras para o Claude ao trabalhar neste projeto

### Segurança e segredos
- Nunca escrever tokens, chaves, senhas ou números de telefone reais no código ou em commits. Tudo vem do `.env`.
- Manter `.env.example` sempre atualizado com as variáveis necessárias (sem valores reais).
- Criptografar tokens salvos em `IntegrationCredential`.
- Validar assinatura de todo webhook recebido (Meta: `X-Hub-Signature-256`; Twilio, ElevenLabs, SNS e site: conforme cada provedor).

### Segurança operacional (ações com efeito no mundo real)
- Toda função que publica, envia mensagem, envia email ou faz ligação deve ter parâmetro `dry_run` e respeitar a flag global `LAB_DRY_RUN=True` por padrão.
- Envios reais só para destinatários na allowlist `LAB_ALLOWED_RECIPIENTS` enquanto estiver em modo laboratório.
- Nunca disparar envios em massa sem pedido explícito do Danilo.
- Verificar `Consent` antes de qualquer contato ativo (mensagem iniciada pela empresa, email de marketing, ligação).
- Respeitar a palavra de saída (`SAIR`, `PARAR`, `STOP`) em qualquer ponto de qualquer fluxo: ela revoga o consentimento do canal e encerra jornadas ativas na hora.
- Limite de frequência por contato (`LAB_MAX_PROACTIVE_PER_WEEK`) para mensagens iniciadas pela empresa, somando todos os canais.

### Console CEO (comandos do dono)
- Comandos só são aceitos de números listados em `OWNER_WHATSAPP_NUMBERS`.
- Comandos com efeito externo (publicar, disparar campanha, ligar, publicar site, consultar ou reservar domínio pago) exigem botão de confirmação; comandos sensíveis exigem também o `OWNER_COMMAND_PIN`.
- Compra de domínio próprio fica desativada (`DOMAIN_PURCHASE_ENABLED=False`) e, mesmo ativada, nunca acontece sem aprovação explícita com preço exibido.
- Todo comando gera um `OwnerCommand` auditável.

### Código
- Um app Django por canal; lógica de API em `services.py` ou `client.py`, nunca nas views.
- Views de webhook devem responder rápido (HTTP 200) e delegar o processamento para tarefas Huey.
- Processamento idempotente: deduplicar por ID externo.
- Tratar rate limits com retry exponencial e registrar respostas de erro completas.
- Type hints em todo código novo; docstrings curtas em português.
- Testes com chamadas externas sempre mockadas (`respx`); nenhum teste pode chamar APIs reais.
- Commits pequenos e descritivos em português.

### Documentação e linguagem
- Comunicação, docs e comentários em português do Brasil; nomes de código (variáveis, funções, classes) em inglês.
- Não usar travessões nos textos; preferir vírgulas, dois pontos ou frases separadas.
- Antes de implementar uma integração, consultar a documentação oficial atual da plataforma, pois versões de API, permissões e preços mudam com frequência. Registrar a versão da API usada (ex.: versão do Graph API) em `settings` e nos docs.

## 9. Comandos úteis

```bash
# ambiente
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# banco e servidor
python manage.py migrate
python manage.py runserver

# tailwind (modo watch)
python manage.py tailwind watch

# fila de tarefas
python manage.py run_huey

# testes e qualidade
pytest
ruff check . && ruff format .

# túnel para webhooks locais
cloudflared tunnel --url http://localhost:8000
```

## 10. Variáveis de ambiente previstas (`.env.example`)

```
DJANGO_SECRET_KEY=
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
FIELD_ENCRYPTION_KEY=

LAB_DRY_RUN=True
LAB_ALLOWED_RECIPIENTS=

META_APP_ID=
META_APP_SECRET=
META_SYSTEM_USER_TOKEN=
META_WEBHOOK_VERIFY_TOKEN=
META_GRAPH_API_VERSION=
FACEBOOK_PAGE_ID=
INSTAGRAM_BUSINESS_ACCOUNT_ID=
THREADS_USER_ID=
THREADS_ACCESS_TOKEN=

WHATSAPP_BUSINESS_ACCOUNT_ID=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_BUSINESS_NUMBER=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
YOUTUBE_CHANNEL_ID=

ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_AGENT_ID=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=

AWS_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
SES_FROM_EMAIL=

ANTHROPIC_API_KEY=

OWNER_WHATSAPP_NUMBERS=
OWNER_COMMAND_PIN=
LAB_MAX_PROACTIVE_PER_WEEK=3

GOOGLE_CALENDAR_ID=
GOOGLE_CALENDAR_TIMEZONE=America/Sao_Paulo
SCHEDULING_BUSINESS_HOURS=09:00-18:00
SCHEDULING_DEFAULT_DURATION_MIN=30

SHORTLINK_BASE_URL=https://go.brave2grow.com
SITES_BASE_DOMAIN=sites.brave2grow.com
SUBDOMAIN_RESERVATION_HOURS=72
ROUTE53_HOSTED_ZONE_ID=
DOMAIN_PURCHASE_ENABLED=False

FUNNEL_BRIDGE_BASE_URL=
FUNNEL_BRIDGE_HMAC_SECRET=
```

## 11. Fora de escopo (por enquanto)

- Alterar o código ou o banco do site brave2grow.com.
- Uso de bibliotecas não oficiais que automatizam o WhatsApp pessoal (risco de banimento do número).
- Disparos em massa para contatos sem consentimento registrado.
- Alta disponibilidade, escalabilidade ou banco de produção (o laboratório roda em SQLite e uma única instância).
- Scraping de perfis em redes sociais, busca de pessoas por telefone ou email fora das APIs oficiais, ou qualquer enriquecimento que viole a seção 13.
- Compra automática de domínios.

## 12. Catálogo de ações e fluxos do WhatsApp

O WhatsApp é o **centro de comando** do ecossistema: para os contatos, é o canal de conversa; para o Danilo, é o painel de controle de tudo (agenda, campanhas, conteúdo, sites). Cada fluxo abaixo tem um código (F01, F02...) para ser referenciado em issues, commits e docs.

### Blocos técnicos reutilizáveis

Todos os fluxos são montados com estes blocos do motor conversacional (app `whatsapp`):

- **Mensagens interativas:** botões de resposta (até 3), listas (até 10 itens), botões de URL e de ligação.
- **WhatsApp Flows:** formulários nativos com telas, campos, seletor de data e validação (ideal para agendamento, briefing de site e cadastro).
- **Templates aprovados:** obrigatórios para qualquer mensagem fora da janela de 24h (lembretes, confirmações e campanhas). Manter o catálogo de templates em `apps/whatsapp/templates_catalog.py` com categoria, idioma, variáveis e status de aprovação.
- **Áudio na voz clonada:** TTS do ElevenLabs enviado como mensagem de voz.
- **Códigos de atribuição:** texto pré-preenchido no link wa.me com código `[B2G-XXXXX]`, detectado na primeira mensagem para iniciar o fluxo certo.
- **Interpretação de linguagem natural:** Claude converte texto livre em intenção + argumentos (ex.: "marca uma call com a Ana quinta à tarde" vira `/agendar`), sempre mostrando o entendimento antes de executar.
- **Handoff humano:** qualquer fluxo pode transferir para o Danilo com resumo do contexto.

### 12.1 Console CEO (comandos do Danilo pelo WhatsApp)

| Comando | O que faz |
|---|---|
| `/hoje` | Agenda do dia, leads quentes, mensagens pendentes, métricas rápidas |
| `/briefing <nome ou reunião>` | Dossiê do contato ou dos participantes da reunião (F04) |
| `/agendar <pessoa> <quando>` | Propõe horários livres à pessoa e cria o evento (F01) |
| `/quem <nome, telefone ou @>` | Visão 360 do contato com todas as interações e perfis vinculados |
| `/leads [hoje\|semana\|quentes]` | Lista de leads com pontuação e próxima ação sugerida |
| `/campanha nova` | Assistente para criar campanha com links rastreáveis (F07) |
| `/campanha <código>` | Desempenho da campanha: cliques, conversas, agendamentos, vendas |
| `/post` (ou enviar um áudio) | Transforma a ideia em conteúdo para todos os canais (F12) |
| `/site nova` | Cria um site instantâneo com subdomínio reservado (F15) |
| `/ligar <contato>` | Agenda uma ligação com o agente de voz (F16), se houver consentimento |
| `/relatorio [semana\|mes]` | Relatório do ecossistema com gráficos em imagem |
| `/pausar <jornada>` e `/retomar <jornada>` | Controle das automações ativas |
| `/ajuda` | Lista de comandos com exemplos |

### 12.2 Agenda e relacionamento

**F01: Agendamento conversacional inteligente**
- Gatilho: contato pede para agendar, clica em link de agendamento, ou Danilo usa `/agendar`.
- Passos: consulta horários livres no Google Calendar (freebusy) respeitando `SCHEDULING_BUSINESS_HOURS`; oferece 3 opções em lista (ou WhatsApp Flow com seletor de data); cria o evento com link do Meet e convida o email do contato; envia confirmação com resumo e arquivo .ics; registra `Appointment` e `Event`.
- Diferencial: os horários oferecidos priorizam o perfil do lead (lead quente recebe os horários mais próximos; contato de outro fuso recebe horários convertidos).

**F02: Confirmação de presença em cascata**
- D-1: template de utilidade com botões **Confirmo**, **Reagendar**, **Cancelar**.
- H-2: lembrete em áudio curto na voz clonada do Danilo ("Oi Ana, aqui é a IA do Danilo, só lembrando...").
- Sem resposta em H-1: ligação curta do agente de voz para confirmar (somente com consentimento de voz).
- Reagendar abre o F01 já filtrado; Cancelar libera o horário e aciona a **lista de espera**: o primeiro da fila recebe o horário com botão de aceite, e o próximo só recebe se ninguém aceitar em 30 minutos.
- O status de presença atualiza o evento no Google Calendar e a etapa no funil.

**F03: Recuperação de no-show**
- Se a reunião é marcada como `no_show` (por botão do Danilo após o horário), o contato recebe mensagem empática com dois caminhos: reagendar agora (F01) ou receber um conteúdo resumido gravado em áudio pela voz clonada.
- Dois no-shows seguidos movem o contato para uma jornada de nutrição em vez de nova tentativa de reunião.

**F04: Varredura da agenda e briefing pré-reunião**
- Tarefa diária às 7h: lê os eventos do dia, identifica participantes externos e cruza com `Contact` por email e telefone.
- 60 minutos antes de cada reunião, o Danilo recebe no WhatsApp: quem é, etapa no funil, origem do lead, últimas interações em cada canal (comentários, DMs, emails abertos, vídeos assistidos quando disponível), resumo de ligações anteriores, perfis sociais vinculados (F06) e 3 sugestões de abertura de conversa geradas pelo Claude.
- Pós-reunião: botão **Como foi?**; o Danilo responde com áudio, que é transcrito e vira notas, próximos passos, tarefa de follow-up e rascunho de mensagem para o contato, aprovado com um toque.

**F05: Ritual semanal de relacionamento**
- Toda segunda: lista de 5 contatos importantes sem interação recente (clientes, parceiros, leads quentes), com motivo sugerido para contato (aniversário de cliente, novo vídeo sobre tema de interesse, marco da empresa dele) e mensagem pronta para enviar ou ajustar.

**F06: Mapa social consentido dos contatos**
- Objetivo: saber em quais plataformas cada contato da agenda se relaciona com a Brave2Grow, para personalizar abordagem e conteúdo.
- Fontes permitidas (detalhes na seção 13): autodeclaração no fluxo ("Qual seu @ no Instagram? Vou te marcar no material"), vínculo por interação (quem comenta ou manda DM nas contas da Brave2Grow é associado e o contato confirma pelo WhatsApp com "Esse @ é você?"), Business Discovery do Instagram para contas comerciais cujo @ já é conhecido, e login social no site.
- Resultado: visão de conexões cruzadas por contato, segmentos como "segue no Instagram e não está inscrito no YouTube", e convites personalizados para o canal que falta.

### 12.3 Campanhas e atribuição

**F07: Campanha com link específico**
- Criação por `/campanha nova`: nome, objetivo, oferta, jornada, canais.
- O sistema gera: links curtos por canal (`go.brave2grow.com/c/<codigo>`), links individuais por contato quando a campanha é segmentada, UTMs padronizados e um deep link wa.me com texto pré-preenchido contendo o código.
- Quando o contato chega pelo link, o código identifica a campanha e inicia a jornada específica (ex.: entrega de material, diagnóstico rápido, agendamento).
- Clique de um lead quente em link individual gera alerta para o Danilo em tempo real com botão **Chamar agora**.
- Painel por campanha: cliques, conversas iniciadas, agendamentos, presença, vendas, custo das mensagens.

**F08: QR code de evento e palestra**
- Cada evento tem um QR que abre o WhatsApp com código do evento.
- Fluxo: check-in com confirmação de presença, entrega imediata do material, enquete durante a palestra (botões), NPS ao final, convite para a próxima etapa (agendamento ou oferta), e publicação automática de agradecimento nas redes com aprovação do Danilo.

**F09: Programa de indicação com link pessoal**
- Cada contato engajado recebe seu link de indicação.
- Cada indicado que chega pelo link é atribuído; o indicador recebe atualizações ("2 pessoas que você indicou já agendaram") e recompensas por marcos.
- Ranking mensal opcional dos maiores indicadores, com mensagem de reconhecimento.

**F10: Reativação inteligente**
- Segmenta contatos com consentimento e sem interação há X dias.
- A mensagem usa o último interesse registrado (vídeo assistido, material baixado, tema da conversa) como gancho, e oferece um único próximo passo.
- Respeita `LAB_MAX_PROACTIVE_PER_WEEK` e pausa automaticamente quem não responder a duas tentativas.

**F11: Lançamento em contagem regressiva**
- Lista de espera via WhatsApp com código de campanha.
- Sequência D-7 a D0 orquestrada entre WhatsApp, email, Stories e Threads.
- Lembrete de live no YouTube com link direto, envio do replay para quem não assistiu, oferta com prazo para quem assistiu.

### 12.4 Conteúdo a partir do WhatsApp

**F12: Áudio vira conteúdo em todos os canais**
- O Danilo envia um áudio ou texto com uma ideia.
- Pipeline: transcrição, Claude gera roteiro de Reels, post do Threads, post do Facebook, legenda do Instagram, descrição e tags para YouTube e uma newsletter curta.
- Preview no WhatsApp com botões **Aprovar tudo**, **Editar**, **Agendar** por canal; publicação pelos apps de cada canal.

**F13: Escuta social com resposta em um toque**
- Comentários, menções e DMs com alta intenção (palavras como preço, como funciona, quero) geram alerta para o Danilo com 2 respostas sugeridas em botões.
- Um toque responde no canal original e, se fizer sentido, convida a pessoa para o WhatsApp com código de atribuição.

**F14: Novidades sob demanda**
- Contatos escolhem por botão quais temas querem receber (lista de interesses).
- Novo vídeo no YouTube sobre um tema dispara aviso apenas para quem optou por aquele tema, com trecho em áudio na voz clonada.

### 12.5 Site instantâneo pelo WhatsApp

**F15: Comando `/site`**
- Pode ser usado pelo Danilo (para si ou para um cliente) e, numa versão futura, oferecido como produto da Brave2Grow ("seu site em 5 minutos pelo WhatsApp").
- Passos:
  1. WhatsApp Flow coleta: nome do negócio, nicho, público, oferta principal, tom de voz, cores, fotos (enviadas como mídia), WhatsApp e Instagram do negócio.
  2. O sistema sugere 3 slugs e verifica disponibilidade; o escolhido vira `ReservedSubdomain` (ex.: `cafedaana.sites.brave2grow.com`) reservado por `SUBDOMAIN_RESERVATION_HOURS`.
  3. Claude gera o conteúdo (headline, seções, prova social, FAQ, chamada para ação) aplicado a um template Tailwind do `site_builder`.
  4. Link de preview com botões **Publicar**, **Ajustar** (por texto ou áudio) e **Trocar estilo**.
  5. Publicação: roteamento multi-tenant pelo cabeçalho Host; DNS curinga `*.sites.brave2grow.com` no Route 53; Caddy com TLS sob demanda, autorizando só subdomínios reservados.
  6. O site publicado já nasce integrado: botão de WhatsApp com código de atribuição do próprio site, formulário que cria `Contact`, e todos os leads entram no ecossistema.
- Domínio próprio (opcional): consulta de disponibilidade e preço via Route 53 Domains, registrada em `DomainQuote`, exibida ao Danilo; compra somente com `DOMAIN_PURCHASE_ENABLED=True`, botão de confirmação e PIN.
- Alternativa sem DNS para a fase inicial: publicar em `brave2grow.com/s/<slug>` via ponte com o site principal.

### 12.6 Voz e IA

**F16: Ligação de qualificação ou confirmação com voz clonada**
- Gatilho: botão **Pode me ligar?** no WhatsApp, `/ligar` do Danilo ou etapa do F02.
- A ligação sempre abre com o aviso fixo de que é uma inteligência artificial em nome da Brave2Grow.
- Ao final, transcrição e resumo voltam como `Event`, e o Danilo recebe o resumo no WhatsApp com próxima ação sugerida.

**F17: Concierge IA 24/7 com base de conhecimento**
- Claude responde dúvidas usando conteúdo da Brave2Grow (transcrições do YouTube, páginas do site, materiais) como base.
- Quando a confiança é baixa ou o assunto é comercial sensível, transfere para o Danilo com resumo e sugestão de resposta.

### 12.7 Inteligência do ecossistema

**F18: Resumo diário e semanal**
- 7h: agenda, leads novos, campanhas, menções, métricas de cada canal e 3 ações recomendadas em botões.
- Sexta: relatório semanal em imagem (gráficos) com o que cresceu, o que caiu e o porquê provável.

**F19: Pontuação multicanal de leads**
- Cada evento soma pontos (abrir email, comentar, clicar em link individual, assistir live, responder no WhatsApp).
- Ao cruzar o limite, alerta para o Danilo com a ação ideal (ligar, agendar, enviar proposta) pronta para executar.

### 12.8 Jornadas assinatura (combinações de fluxos)

- **Do comentário ao contrato:** F13 (comentário com intenção) → convite com código para o WhatsApp → F17 (concierge qualifica) → F01 (agendamento) → F02 (confirmação em cascata) → F04 (briefing) → reunião → F12 em versão follow-up (resumo em áudio para o cliente) → funil.
- **Do palco à mentoria:** F08 (QR no evento) → material + NPS → F14 (temas de interesse) → F11 (lançamento) → F16 (ligação para quem demonstrou interesse e consentiu).
- **Do site ao ecossistema:** F15 (cliente cria site pelo WhatsApp) → leads do site entram no funil → cliente recebe relatório semanal do próprio site (F18 versão cliente) → upsell de serviços da Brave2Grow.

## 13. Regras de privacidade para enriquecimento e varredura de agenda

O mapa social (F06) e a varredura da agenda (F04) lidam com dados pessoais de terceiros. Regras obrigatórias:

- **Somente APIs oficiais e fontes legítimas.** As APIs da Meta não permitem localizar perfis de pessoas por telefone ou email, e scraping viola os termos das plataformas. Não implementar nenhuma forma de busca não oficial.
- **Fontes permitidas:** autodeclaração do próprio contato, interações com as contas oficiais da Brave2Grow (comentários, DMs, menções), Business Discovery para contas comerciais cujo @ já é conhecido, e login social feito pelo próprio contato no site.
- **Confirmação do contato:** vínculos inferidos por interação ficam com `confirmed_by_contact=False` até a pessoa confirmar.
- **Transparência e base legal (LGPD):** informar no primeiro contato que a Brave2Grow conecta as interações nos seus canais para personalizar o atendimento, com link para a política de privacidade.
- **Direitos do titular:** comando `MEUS DADOS` mostra o que está registrado sobre o contato, e `APAGAR MEUS DADOS` inicia a exclusão (com confirmação), removendo também vínculos em `SocialProfileMatch`.
- **Minimização:** guardar só o necessário (handle, fonte, data, confiança), nunca conteúdo privado de terceiros.
- **Agenda:** a varredura lê apenas o calendário configurado em `GOOGLE_CALENDAR_ID`; dados dos participantes servem só para o briefing interno do Danilo e não disparam contatos automáticos sem consentimento.
