# Facebook (Página da Brave2Grow e Messenger)

**Versão da API:** Graph API v26.0 (`META_GRAPH_API_VERSION`). A v27.0 saiu em 04/11/2026 só com mudanças aditivas em Páginas; a troca fica para depois da fase.
**Última revisão:** 06/11/2026 (Fase 3 em preparação; nada validado contra a Meta ainda)

Base comum (app, usuário do sistema, token, webhook único) em [meta.md](meta.md). O Instagram fica em [instagram.md](instagram.md).

## Situação em 06/11/2026

- **Caso de uso "Gerenciar tudo na sua Página":** prontas para teste `business_management`, `pages_manage_metadata`, `pages_show_list` e `public_profile`. Com "Adicionar": `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights`, Page Mentions e Business Asset User Profile Access.
- **Caso de uso Messenger:** prontas para teste `pages_messaging`, `pages_manage_metadata` e `pages_show_list`. Human Agent com "Adicionar".
- **Webhook:** callback configurado na Fase 1 pelo caso de uso do Messenger; o evento de teste do campo `messages` chegou assinado com rota `page`. O app ainda não foi conectado à Página (Configurações da API do Messenger > 2. Gere tokens de acesso), então eventos reais da Página não chegam.
- **Usuário do sistema:** a Página está atribuída com acesso total (meta.md).
- **Código:** ainda não existe app `facebook`. Entregas com `object: page` ficam como "ignoradas", com o payload guardado.

## Como a API funciona

Resumo da documentação oficial lida em 06/11/2026 (Pages API e Messenger Platform). Os itens marcados "a confirmar" dependem do teste real.

### Token da Página

- Envio no Messenger, publicação e moderação pedem **token de Página**, não o do usuário do sistema. Ele sai de `GET /me/accounts` (ou `GET /<PAGE_ID>?fields=access_token`) chamado com o token do usuário do sistema.
- Token de Página derivado de token sem expiração também não expira. O laboratório guarda o token da Página criptografado em `IntegrationCredential`, renovado pelo comando de conferência quando o token do usuário do sistema mudar.

### Webhooks

- Inscrição do app na Página: `POST /<PAGE_ID>/subscribed_apps?subscribed_fields=...` com o token da Página. `feed` exige `pages_manage_metadata` e `pages_show_list`; os campos de mensagem exigem também `pages_messaging`.
- Campos de interesse: `feed` (posts e comentários), `messages`, `messaging_postbacks`, `message_echoes`, `message_deliveries`, `message_reads`, `message_reactions`, `message_edits`, `messaging_referrals` e `messaging_optins`.
- A Meta espera HTTP 200 em até 5 segundos e, depois de 1 hora de falhas, desinscreve o app da Página. A esteira da Fase 0 já responde antes de processar (ADR 0003).
- **Mensagem:** `entry[].messaging[]` com `sender.id` (PSID), `recipient.id` (a Página), `timestamp` e `message` (`mid`, `text`, `attachments`, `quick_reply`). Ecos das mensagens enviadas pela Página chegam pelo campo `message_echoes`, com `is_echo: true`.
- **Comentário:** `entry[].changes[]` com `field: feed`. A documentação atual só mostra o exemplo de post (`item: post`, `verb: add`, `post_id`, `from`, `message`). O formato de comentário (`item: comment`, `comment_id`, `parent_id`, `post_id`, `from`) aparece documentado só para grupos; confirmar com o primeiro payload real guardado.

### Messenger

- Envio: `POST /<PAGE_ID>/messages` com o token da Página, `recipient.id` = PSID e `messaging_type`:
  - `RESPONSE` dentro da janela de 24h após a última mensagem da pessoa;
  - `MESSAGE_TAG` fora dela, com `tag=HUMAN_AGENT` (até 7 dias, resposta de pessoa de verdade, depende do recurso Human Agent) ou `CUSTOMER_FEEDBACK`;
  - `UPDATE` para mensagem iniciada pela empresa dentro das regras da plataforma.
- As tags `CONFIRMED_EVENT_UPDATE`, `ACCOUNT_UPDATE` e `POST_PURCHASE_UPDATE` devolvem erro 100 desde 27/04/2026. Não usar.
- **Resposta privada** a comentário ou post da Página: `POST /<PAGE_ID>/messages` com `recipient.comment_id` (ou `post_id`). Uma única mensagem, em até 7 dias. Precisa de `pages_messaging`. Com acesso padrão, só alcança pessoas com função no app.

### Publicação e comentários

- Post: `POST /<PAGE_ID>/feed` com `message` e, opcionalmente, `link`. Agendamento com `published=false` e `scheduled_publish_time` entre 10 minutos e 30 dias à frente.
- Foto: `POST /<PAGE_ID>/photos` com `url` pública.
- Permissões: `pages_manage_posts`, `pages_read_engagement` e `pages_show_list`, com a tarefa CREATE_CONTENT na Página.
- Ler comentários: `GET /<POST_ID>/comments?fields=from,message` (`pages_read_engagement` e `pages_read_user_content`). Responder: `POST /<POST_ID ou COMMENT_ID>/comments` com `message` (`pages_manage_engagement`). Ocultar: `POST /<COMMENT_ID>` com `is_hidden=true` (a confirmar na referência de comentários).

