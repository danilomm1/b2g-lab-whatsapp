# WhatsApp (Cloud API)

**Versão da API:** Graph API v26.0 (`META_GRAPH_API_VERSION`), a mesma da Fase 1. Os exemplos atuais da documentação do WhatsApp já usam a v27.0, mas a tabela de versões da Graph API ainda não a lista; a troca fica para quando ela aparecer lá.
**Última revisão:** 06/11/2026 (Fase 2 em andamento)

## O que está configurado

- **Código:** app `apps/whatsapp` com recebimento (webhook), envio com as travas do laboratório e comandos de conferência.
- **Painel da Meta:** ainda nada específico do WhatsApp. O caso de uso WhatsApp existe no app desde a Fase 1, e o token do usuário do sistema já tem `whatsapp_business_management` e `whatsapp_business_messaging`.
- **Número:** a Fase 2 começa pelo número de teste da Meta. A conta do portfólio que usa o número comercial é do tipo "Aplicativo WhatsApp Business" e só migra depois da decisão sobre coexistência (CLAUDE.md, 5.6).

## Passo a passo no painel (número de teste)

1. **Número de teste:** no app "B2G Integrations Lab", caso de uso WhatsApp, abrir a configuração da API e iniciar o uso da API. A Meta cria uma conta do WhatsApp Business de teste com um número de teste.
2. **IDs:** copiar o "ID do número de telefone" para `WHATSAPP_PHONE_NUMBER_ID` e o "ID da conta do WhatsApp Business" para `WHATSAPP_BUSINESS_ACCOUNT_ID`, no `.env` local e no do servidor.
3. **Destinatário de teste:** no campo "Para", cadastrar o celular do Danilo e confirmar com o código que chega no WhatsApp. O número de teste só envia para até 5 destinatários cadastrados, sem custo.
4. **Acesso do usuário do sistema:** atribuir a conta de teste ao usuário do sistema "B2G Lab API" (Configurações do negócio > Contas do WhatsApp), com controle total. Rodar `meta_check`: se a WABA não aparecer como alcançada, gerar um token novo.
5. **Webhook:** na configuração do caso de uso WhatsApp, cadastrar o mesmo callback da Fase 1 (`https://<domínio do servidor>/webhooks/meta/`) com o `META_WEBHOOK_VERIFY_TOKEN` e assinar o campo `messages`. Conferir com `whatsapp_check` que o app aparece entre os assinados da WABA; se não aparecer, assinar com `POST /<WABA_ID>/subscribed_apps` usando o token do usuário do sistema.
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
- **Mensagens de sistema e BSUID com o número de teste:** a documentação não diz se o número de teste já recebe BSUID; conferir no primeiro webhook real.

## O que funcionou

- 06/11/2026: recebimento e envio cobertos por testes com payloads da documentação atual (BSUID incluído) e a Graph API mockada. Ainda não validado contra a Meta real.

## Limitações encontradas

- Nenhuma ainda contra a Meta real.

## Próximos passos

1. Configurar o número de teste no painel (passos 1 a 5) e validar a primeira conversa na EC2.
2. Catálogo de templates (`apps/whatsapp/templates_catalog.py`) e sincronização de status de aprovação (campo `message_template_status_update`).
3. Motor de fluxo conversacional: nós de mensagem, pergunta, condição, chamada de API e handoff humano. Os envios dos fluxos precisam sair depois do commit da transação do webhook.
4. Resposta automática de confirmação para a palavra de saída.
5. Mídia (download e envio), WhatsApp Flows e indicador de digitação nos fluxos.
