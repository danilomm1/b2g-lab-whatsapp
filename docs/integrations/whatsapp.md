# WhatsApp (Cloud API)

**Versão da API:** Graph API v26.0 (`META_GRAPH_API_VERSION`), a mesma da Fase 1. Os exemplos atuais da documentação do WhatsApp já usam a v27.0, mas a tabela de versões da Graph API ainda não a lista; a troca fica para quando ela aparecer lá.
**Última revisão:** 06/11/2026 (Fase 2 em andamento: recebimento validado contra a Meta real)

## O que está configurado

- **Código:** app `apps/whatsapp` com recebimento (webhook), envio com as travas do laboratório e comandos de conferência.
- **Painel da Meta:** termos da Plataforma do WhatsApp Business aceitos e número de teste criado em 06/11/2026, com uma conta do WhatsApp Business de teste no portfólio. IDs em `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_BUSINESS_ACCOUNT_ID` (local e servidor). Um destinatário de teste cadastrado (celular do Danilo).
- **Webhook:** objeto `whatsapp_business_account` assinado no app com o campo `messages` e o mesmo callback da Fase 1; o app está inscrito na conta de teste (`subscribed_apps`).
- **Número comercial:** a conta do portfólio que usa o número comercial é do tipo "Aplicativo WhatsApp Business" e só migra depois da decisão sobre coexistência (CLAUDE.md, 5.6).

## Passo a passo no painel (número de teste)

1. **Número de teste:** no app "B2G Integrations Lab", caso de uso WhatsApp, abrir a configuração da API e iniciar o uso da API. A Meta cria uma conta do WhatsApp Business de teste com um número de teste.
2. **IDs:** copiar o "ID do número de telefone" para `WHATSAPP_PHONE_NUMBER_ID` e o "ID da conta do WhatsApp Business" para `WHATSAPP_BUSINESS_ACCOUNT_ID`, no `.env` local e no do servidor.
3. **Destinatário de teste:** no campo "Para", cadastrar o celular do Danilo e confirmar com o código que chega no WhatsApp. O número de teste só envia para até 5 destinatários cadastrados, sem custo.
4. **Acesso do usuário do sistema:** rodar `meta_check`. Em 06/11/2026 o token já alcançou a conta de teste com as duas permissões do WhatsApp, sem atribuição manual. Se não alcançar, atribuir a conta ao usuário do sistema "B2G Lab API" (Configurações do negócio > Contas do WhatsApp) e, se preciso, gerar token novo.
5. **Webhook:** no painel, a tela de webhooks do WhatsApp fica dentro da "Etapa 2. Configuração da produção", junto com o cadastro do número real. Por isso foi feito pela API:
   - `POST /<APP_ID>/subscriptions` com o token de app, `object=whatsapp_business_account`, o callback da Fase 1 (`https://<domínio do servidor>/webhooks/meta/`), o `META_WEBHOOK_VERIFY_TOKEN` e `fields=messages`. A Meta faz o handshake na hora.
   - `POST /<WABA_ID>/subscribed_apps` com o token do usuário do sistema, para a conta entregar os eventos ao app. O `whatsapp_check` confirma.

O token de acesso que o painel gera na Etapa 1 é temporário e não é usado pelo laboratório.
6. **Primeira conversa:** publicar o código na EC2 (`python deploy.py`), mandar "oi" do celular para o número de teste e conferir no admin o contato, a conversa e a mensagem. A janela de 24h fica aberta.
7. **Primeiro envio real:** no servidor, colocar o celular em `LAB_ALLOWED_RECIPIENTS`, desligar `LAB_DRY_RUN` só durante o teste e rodar `whatsapp_send_test --to <celular> --text "..."`. O status (enviada, entregue, lida) chega pelo webhook.

## Como o laboratório integra

### Recebimento (`apps/whatsapp/webhook.py` e `inbound.py`)

