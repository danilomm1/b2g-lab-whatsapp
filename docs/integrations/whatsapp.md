# WhatsApp (Cloud API)

**Versão da API:** Graph API v27.0 (`META_GRAPH_API_VERSION`), a versão dos exemplos atuais da documentação do WhatsApp. Em 06/11/2026 ela respondeu normalmente com o token do usuário do sistema; a v28.0 ainda não existe.
**Última revisão:** 06/11/2026 (Fase 2 concluída e validada de ponta a ponta no WhatsApp real, nos papéis de cliente e de fornecedor)

## O que está configurado

- **Código:** app `apps/whatsapp` com recebimento, envio com as travas do laboratório, mídia, templates, formulários nativos (WhatsApp Flows), motor de fluxo conversacional, telas de conversa e comandos de conferência e de simulação.
- **Painel da Meta:** termos da Plataforma do WhatsApp Business aceitos e número de teste criado em 06/11/2026, com uma conta do WhatsApp Business de teste no portfólio. IDs em `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_BUSINESS_ACCOUNT_ID` (local e servidor). Um destinatário de teste cadastrado (celular do Danilo).
- **Webhook:** objeto `whatsapp_business_account` assinado no app com os campos `messages` e `message_template_status_update`, no mesmo callback da Fase 1; o app está inscrito na conta de teste (`subscribed_apps`).
- **Templates:** `b2g_retomar_conversa` e `b2g_confirmacao_reuniao` enviados para análise em 06/11/2026 (pt_BR, utilidade). O `hello_world` da Meta já vem aprovado na conta de teste.
- **Formulário nativo:** `b2g_cadastro` criado e publicado na Meta em 06/11/2026.
- **Servidor:** com `LAB_DRY_RUN=False` e só o celular do Danilo em `LAB_ALLOWED_RECIPIENTS` e em `OWNER_WHATSAPP_NUMBERS`, por decisão do Danilo, para a conversa de teste seguir funcionando. `PRIVACY_POLICY_URL=https://brave2grow.com/privacidade/`.
- **Número comercial:** continua no app WhatsApp Business. As opções para levá-lo à API estão em "Número comercial: opções".

## Passo a passo no painel (número de teste)

1. **Número de teste:** no app "B2G Integrations Lab", caso de uso WhatsApp, abrir "Etapa 1. Experimente" e aceitar os termos. A Meta cria uma conta do WhatsApp Business de teste com um número de teste.
2. **IDs:** copiar o "Phone Number ID" para `WHATSAPP_PHONE_NUMBER_ID` e a "Identificação da conta de mensagens" para `WHATSAPP_BUSINESS_ACCOUNT_ID`, no `.env` local e no do servidor (o `deploy.py` só cria o `.env` do servidor na primeira vez).
3. **Destinatário de teste:** em "Destinatário", "Gerenciar lista de números de telefone", cadastrar o celular e confirmar com o código que chega no WhatsApp. O número de teste só envia para até 5 destinatários cadastrados.
4. **Acesso do usuário do sistema:** rodar `meta_check`. Em 06/11/2026 o token já alcançou a conta de teste com as duas permissões do WhatsApp, sem atribuição manual. Se não alcançar, atribuir a conta ao usuário do sistema "B2G Lab API" (Configurações do negócio > Contas do WhatsApp) e, se preciso, gerar token novo.
5. **Webhook:** no painel, a tela de webhooks do WhatsApp fica dentro da "Etapa 2. Configuração da produção", junto com o cadastro do número real. Por isso foi feito pela API:
   - `POST /<APP_ID>/subscriptions` com o token de app, `object=whatsapp_business_account`, o callback da Fase 1 (`https://<domínio do servidor>/webhooks/meta/`), o `META_WEBHOOK_VERIFY_TOKEN` e `fields=messages,message_template_status_update`. A Meta faz o handshake na hora.
   - `POST /<WABA_ID>/subscribed_apps` com o token do usuário do sistema, para a conta entregar os eventos ao app. O `whatsapp_check` confirma.
6. **Templates e formulário:** no servidor, `whatsapp_templates submit <nome>` e `whatsapp_forms create b2g_cadastro`.
7. **Primeira conversa:** publicar o código na EC2 (`python deploy.py`), mandar "oi" do celular para o número de teste e acompanhar em `/whatsapp/`.
8. **Envio real:** no servidor, colocar o celular em `LAB_ALLOWED_RECIPIENTS` e desligar `LAB_DRY_RUN`.

O token de acesso que o painel gera na Etapa 1 é temporário e não é usado pelo laboratório.

