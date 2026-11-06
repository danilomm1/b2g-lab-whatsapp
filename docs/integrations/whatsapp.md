# WhatsApp (Cloud API)

**Versão da API:** Graph API v26.0 (`META_GRAPH_API_VERSION`), a mesma da Fase 1. Os exemplos atuais da documentação do WhatsApp já usam a v27.0, mas a tabela de versões da Graph API ainda não a lista; a troca fica para quando ela aparecer lá.
**Última revisão:** 06/11/2026 (Fase 2 concluída e validada contra a Meta real; aprovação dos dois templates próprios em análise pela Meta)

## O que está configurado

- **Código:** app `apps/whatsapp` com recebimento (webhook), envio com as travas do laboratório, templates, motor de fluxo conversacional, telas de conversa e comandos de conferência.
- **Painel da Meta:** termos da Plataforma do WhatsApp Business aceitos e número de teste criado em 06/11/2026, com uma conta do WhatsApp Business de teste no portfólio. IDs em `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_BUSINESS_ACCOUNT_ID` (local e servidor). Um destinatário de teste cadastrado (celular do Danilo).
- **Webhook:** objeto `whatsapp_business_account` assinado no app com os campos `messages` e `message_template_status_update`, no mesmo callback da Fase 1; o app está inscrito na conta de teste (`subscribed_apps`).
- **Templates:** `b2g_retomar_conversa` e `b2g_confirmacao_reuniao` enviados para análise em 06/11/2026 (pt_BR, utilidade). O `hello_world` da Meta já vem aprovado na conta de teste.
- **Servidor:** em 06/11/2026 ficou com `LAB_DRY_RUN=False` e só o celular do Danilo em `LAB_ALLOWED_RECIPIENTS`, para os testes reais. Voltar ao dry-run quando os testes acabarem.
- **Número comercial:** a conta do portfólio que usa o número comercial é do tipo "Aplicativo WhatsApp Business" e só migra depois da decisão sobre coexistência (CLAUDE.md, 5.6).

## Passo a passo no painel (número de teste)

1. **Número de teste:** no app "B2G Integrations Lab", caso de uso WhatsApp, abrir "Etapa 1. Experimente" e aceitar os termos. A Meta cria uma conta do WhatsApp Business de teste com um número de teste.
2. **IDs:** copiar o "Phone Number ID" para `WHATSAPP_PHONE_NUMBER_ID` e a "Identificação da conta de mensagens" para `WHATSAPP_BUSINESS_ACCOUNT_ID`, no `.env` local e no do servidor (o `deploy.py` só cria o `.env` do servidor na primeira vez).
3. **Destinatário de teste:** em "Destinatário", "Gerenciar lista de números de telefone", cadastrar o celular e confirmar com o código que chega no WhatsApp. O número de teste só envia para até 5 destinatários cadastrados.
4. **Acesso do usuário do sistema:** rodar `meta_check`. Em 06/11/2026 o token já alcançou a conta de teste com as duas permissões do WhatsApp, sem atribuição manual. Se não alcançar, atribuir a conta ao usuário do sistema "B2G Lab API" (Configurações do negócio > Contas do WhatsApp) e, se preciso, gerar token novo.
5. **Webhook:** no painel, a tela de webhooks do WhatsApp fica dentro da "Etapa 2. Configuração da produção", junto com o cadastro do número real. Por isso foi feito pela API:
   - `POST /<APP_ID>/subscriptions` com o token de app, `object=whatsapp_business_account`, o callback da Fase 1 (`https://<domínio do servidor>/webhooks/meta/`), o `META_WEBHOOK_VERIFY_TOKEN` e `fields=messages,message_template_status_update`. A Meta faz o handshake na hora.
   - `POST /<WABA_ID>/subscribed_apps` com o token do usuário do sistema, para a conta entregar os eventos ao app. O `whatsapp_check` confirma.
6. **Primeira conversa:** publicar o código na EC2 (`python deploy.py`), mandar "oi" do celular para o número de teste e acompanhar em `/whatsapp/`.
7. **Envio real:** no servidor, colocar o celular em `LAB_ALLOWED_RECIPIENTS` e desligar `LAB_DRY_RUN` só durante os testes.

O token de acesso que o painel gera na Etapa 1 é temporário e não é usado pelo laboratório.

## Como o laboratório integra

### Recebimento (`apps/whatsapp/webhook.py` e `inbound.py`)