- Handler da rota `whatsapp_business_account` do provedor `meta` (ADR 0003). Só o campo `messages` é interpretado; os outros ficam no bruto, registrados no log.
- **Identidade (ADR 0006):** o contato é identificado pelo BSUID (`user_id`). O telefone (`wa_id`) vai para `Contact.phone` quando vem, com o nono dígito para celulares brasileiros antigos. Um contato já existente com o mesmo telefone (ex.: veio do site) é reaproveitado.
- **Mensagens:** cada uma vira `Message` de entrada (idempotente pelo `wamid`), na conversa aberta do contato com aquele número, e atualiza `last_inbound_at`, que controla a janela de 24h. Também vira o evento `whatsapp.message_received`.
- **Tipos:** texto, respostas de botão e de lista (título em `body`, ID em `raw_payload.reply_id`), botão de template, mídia (legenda), localização, reação e contatos. Os demais ficam com o tipo e o bruto.
- **Palavra de saída:** `SAIR`, `PARAR` ou `STOP` (sozinhas, sem diferenciar maiúsculas, acentos e pontuação) em texto ou botão revogam os consentimentos do WhatsApp e disparam `contact_opted_out`.
- **Consentimento:** escrever para a Brave2Grow não gera consentimento automático. Ele permite responder dentro da janela, mas contato proativo exige um `Consent` registrado (ex.: por botão em um fluxo).
- **Status:** `sent`, `delivered`, `read` e `failed` avançam o status da mensagem enviada sem regredir (chegam fora de ordem). Cada notificação, com o bloco `pricing`, fica em `raw_payload.statuses`. Falhas viram o evento `whatsapp.message_failed` com o código de erro.
- **Troca de número ou de BSUID:** as mensagens de sistema atualizam a identidade e geram `whatsapp.identity_changed`.

### Envio (`apps/whatsapp/services.py`)

`send_message` é o único ponto de envio. As travas, nesta ordem:

1. **Destinatário:** `to` com o telefone ou, sem ele, `recipient` com o BSUID.
2. **Janela de 24h:** fora dela, só template; o envio passa a contar como proativo.
3. **Contato proativo:** exige `Consent` ativo para o WhatsApp na finalidade informada e respeita `LAB_MAX_PROACTIVE_PER_WEEK`, somando todos os canais.
4. **Laboratório:** com `LAB_DRY_RUN=True` (padrão) nada sai e a mensagem fica como "Simulada"; envio real só para `LAB_ALLOWED_RECIPIENTS`.

Bloqueios levantam `SendBlocked` e não gravam nada. Erros da API viram `Message` com status "Falhou" e o erro completo. O envio não é repetido depois de um timeout de leitura ou de um erro 5xx, porque a Meta pode ter enviado; só repete em limite de vazão (130429 e os limites da Graph API) ou quando a conexão nem abriu.

Montagem das mensagens (`apps/whatsapp/payloads.py`), com os limites validados antes de chamar a API: texto (até 4096 caracteres), botões de resposta (até 3, título até 20), lista (até 10 linhas, título até 24, descrição até 72) e template.

`mark_as_read` marca a mensagem recebida como lida e pode mostrar "digitando...". Também segue dry-run e allowlist.

### Telas de teste (`/whatsapp/`)

- **Conversas** (link no topo do painel, só staff): lista as conversas do WhatsApp com o estado da janela de 24h.
- **Conversa:** mostra as mensagens (atualizadas pelo HTMX a cada 5 s), com o status de cada envio (simulada, na fila, enviada, entregue, lida, falhou) e o ID dos botões tocados.
- **Responder:** texto livre dentro da janela e um botão que manda uma mensagem de teste com três botões (`teste_sim`, `teste_nao`, `teste_talvez`), para validar a resposta interativa.
- Todo envio passa por `send_message`. Para chegar de verdade no celular, o servidor precisa de `LAB_DRY_RUN=False` e do número em `LAB_ALLOWED_RECIPIENTS`; voltar ao dry-run ao fim do teste.
- É uma versão só do WhatsApp; a caixa de entrada unificada continua na Fase 8.