## Como o laboratório integra

### Recebimento (`apps/whatsapp/webhook.py` e `inbound.py`)

- Handler da rota `whatsapp_business_account` do provedor `meta` (ADR 0003). Campos tratados: `messages` (mensagens recebidas e status de entrega) e `message_template_status_update`; os outros ficam no bruto, registrados no log.
- **Identidade (ADR 0006):** o contato é identificado pelo BSUID (`user_id`). O telefone (`wa_id`) vai para `Contact.phone` quando vem, com o nono dígito para celulares brasileiros antigos. Um contato já existente com o mesmo telefone (ex.: veio do site) é reaproveitado.
- **Mensagens:** cada uma vira `Message` de entrada (idempotente pelo `wamid`), na conversa aberta do contato com aquele número, e atualiza `last_inbound_at`, que controla a janela de 24h. Também vira o evento `whatsapp.message_received` e segue para o motor de fluxo.
- **Tipos:**
  - texto;
  - respostas de botão e de lista (título em `body`, ID em `raw_payload.reply_id`);
  - botão de template (payload em `reply_id`);
  - resposta de formulário nativo (`nfm_reply`): o `response_json` vai para `raw_payload.form_response`, e `body` ganha um resumo;
  - mídia (legenda), localização, reação e contatos.

  Os demais ficam com o tipo e o bruto.
- **Mídia recebida:** imagem, áudio, vídeo, documento e figurinha são baixados logo depois do commit pela tarefa `download_media`, porque a URL da Meta expira em 5 minutos. O arquivo vai para `var/media/whatsapp/AAAA/MM/` com a extensão do tipo, e os dados (ID, tipo, sha256, tamanho e caminho) ficam em `raw_payload.media`. A tela serve o arquivo só a staff, nunca como estático público.
- **Palavra de saída:** `SAIR`, `PARAR` ou `STOP` (sozinhas, sem diferenciar maiúsculas, acentos e pontuação) em texto ou botão revogam os consentimentos do WhatsApp, disparam `contact_opted_out`, cancelam o fluxo em andamento e geram a confirmação de saída.
- **Consentimento:** escrever para a Brave2Grow não gera consentimento automático. Ele permite responder dentro da janela, mas contato proativo exige um `Consent` registrado (no fluxo, pelo botão "Quero receber" ou pela caixa de novidades do formulário).
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

Montagem das mensagens (`apps/whatsapp/payloads.py`), com os limites validados antes de chamar a API:

| Tipo | Limites |
|---|---|
| Texto | até 4096 caracteres |
| Botões de resposta | até 3, título até 20 |
| Lista | até 10 linhas, título até 24, descrição até 72 |
| Mídia | imagem JPEG, PNG ou WebP até 5 MB; áudio AAC, AMR, MP3, MP4 ou OGG até 16 MB; vídeo MP4 ou 3GP até 16 MB; documento até 100 MB; legenda até 1024 (áudio não aceita legenda) |
| Formulário nativo | botão até 20 caracteres |
| Template | variáveis e botões conferidos pelo catálogo |

**Envio de mídia** (`send_media`): o tipo de mensagem sai do tipo do arquivo (o que não for imagem, áudio ou vídeo aceito vira documento). O arquivo sobe para a Meta (`POST /<PHONE_NUMBER_ID>/media`, fica 30 dias) e vai pelo ID. No dry-run, ou fora da allowlist, nada sobe.

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

### Formulários nativos (WhatsApp Flows: `forms_catalog.py`, `form_sync.py`)

- **Flows estáticos, sem endpoint de dados:** a tela final termina com a ação `complete`, e as respostas voltam como `nfm_reply`. O JSON fica versionado no catálogo (Flow JSON 6.0).
- **`b2g_cadastro`** (categoria `LEAD_GENERATION`, tela `CADASTRO`): nome, email, interesse (Conhecer os serviços, Agendar uma conversa, Receber conteúdos) e uma caixa opcional de opt-in de novidades. O consentimento só é registrado se a caixa for marcada, com o texto exato do rótulo.
- **Estado na Meta:** `WhatsAppForm` guarda ID, status (`DRAFT`, `PUBLISHED`...) e erros de validação. Um Flow publicado não pode ser editado nem apagado, só clonado ou descontinuado; um rascunho só pode ser enviado em modo `draft`, e o laboratório escolhe o modo pelo status.
- **No motor:** o nó `Form` envia o convite com `flow_token = <execução>:<nó>` e só aceita o `nfm_reply` com esse token. Outra mensagem conta como tentativa e reenvia o convite. Sem o formulário na Meta, o fluxo segue por um caminho alternativo.