### Insights

- Várias métricas da Página foram removidas: `page_fans` deu lugar a `page_follows`, `page_impressions` a `page_media_view`, e um lote de `*_impressions_unique` saiu com a v26.0. Usar só métricas da lista atual (Pages API > Platform Insights).
- Permissão `read_insights`.

## Modo de desenvolvimento: quem gera eventos

- Com acesso padrão, as permissões e os recursos só valem para pessoas com função no app. A conta pessoal do Facebook usada nos testes precisa de função no app (Funções do app > Funções, como Testador).
- O evento de teste da Fase 1 chegou com o app não publicado. Eventos reais de pessoas talvez exijam o app publicado, como a documentação do Instagram diz. Decisão em aberto em [meta.md](meta.md).

## Passo a passo no painel (a fazer)

Feito pelo Danilo; as etapas comuns (token novo, funções, publicação do app) estão em [meta.md](meta.md).

1. **Permissões da Página:** caso de uso "Gerenciar tudo na sua Página" > Permissões e recursos: "Adicionar" em `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights` e Business Asset User Profile Access.
2. **Messenger:** caso de uso Messenger > Permissões e recursos: "Adicionar" no recurso Human Agent.
3. **Conectar a Página:** Configurações da API do Messenger > "2. Gere tokens de acesso" > conectar a Página Brave2Grow. O token que essa tela mostra não precisa ir para o `.env`: o laboratório obtém o token da Página pelo usuário do sistema.
4. **Campos do webhook:** na mesma tela, em "1. Configure webhooks", assinar `messages`, `messaging_postbacks`, `message_echoes`, `message_reads`, `message_reactions` e `feed` (se `feed` não aparecer ali, ele fica no caso de uso da Página).
5. **Inscrição na Página:** `POST /<PAGE_ID>/subscribed_apps`, pelo comando de conferência do laboratório.

## Plano de implementação (`apps/facebook`)

Ordem e dependências da fase em [meta.md](meta.md).

1. **Conferência (`facebook_check`):** obtém e guarda o token da Página, mostra permissões e tarefas na Página, inscreve o app (`subscribed_apps`) e lista os campos assinados.
2. **Recebimento:** handler da rota `page` do provedor `meta`, separando `messaging[]` (Messenger) de `changes[]` (`feed`).
   - Mensagem vira `Message` de entrada, idempotente pelo `mid`, e atualiza a janela de 24h. Ecos viram `Message` de saída quando não forem envios do próprio laboratório.
   - Contato e `ChannelIdentity` pelo PSID, com `account_id` = ID da Página. O nome vem do perfil (Business Asset User Profile Access).
   - Comentário vira o evento `facebook.comment_received` (idempotente pelo `comment_id`); post da Página vira `facebook.post_published`.
   - Palavra de saída em mensagem revoga os consentimentos do Facebook.
3. **Envio no Messenger:** `send_message` único, com janela de 24h, `HUMAN_AGENT` só por ação humana na tela, `Consent` e limite semanal para contato proativo, dry-run e allowlist. Usa o `GraphClient.post` sem repetição da Fase 2.
4. **Comentários:** responder, ocultar e resposta privada, com o mesmo gatilho por palavra-chave do Instagram.
5. **Publicação:** post de texto, link e foto, com agendamento, sempre com `dry_run` e `LAB_DRY_RUN`.
6. **Insights:** comando com as métricas atuais da Página.
7. **Tela:** conversas do Messenger junto das do WhatsApp e do Instagram.

## Permissões

| Permissão ou recurso | Uso | Situação |
|---|---|---|
| `pages_show_list` | Listar a Página e obter o token dela | no token |
| `pages_manage_metadata` | Inscrever o app na Página (webhooks) | no token |
| `pages_messaging` | Messenger e resposta privada | no token |
| `pages_read_engagement` | Posts, comentários e seguidores | a adicionar |
| `pages_read_user_content` | Comentários de usuários | a adicionar |
| `pages_manage_engagement` | Responder e ocultar comentários | a adicionar |
| `pages_manage_posts` | Publicar | a adicionar |
| `read_insights` | Insights | a adicionar |
| Human Agent | Tag `HUMAN_AGENT` (7 dias) | a adicionar |
| Business Asset User Profile Access | Nome e foto de quem interage | a adicionar |

## O que funcionou

Nada validado ainda nesta fase. Na Fase 1, o evento de teste do campo `messages` chegou assinado e roteado como `page` (meta.md).

## Limitações encontradas

Ainda sem teste real. Pela documentação: envio e publicação só com token de Página, tags de atualização antigas descontinuadas, formato do comentário em `feed` a confirmar, métricas antigas de insights removidas.

## Custos observados

Nenhum ainda. A Graph API não cobra por chamada (meta.md).

## Próximos passos

Os do plano acima, a começar pelo passo a passo no painel e pelo recebimento.