- Handler da rota `whatsapp_business_account` do provedor `meta` (ADR 0003). Campos tratados: `messages` (mensagens recebidas e status de entrega) e `message_template_status_update`; os outros ficam no bruto, registrados no log.
- **Identidade (ADR 0006):** o contato é identificado pelo BSUID (`user_id`). O telefone (`wa_id`) vai para `Contact.phone` quando vem, com o nono dígito para celulares brasileiros antigos. Um contato já existente com o mesmo telefone (ex.: veio do site) é reaproveitado.
- **Mensagens:** cada uma vira `Message` de entrada (idempotente pelo `wamid`), na conversa aberta do contato com aquele número, e atualiza `last_inbound_at`, que controla a janela de 24h. Também vira o evento `whatsapp.message_received` e segue para o motor de fluxo.
- **Tipos:** texto, respostas de botão e de lista (título em `body`, ID em `raw_payload.reply_id`), botão de template (payload em `reply_id`), mídia (legenda), localização, reação e contatos. Os demais ficam com o tipo e o bruto.
- **Palavra de saída:** `SAIR`, `PARAR` ou `STOP` (sozinhas, sem diferenciar maiúsculas, acentos e pontuação) em texto ou botão revogam os consentimentos do WhatsApp, disparam `contact_opted_out`, cancelam o fluxo em andamento e geram a confirmação de saída.
- **Consentimento:** escrever para a Brave2Grow não gera consentimento automático. Ele permite responder dentro da janela, mas contato proativo exige um `Consent` registrado (no fluxo, pelo botão "Quero receber").
- **Status:** `sent`, `delivered`, `read` e `failed` avançam o status da mensagem enviada sem regredir (chegam fora de ordem). Cada notificação, com o bloco `pricing`, fica em `raw_payload.statuses`. Falhas viram o evento `whatsapp.message_failed` com o código de erro.
- **Troca de número ou de BSUID:** as mensagens de sistema atualizam a identidade e geram `whatsapp.identity_changed`.

### Envio (`apps/whatsapp/services.py`)

`send_message` é o único ponto de envio. As travas, nesta ordem:

1. **Destinatário:** `to` com o telefone ou, sem ele, `recipient` com o BSUID.
2. **Template:** se o template tem registro local e não está aprovado, o envio é barrado antes de chamar a Meta.
3. **Janela de 24h:** fora dela, só template; o envio passa a contar como proativo.
4. **Contato proativo:** exige `Consent` ativo para o WhatsApp na finalidade informada e respeita `LAB_MAX_PROACTIVE_PER_WEEK`, somando todos os canais.
5. **Laboratório:** com `LAB_DRY_RUN=True` (padrão) nada sai e a mensagem fica como "Simulada"; envio real só para `LAB_ALLOWED_RECIPIENTS`.

Bloqueios levantam `SendBlocked` e não gravam nada. Erros da API viram `Message` com status "Falhou" e o erro completo. O envio não é repetido depois de um timeout de leitura ou de um erro 5xx, porque a Meta pode ter enviado; só repete em limite de vazão (130429 e os limites da Graph API) ou quando a conexão nem abriu.

Montagem das mensagens (`apps/whatsapp/payloads.py`), com os limites validados antes de chamar a API: texto (até 4096 caracteres), botões de resposta (até 3, título até 20), lista (até 10 linhas, título até 24, descrição até 72) e template.

`mark_as_read` marca a mensagem recebida como lida e pode mostrar "digitando...". Também segue dry-run e allowlist.

### Templates (`templates_catalog.py`, `template_sync.py`)

- **Catálogo versionado:** cada template tem nome, categoria, idioma, texto com variáveis posicionais (`{{1}}`, `{{2}}`), descrição e exemplo de cada variável, rodapé e botões de resposta rápida com o payload que volta no webhook. O catálogo valida nome e variáveis ao carregar.
- **Estado na Meta:** `MessageTemplate` guarda status, categoria (a Meta pode reclassificar), motivo de rejeição e ID. Atualizado pelo `whatsapp_templates sync` e pelo webhook `message_template_status_update`.
- **Envio:** `get_template(nome).build(*variaveis)` monta o template com os parâmetros e os payloads dos botões, e grava em `Message.body` o texto já preenchido.
- **Templates próprios:**

| Nome | Categoria | Uso | Botões (payload) |
|---|---|---|---|
| `b2g_retomar_conversa` | UTILITY | Reabrir a janela com quem já conversou e tem consentimento | Sim, continuar (`retomar_sim`), Agora não (`retomar_nao`) |
| `b2g_confirmacao_reuniao` | UTILITY | Confirmação de presença D-1 (base do F02) | Confirmo, Reagendar, Cancelar (`reuniao_*`) |

### Motor de fluxo (`apps/whatsapp/flows`, ADR 0007)