### Motor de fluxo (`apps/whatsapp/flows`, ADR 0007)

- **Fluxos em código:** grafos de nós versionados. Tipos de nó: `Say` (mensagem), `Ask` (pergunta por botões, lista ou texto validado), `Form` (formulário nativo), `Branch` (condição), `Call` (serviço interno ou API externa, em savepoint), `Handoff` (passa para humano) e `End`.
- **Estado:** `FlowRun` guarda o fluxo, o nó atual, as respostas e as tentativas. No máximo uma execução aberta por conversa.
- **Envio depois do commit:** o motor decide as respostas dentro da transação do webhook; a tarefa `send_outbox` envia depois do commit, marca a mensagem recebida como lida com "digitando..." e espera `WHATSAPP_FLOW_SEND_DELAY` (1 s) entre mensagens seguidas, porque a Meta não garante a ordem. Um bloqueio interrompe o resto e vira o evento `whatsapp.flow_send_blocked`.
- **Regras, na ordem de prioridade:**
  1. **SAIR:** cancela o fluxo e confirma a saída.
  2. **MENU (ou INICIO):** recomeça o fluxo e devolve do humano ao robô. **CADASTRO** inicia o fluxo `cadastro`.
  3. **Botão de template:** tem prioridade sobre o fluxo em andamento. `retomar_sim` abre o menu, `retomar_nao` responde e encerra, e `reuniao_*` registra `meeting.response` e responde sem mexer na pergunta aberta.
  4. **Handoff:** a conversa fica "com humano" e o robô não responde até alguém clicar em "Devolver ao assistente" na tela ou o contato enviar MENU.
  5. **Pergunta aberta:** a resposta é interpretada. O ID do botão leva o nó como prefixo (`no:opcao`), para um botão antigo não valer como resposta; também valem o título digitado (sem acento nem pontuação) e o número da opção. Duas respostas inválidas seguidas levam ao caminho de falha (em geral, o handoff). Uma pergunta sem resposta por 24 horas expira.
  6. **Sem fluxo aberto:** o fluxo `boas_vindas` começa, exceto nas 12 horas depois de um fluxo concluído (um "obrigado" não reinicia o menu).
- **Falhas no motor:** viram o evento `whatsapp.flow_error` sem perder a mensagem recebida.
- **Fluxo `boas_vindas`** (`flows/brave2grow.py`):
  1. Saudação pelo nome. No primeiro contato, inclui o aviso de privacidade da seção 13, com o link da política, e o lembrete do SAIR, e registra `privacy.notice_shown`.
  2. Menu com 3 botões: Conhecer serviços, Agendar conversa, Falar com o Danilo.
  3. **Serviços:** apresentação e pergunta de novidades. "Quero receber" registra `Consent` de marketing no WhatsApp com o texto aceito e o `wamid` como prova.
  4. **Agendar:** pede o email só se o contato não tem um (validado, gravado se nenhum outro contato o usa), pergunta o período e registra `lead.scheduling_requested` com a etiqueta `lead-whatsapp`. O agendamento com Google Calendar é o F01 (Fase 10).
  5. **Falar com o Danilo:** handoff com o evento `whatsapp.handoff` e o aviso ao dono.
- **Fluxo `cadastro`** (palavra CADASTRO ou botão na tela): formulário `b2g_cadastro`, gravação de nome e email vazios do contato, evento `lead.form_submitted`, etiqueta `lead-whatsapp` e consentimento se a caixa foi marcada.
- **Aviso ao dono no handoff:** os números de `OWNER_WHATSAPP_NUMBERS` com janela aberta recebem quem pediu, telefone, motivo e respostas, depois da resposta ao cliente. Sem janela, o aviso só poderia ir por template aprovado; até lá, fica o evento `whatsapp.owner_notice_skipped` e o handoff aparece no painel. O Console CEO (Fase 9) amplia esses avisos.

### Telas (`/whatsapp/`)

- **Conversas** (link no topo do painel, só staff): lista as conversas do WhatsApp com a janela de 24h e a marca "com humano".
- **Conversa:** mensagens atualizadas pelo HTMX a cada 5 s, com o status de cada envio, o ID dos botões tocados e as mídias recebidas (imagem em miniatura, demais tipos por link); o fluxo em andamento com nó atual e respostas; o botão "Devolver ao assistente" durante o handoff.
- **Responder como Brave2Grow:** texto livre ou arquivo com legenda (dentro da janela).
- **Testes rápidos:** mensagem com três botões (`teste_sim`, `teste_nao`, `teste_talvez`), imagem de teste e formulário de cadastro.
- É uma versão só do WhatsApp; a caixa de entrada unificada continua na Fase 8.