### Comandos

```powershell
.\.venv\Scripts\python.exe manage.py whatsapp_check                                # número, apps assinados na WABA e templates (só leitura)
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --text "Oi"    # dentro da janela de 24h
.\.venv\Scripts\python.exe manage.py whatsapp_send_test --to +55... --template hello_world --language en_US
```

O `whatsapp_send_test` só envia para um contato que já existe (o que acontece quando ele escreve primeiro) e passa por todas as travas. Para testar template fora da janela, registrar antes um `Consent` de WhatsApp para o contato no admin.

## Permissões

| Permissão | Uso | No token |
|---|---|---|
| `whatsapp_business_messaging` | Enviar e receber mensagens | sim |
| `whatsapp_business_management` | Número, templates, assinatura da WABA | sim |
| `business_management` | Ativos do portfólio | sim |

O token só alcança a WABA de teste depois que ela for atribuída ao usuário do sistema (passo 4).

## Custos (página oficial de preços, consultada em 06/11/2026)

- Cobrança por mensagem entregue desde 01/07/2025, conforme a categoria e o país do destinatário. Mensagens recebidas não são cobradas.
- **Templates:** marketing, utilidade e autenticação são cobrados em qualquer momento.
- **Serviço (texto livre dentro da janela):** desde 01/10/2026, cada número tem 1.000 mensagens de serviço grátis por mês; a partir da 1.001ª, são cobradas. Sem forma de pagamento cadastrada, a Meta só entrega dentro da cota grátis.
- **Utilidade dentro da janela:** deixou de ser grátis em 01/10/2026.
- **Janela de ponto de entrada grátis:** quem chega por anúncio de clique para o WhatsApp abre 7 dias sem cobrança.
- **Brasil:** os valores estão na planilha de preços em BRL da Meta, não na página. Faturamento em reais disponível desde 01/07/2026, obrigatório até 30/06/2027. Consultar a planilha antes de qualquer disparo em volume.
- **Número de teste:** envios grátis para até 5 destinatários cadastrados.

## Pontos a verificar

- **Política de provedores de IA:** a Meta tem uma política específica para "AI Providers" (vigente desde 16/02/2026, atualizada em 12/05/2026), com cobrança de mensagens fora de template para usuários no Brasil. Antes do concierge com Claude (F17), confirmar se o uso da Brave2Grow se enquadra.

## O que funcionou

- 06/11/2026: recebimento e envio cobertos por testes com payloads da documentação atual (BSUID incluído) e a Graph API mockada.
- 06/11/2026: primeira conversa real. Mensagens de texto do celular cadastrado para o número de teste chegaram na EC2 assinadas e foram processadas: contato criado com telefone em E.164, identidade pelo BSUID (o número de teste recebe BSUID, com `user_id` e `wa_id` no bloco `contacts` e `from_user_id` na mensagem), conversa aberta no `phone_number_id` com a janela de 24h e um evento por mensagem.

## Limitações encontradas

- A verificação de webhook manda o verify token na URL (como `hub.verify_token` e `hub_verify_token`), e os logs de acesso do Gunicorn e do Caddy gravavam a URL completa. Corrigido em 06/11/2026: o Gunicorn grava só o caminho e o Caddy troca o valor por `REDACTED`.

## Próximos passos

1. Primeiro envio real (passo 7), com resposta dentro da janela e status de entrega pelo webhook.
2. Catálogo de templates (`apps/whatsapp/templates_catalog.py`) e sincronização de status de aprovação (campo `message_template_status_update`).
3. Motor de fluxo conversacional: nós de mensagem, pergunta, condição, chamada de API e handoff humano. Os envios dos fluxos precisam sair depois do commit da transação do webhook.
4. Resposta automática de confirmação para a palavra de saída.
5. Mídia (download e envio), WhatsApp Flows e indicador de digitação nos fluxos.