- **Fluxos em código:** grafos de nós versionados. Tipos de nó: `Say` (mensagem), `Ask` (pergunta por botões, lista ou texto validado), `Branch` (condição), `Call` (serviço interno ou API externa, em savepoint), `Handoff` (passa para humano) e `End`.
- **Estado:** `FlowRun` guarda o fluxo, o nó atual, as respostas e as tentativas. No máximo uma execução aberta por conversa.
- **Envio depois do commit:** o motor decide as respostas dentro da transação do webhook; a tarefa `send_outbox` envia depois do commit, marca a mensagem recebida como lida com "digitando..." e espera `WHATSAPP_FLOW_SEND_DELAY` (1 s) entre mensagens seguidas, porque a Meta não garante a ordem. Um bloqueio interrompe o resto e vira o evento `whatsapp.flow_send_blocked`.
- **Regras:**
  - **Botões com prefixo do nó:** o ID enviado é `no:opcao`. Um botão antigo tocado fora de hora não vale como resposta. Também valem o título digitado (sem acento nem pontuação) e o número da opção.
  - **Respostas inválidas:** duas seguidas levam ao caminho de falha (em geral, o handoff).
  - **MENU** (ou INICIO): recomeça o fluxo e devolve do humano ao robô.
  - **Handoff:** a conversa fica "com humano" e o robô não responde até alguém clicar em "Devolver ao assistente" na tela ou o contato enviar MENU.
  - **Recomeço automático:** depois de um fluxo concluído, o robô não recomeça sozinho por 12 horas (um "obrigado" não reinicia o menu).
  - **Validade:** uma pergunta sem resposta por 24 horas expira, e a próxima mensagem começa de novo.
  - **Botões de template:** fora de fluxo, `retomar_sim` abre o menu, `retomar_nao` responde e encerra, e `reuniao_*` registra `meeting.response` e responde.
  - **Falhas no motor:** viram o evento `whatsapp.flow_error` sem perder a mensagem recebida.
- **Fluxo `boas_vindas`** (`flows/brave2grow.py`):
  1. Saudação pelo nome. No primeiro contato, inclui o aviso de privacidade da seção 13 (com link se `PRIVACY_POLICY_URL` estiver definido) e o lembrete do SAIR, e registra `privacy.notice_shown`.
  2. Menu com 3 botões: Conhecer serviços, Agendar conversa, Falar com o Danilo.
  3. **Serviços:** apresentação e pergunta de novidades. "Quero receber" registra `Consent` de marketing no WhatsApp com o texto aceito e o `wamid` como prova.
  4. **Agendar:** pede o email só se o contato não tem um (validado, gravado se nenhum outro contato o usa), pergunta o período e registra `lead.scheduling_requested` com a etiqueta `lead-whatsapp`. O agendamento com Google Calendar é o F01 (Fase 10).
  5. **Falar com o Danilo:** handoff com o evento `whatsapp.handoff`.

### Telas de teste (`/whatsapp/`)

- **Conversas** (link no topo do painel, só staff): lista as conversas do WhatsApp com a janela de 24h e a marca "com humano".
- **Conversa:** mensagens atualizadas pelo HTMX a cada 5 s, com o status de cada envio e o ID dos botões tocados; o fluxo em andamento com nó atual e respostas; o botão "Devolver ao assistente" durante o handoff.
- **Responder:** texto livre dentro da janela e um botão que manda uma mensagem de teste com três botões (`teste_sim`, `teste_nao`, `teste_talvez`).
- É uma versão só do WhatsApp; a caixa de entrada unificada continua na Fase 8.

### Comandos

```powershell
.\.venv\Scripts\python.exe manage.py whatsapp_check                                  # número, apps assinados na WABA e templates (só leitura)
.\.venv\Scripts\python.exe manage.py whatsapp_templates list                         # catálogo comparado com o estado na Meta
.\.venv\Scripts\python.exe manage.py whatsapp_templates sync                         # atualiza o status (só leitura na Meta)
.\.venv\Scripts\python.exe manage.py whatsapp_templates submit b2g_retomar_conversa  # envia para aprovação
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --text "Oi"      # dentro da janela de 24h
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --template b2g_confirmacao_reuniao --var Ana --var "quinta, às 10h"
```

O `whatsapp_send_test` só envia para um contato que já existe (o que acontece quando ele escreve primeiro) e passa por todas as travas. Para testar template fora da janela, o contato precisa de um `Consent` de WhatsApp. Para os templates próprios, rodar `submit` no servidor, para o status ficar no banco que recebe o webhook.

## Permissões

| Permissão | Uso | No token |
|---|---|---|
| `whatsapp_business_messaging` | Enviar e receber mensagens | sim |
| `whatsapp_business_management` | Número, templates, assinatura da WABA | sim |
| `business_management` | Ativos do portfólio | sim |

## Custos

Regras da página oficial de preços, consultada em 06/11/2026:

- Cobrança por mensagem entregue desde 01/07/2025, conforme a categoria e o país do destinatário. Mensagens recebidas não são cobradas.
- **Templates:** marketing, utilidade e autenticação são cobrados em qualquer momento.
- **Serviço (texto livre dentro da janela):** desde 01/10/2026, cada número tem 1.000 mensagens de serviço grátis por mês; a partir da 1.001ª, são cobradas. Sem forma de pagamento cadastrada, a Meta só entrega dentro da cota grátis.
- **Utilidade dentro da janela:** deixou de ser grátis em 01/10/2026.
- **Janela de ponto de entrada grátis:** quem chega por anúncio de clique para o WhatsApp abre 7 dias sem cobrança.
- **Brasil:** os valores estão na planilha de preços em BRL da Meta, não na página. Faturamento em reais disponível desde 01/07/2026, obrigatório até 30/06/2027. Consultar a planilha antes de qualquer disparo em volume.

Observado nos webhooks de status em 06/11/2026 (bloco `pricing`, modelo `PMP`):

| Mensagem | Categoria | Tipo | Cobrável |
|---|---|---|---|
| Texto e interativas dentro da janela (19) | `service` | `free_customer_service` | não |
| Template `hello_world` dentro da janela | `utility` | `regular` | sim |

Consequência prática: para responder quem escreveu, usar texto ou mensagens interativas; template só quando a janela estiver fechada.

## Pontos a verificar

- **Política de provedores de IA:** a Meta tem uma política específica para "AI Providers" (vigente desde 16/02/2026, atualizada em 12/05/2026), com cobrança de mensagens fora de template para usuários no Brasil. Antes do concierge com Claude (F17), confirmar se o uso da Brave2Grow se enquadra.
- **Política de privacidade:** definir `PRIVACY_POLICY_URL` com o endereço da política da Brave2Grow; sem ele, o aviso do primeiro contato sai sem link.

## O que funcionou

- 06/11/2026: recebimento, envio, templates e fluxos cobertos por testes com payloads da documentação atual (BSUID incluído) e a Graph API mockada.
- 06/11/2026: primeira conversa real. Mensagens do celular cadastrado chegaram na EC2 assinadas: contato com telefone em E.164, identidade pelo BSUID (o número de teste recebe BSUID, com `user_id` e `wa_id` no bloco `contacts` e `from_user_id` na mensagem), conversa no `phone_number_id` com a janela de 24h.
- 06/11/2026: envio real de texto, de mensagem com botões e do template `hello_world`, todos com os status enviada, entregue e lida pelo webhook. O toque no botão voltou como `interactive` com o ID esperado.
- 06/11/2026: fluxo `boas_vindas` validado de ponta a ponta no WhatsApp real, pelo WhatsApp Web no papel de cliente: aviso de privacidade só no primeiro contato, caminho de serviços com consentimento registrado, caminho de agendamento com email inválido e válido e lead registrado, handoff com o robô em silêncio, "Devolver ao assistente" pela tela, MENU, recomeço bloqueado logo depois de concluir, e SAIR com fluxo cancelado, confirmação e consentimento revogado.
- 06/11/2026: templates próprios enviados para análise pela API; ficaram em `PENDING`.

## Limitações encontradas

- A verificação de webhook manda o verify token na URL (como `hub.verify_token` e `hub_verify_token`), e os logs de acesso do Gunicorn e do Caddy gravavam a URL completa. Corrigido em 06/11/2026: o Gunicorn grava só o caminho e o Caddy troca o valor por `REDACTED`. O token foi trocado no mesmo dia; o campo do painel do Messenger ainda mostra o valor antigo.
- A listagem de templates devolve `rejected_reason: "NONE"` quando não há motivo; o laboratório grava vazio.
- A Meta não garante a ordem de mensagens enviadas em sequência; o motor espera 1 s entre elas. Para ordem estrita, seria preciso esperar o `delivered` de cada uma.
- A aprovação de templates não é imediata; até a resposta, o template fica em `PENDING` e o envio é barrado.

## Próximos passos

1. Quando a Meta aprovar, enviar `b2g_confirmacao_reuniao` e validar os botões de template de ponta a ponta.
2. Voltar o servidor para `LAB_DRY_RUN=True` ao fim dos testes.
3. Definir `PRIVACY_POLICY_URL`.
4. Respostas abertas com Claude, sempre com fallback para humano (F17), depois de conferir a política de provedores de IA.
5. Avisar o Danilo no próprio WhatsApp quando houver handoff (Console CEO, Fase 9).
6. Mídia (download e envio), WhatsApp Flows (formulários nativos) e áudio na voz clonada (Fase 7).
7. Decidir a migração do número comercial (coexistência) e trocar `META_GRAPH_API_VERSION` para a v27.0 quando ela constar na tabela de versões.