### Comandos

```powershell
.\.venv\Scripts\python.exe manage.py whatsapp_check                                  # número, apps assinados na WABA e templates (só leitura)
.\.venv\Scripts\python.exe manage.py whatsapp_templates list                         # catálogo comparado com o estado na Meta
.\.venv\Scripts\python.exe manage.py whatsapp_templates sync                         # atualiza o status (só leitura na Meta)
.\.venv\Scripts\python.exe manage.py whatsapp_templates submit b2g_retomar_conversa  # envia para aprovação
.\.venv\Scripts\python.exe manage.py whatsapp_forms list                             # formulários do catálogo e estado na Meta
.\.venv\Scripts\python.exe manage.py whatsapp_forms create b2g_cadastro              # cria e publica (--draft para só criar)
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --text "Oi"      # dentro da janela de 24h
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --template b2g_confirmacao_reuniao --var Ana --var "quinta, às 10h"
.\.venv\Scripts\python.exe manage.py whatsapp_simulate_reply --contact +55... --template-button reuniao_confirmar --title Confirmo --url https://<domínio>/webhooks/meta/
```

- **`whatsapp_send_test`:** só envia para um contato que já existe (o que acontece quando ele escreve primeiro) e passa por todas as travas. Para testar template fora da janela, o contato precisa de um `Consent` de WhatsApp.
- **Templates e formulários próprios:** rodar `submit` e `create` no servidor, para o estado ficar no banco que recebe o webhook.
- **`whatsapp_simulate_reply`:** manda à esteira um webhook assinado com o App Secret, como se o contato tivesse escrito ou tocado num botão de template. Serve para validar respostas hipotéticas, como os botões de templates ainda em análise. A mensagem fica com `wamid.simulado.` e `simulated: true` no bruto e não é marcada como lida na Meta.

## Permissões

| Permissão | Uso | No token |
|---|---|---|
| `whatsapp_business_messaging` | Enviar e receber mensagens e mídia | sim |
| `whatsapp_business_management` | Número, templates, Flows, assinatura da WABA | sim |
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
| Texto, interativas, imagem, documento e convite de formulário dentro da janela | `service` | `free_customer_service` | não |
| Template `hello_world` dentro da janela | `utility` | `regular` | sim |

Consequência prática: para responder quem escreveu, usar texto, mídia ou mensagens interativas; template só quando a janela estiver fechada.

## Decisões e verificações

- **Política de provedores de IA** (consultada em 06/11/2026): a política vale para "provedores e desenvolvedores de inteligência artificial", e a página diz que não muda a cobrança das demais empresas. A Brave2Grow, usando um LLM para atender os próprios clientes sobre os próprios serviços, se enquadra como empresa comum, não como provedor de IA. A página não trata esse caso de forma explícita: rever antes de abrir o concierge (F17) para o público.
- **Política de privacidade:** o aviso do primeiro contato aponta para https://brave2grow.com/privacidade/, que cita a LGPD e o WhatsApp como canal para os direitos do titular.

## Número comercial: opções

O número comercial da Brave2Grow usa o app WhatsApp Business. Registrá-lo só na Cloud API faz ele deixar de funcionar no app. A coexistência (o mesmo número no app e na API) existe, mas tem condições (página "Onboard WhatsApp Business app users", consultada em 06/11/2026):

- só é feita por Embedded Signup, por um Tech Provider ou parceiro de solução (BSP). O app do laboratório é de desenvolvedor direto;
- exige o app WhatsApp Business 2.24.17 ou mais recente; sincroniza contatos e até 6 meses de conversas;
- no app, deixa de ter mensagens temporárias, visualização única, localização em tempo real e listas de transmissão (que ficam só leitura), e grupos não vão para a API;
- vazão fixa de 20 mensagens por segundo; mensagens enviadas pelo app continuam grátis, e as da API seguem a tabela da Cloud API.

| Caminho | O que exige | Efeito |
|---|---|---|
| Número novo dedicado à API | Um chip novo | O número atual segue intacto no app; mais simples |
| Coexistência via parceiro (BSP) | Contrato com um BSP que ofereça coexistência | Mesmo número no app e na API, com as limitações acima |
| Tornar a Brave2Grow Tech Provider | Análise do app, Embedded Signup próprio | Coexistência sem intermediário; também abre o F15 como produto |
| Migrar o número só para a API | Nada além do registro | O app WhatsApp Business deixa de funcionar nesse número |

Para o laboratório, o número de teste basta. A escolha entre esses caminhos é do Danilo, antes de usar o WhatsApp com clientes reais.

## O que funcionou

- 06/11/2026, rodada 1: recebimento com BSUID (o número de teste recebe BSUID, com `user_id` e `wa_id` no bloco `contacts` e `from_user_id` na mensagem); envio de texto, botões e `hello_world` com status enviada, entregue e lida; fluxo `boas_vindas` em todos os caminhos (serviços com consentimento, agendamento com email inválido e válido, handoff e devolução pela tela, MENU, recomeço bloqueado logo depois de concluir, SAIR).
- 06/11/2026, rodada 2, com o WhatsApp Web no papel de cliente e a tela do laboratório no papel de fornecedor:

| Lado | Ação | Resultado |
|---|---|---|
| Cliente | MENU | Saudação com o aviso de privacidade e o link da política, e o menu |
| Cliente | "Falar com o Danilo" | Resposta de handoff e, depois dela, o aviso ao dono com motivo e respostas |
| Fornecedor | Resposta em texto e imagem de teste | Chegaram no WhatsApp (imagem enviada por upload e ID) |
| Cliente | Texto durante o handoff | Robô em silêncio |
| Cliente | Figurinha e foto | Baixadas para o servidor como `image/webp` e `image/jpeg` (o WhatsApp converteu o PNG em JPEG) |
| Fornecedor | Devolver ao assistente | Handoff encerrado |
| Cliente | CADASTRO e formulário preenchido com opt-in | `nfm_reply` com `name: flow`, `body: Sent` e o `response_json` com os campos e o `flow_token`; cadastro gravado, consentimento `whatsapp_form` e agradecimento |
| Simulado | Botões dos templates em análise (Confirmo, Reagendar, Agora não, Sim, continuar, Cancelar) | Respostas reais no WhatsApp; "Cancelar" com o menu aberto não mexeu na pergunta |
| Fornecedor | PDF com legenda pelo anexo | Chegou como documento com nome e legenda |
| Fornecedor | Formulário pela tela, cliente preenche sem opt-in | Cadastro gravado sem consentimento novo |

- Todos os envios das duas rodadas passaram por enviada, entregue e lida pelo webhook.

## Limitações encontradas

- A verificação de webhook manda o verify token na URL (como `hub.verify_token` e `hub_verify_token`), e os logs de acesso do Gunicorn e do Caddy gravavam a URL completa. Corrigido: o Gunicorn grava só o caminho e o Caddy troca o valor por `REDACTED`. O token foi trocado; o campo do painel do Messenger ainda mostra o valor antigo, que só importa se alguém refizer a verificação por ali.
- A listagem de templates devolve `rejected_reason: "NONE"` quando não há motivo; o laboratório grava vazio.
- A Meta não garante a ordem de mensagens enviadas em sequência; o motor espera 1 s entre elas. Para ordem estrita, seria preciso esperar o `delivered` de cada uma.
- A aprovação de templates não é imediata: os dois templates próprios seguiam em `PENDING` mais de uma hora depois do envio. Até a resposta, o envio deles é barrado; o webhook atualiza o status sozinho.
- O `mimetypes` do servidor não conhece `image/webp`; o laboratório usa uma tabela própria de extensões.
- No WhatsApp Web, o formulário nativo abre num painel lateral (iframe) mais largo que a janela; a automação de teste precisou clicar no texto da caixa de opt-in. Isso não afeta o celular.
- Um toque em botão de template com um fluxo aberto era lido como resposta à pergunta; corrigido (o botão de template tem prioridade).

## Próximos passos (fora da Fase 2)

1. Quando a Meta aprovar os templates, o status atualiza sozinho; enviar `b2g_confirmacao_reuniao` de verdade no F02 (Fase 10).
2. Respostas abertas com Claude, sempre com fallback para humano (F17): precisa de `ANTHROPIC_API_KEY`.
3. Console CEO (Fase 9): comandos do Danilo e avisos por template quando a janela dele estiver fechada.
4. Agendamento com Google Calendar e Flows com endpoint de dados (horários livres): F01 (Fase 10).
5. Áudio na voz clonada (Fase 7).
6. Escolher o caminho do número comercial (ver "Número comercial: opções") antes de atender clientes reais.
