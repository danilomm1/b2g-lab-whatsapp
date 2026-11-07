# Instagram (@brave2grow)

**Versão da API:** Graph API v26.0 (`META_GRAPH_API_VERSION`) em `graph.facebook.com`, configuração com login unificado (ADR 0008). A v27.0 saiu em 04/11/2026 sem mudança que quebre Instagram; a troca fica para depois da fase.
**Última revisão:** 06/11/2026 (Fase 3 em preparação; painel configurado, código ainda não iniciado)

Base comum (app, usuário do sistema, token, webhook único) em [meta.md](meta.md). A Página e o Messenger ficam em [facebook.md](facebook.md).

## O que está configurado (06/11/2026)

- **Configuração:** o caso de uso "API do Instagram" só oferece o login unificado (ADR 0008).
- **Permissões no caso de uso:** `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `instagram_content_publish`, `instagram_manage_insights`, Human Agent e Business Asset User Profile Access adicionados ("Pronto para teste"). Algumas também entraram no caso de uso do Messenger, que as compartilha.
- **Token:** o token novo do usuário do sistema tem as cinco permissões `instagram_*` e alcança a conta @brave2grow (`meta_check` e `/me/assigned_instagram_accounts`).
- **Webhook do objeto `instagram`:** callback e verify token da Fase 1 na etapa "3. Configurar webhooks" da aba do login unificado, com os campos `comments`, `mentions`, `messages`, `messaging_postbacks`, `message_reactions`, `messaging_seen`, `messaging_referral` e `message_edit` assinados (versão v27.0 dos campos).
- **Conta inscrita no app:** `POST /<IG_ID>/subscribed_apps` com os mesmos oito campos, confirmado por `GET /<IG_ID>/subscribed_apps`.
- **Mensagens:** `GET /<IG_ID>/conversations?platform=instagram` respondeu com a lista de conversas, então o acesso às mensagens pela API já está liberado na conta.
- **Eventos de teste:** os exemplos de `comments` e `messages` do botão "Teste" chegaram ao servidor assinados, com rota `instagram`, e ficaram como "ignorados" (sem handler ainda).
- **Ainda não feito:** aceite do convite de testador na conta pessoal de testes e clique em "Publicar" no app (meta.md).
- **Código:** ainda não existe app `instagram`.

## Como a API funciona nesta configuração

Resumo da documentação oficial lida em 06/11/2026 (Instagram Platform e Instagram Messaging). Os itens marcados "a confirmar" dependem do teste real.

### Conta e token

- Chamadas em `https://graph.facebook.com/<versão>/<IG_ID>/...` com o token do usuário do sistema. `/me` é o usuário do sistema; as contas que ele alcança saem de `GET /me/assigned_instagram_accounts` (`instagram_basic`).
- O ID da conta também sai de `GET /<PAGE_ID>?fields=instagram_business_account`.
- A conta precisa ser profissional e pública: conta privada não gera notificação de comentário nem de menção.

### Webhooks

Callback na etapa "3. Configurar webhooks" (mesmo endereço e verify token da Fase 1) e conta inscrita com `POST /<IG_ID>/subscribed_apps`. Não dá para escolher campos por conta: a conta recebe todos os campos marcados no app.

| Campo | Permissão | Uso no laboratório |
|---|---|---|
| `messages` | `instagram_manage_messages` | DMs recebidas e ecos das enviadas (`is_echo`) |
| `messaging_postbacks` | `instagram_manage_messages` | Botões e respostas rápidas |
| `message_reactions` | `instagram_manage_messages` | Reações a mensagens |
| `messaging_seen` | `instagram_manage_messages` | Leitura |
| `messaging_referral` | `instagram_manage_messages` | Origem da conversa (anúncio, link) |
| `comments` | `instagram_manage_comments` | Comentários nas mídias da conta |
| `mentions` | `instagram_manage_comments` | Menções em comentários e legendas |
| `story_insights` | `instagram_manage_insights` | Métricas de stories (só as primeiras 24h) |

- **DM:** `entry[].messaging[]` com `sender.id` (IGSID de quem escreveu), `recipient.id` (a conta), `timestamp` e `message` (`mid`, `text`, `attachments`, `is_echo`, `is_deleted`, `reply_to`). Não existe campo `message_echoes` no Instagram: o eco vem em `messages` com `is_echo: true` e o `sender` é a própria conta. Desde 27/04/2026 o anexo `share` virou `ig_post`; há também `message_edit`.
- **Comentário:** `entry[].changes[]` com `field: comments` e `value` com `from.id` (IGSID), `from.username`, o ID do comentário, `parent_id`, `text`, `media.id` e `media.media_product_type`. A documentação do login do Facebook chama o ID de `comment_id`; o exemplo do painel na v27.0 usa `id` e traz também `from.self_ig_scoped_id`. Aceitar os dois nomes.
- **Eventos de teste do painel:** o botão "Teste" manda até os campos de mensagem no formato `changes[]` (`field: messages`, `value` com `sender`, `recipient`, `timestamp` e `message`), não em `messaging[]`. O handler precisa aceitar os dois formatos para os testes do painel servirem.

### Mensagens (Direct)

- Envio: `POST /<IG_ID>/messages` com `recipient.id` = IGSID (a confirmar no teste; o caminho alternativo está no ADR 0008). Texto até 1000 bytes.
- Janela de 24h após a última mensagem da pessoa (até 7 dias após clique em anúncio Click to Direct).
- Fora da janela, só a tag `HUMAN_AGENT`, até 7 dias, para resposta de pessoa de verdade. É a única tag aceita no Instagram e depende do recurso Human Agent.
- Pré-requisito no app do Instagram da conta: Configurações > Mensagens e respostas a stories > Controles de mensagens > Ferramentas conectadas > Permitir acesso às mensagens. Sem isso, a API devolve `(#200) The account owner has disabled access to Instagram Direct Messaging Outside of Instagram App`.

### Comentários

- Listar: `GET /<MEDIA_ID>/comments`. Responder: `POST /<COMMENT_ID>/replies` com `message`. Ocultar: `POST /<COMMENT_ID>` com `hide=true`. Apagar: `DELETE /<COMMENT_ID>` (só em mídia da própria conta).
- Permissões: `instagram_basic` e `instagram_manage_comments`. Com o login do Facebook, a Meta pede também `pages_read_engagement` e, quando o papel na Página vem do portfólio (é o caso do usuário do sistema), `ads_read` ou `ads_management`. Se a moderação der erro de permissão, adicionar `ads_read`.
- **Resposta privada** (DM a partir de um comentário): `POST /<IG_ID>/messages` com `recipient.comment_id`. Uma única mensagem, em até 7 dias do comentário; a conversa só continua se a pessoa responder, e aí dentro de 24h. Limite de 750 chamadas por hora por conta. Precisa de `instagram_manage_messages`.

### Publicação

- Duas etapas: criar o container com `POST /<IG_ID>/media` e publicar com `POST /<IG_ID>/media_publish` (`creation_id`).
- Imagem só JPEG, por `image_url`; vídeo por `video_url` com `media_type` `REELS`, `VIDEO` ou `STORIES`. Carrossel: até 20 containers filhos com `is_carousel_item=true` e um container `CAROUSEL` com `children`.
- **A mídia precisa estar numa URL pública**, porque a Meta baixa o arquivo. A exceção é vídeo por upload resumível em `rupload.facebook.com`.
- Status do container: `GET /<CONTAINER_ID>?fields=status_code` (`IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`, `PUBLISHED`). Consultar uma vez por minuto, por até 5 minutos. Container não publicado expira em 24h.
- Limite: `GET /<IG_ID>/content_publishing_limit`. A documentação cita 50 e 100 publicações por 24h em páginas diferentes; vale o número que a API devolver.
- Novidade de 22/06/2026: parâmetro `is_ai_generated`.

## Modo de desenvolvimento: quem gera eventos

- Com acesso padrão (sem App Review), a API só funciona com pessoas que têm função no app. A conta pessoal usada nos testes precisa de função no app e do papel de Testador do Instagram, aceito no próprio Instagram.
- A documentação de webhooks diz que o app precisa estar publicado (Live) para entregar notificações de usuários do app, mesmo sem App Review. O app ainda não está publicado. Decisão em aberto em [meta.md](meta.md).
- **Comentários por webhook exigem acesso avançado**, que só vem com App Review. A resposta privada no Instagram também lista acesso avançado como requisito. Para app que atende só a própria empresa, a Meta diz que o App Review não é necessário, mas sem ele esses dois recursos ficam de fora.
- Plano para não depender do App Review: ler comentários por consulta periódica (tarefa do Huey sobre as mídias recentes) e usar o botão "Testar" do painel para validar o formato do webhook.

## Passo a passo no painel

Feito em 06/11/2026 pelo Chrome de depuração (etapas comuns em [meta.md](meta.md)):

1. **Permissões:** caso de uso "API do Instagram" > Permissões e recursos > "Adicionar" em cada permissão e recurso da tabela abaixo. Quando a permissão existe em outro caso de uso, o painel avisa "afetará outros casos de uso" e pede confirmação. `ads_read` fica para quando a moderação de comentários pedir.
2. **Webhook:** aba "API setup with Unified login" > "3. Configurar webhooks": callback e verify token da Fase 1, "Verificar e salvar" e, na tabela "Campos do webhook" que aparece em seguida, ligar o interruptor "Assinar" de cada campo.
3. **Inscrição da conta:** `POST /<IG_ID>/subscribed_apps` com `subscribed_fields` iguais aos do painel, com o token do usuário do sistema. O comando de conferência do laboratório vai repetir e conferir isso.

Falta:

4. **Testador:** convite enviado em 07/11/2026 para a conta pessoal de testes (Funções do app > Funções > Adicionar pessoas > "Testador do Instagram"). Falta aceitar no Instagram dessa conta: Configurações > Apps e sites > Convites de testador.
5. **Acesso às mensagens:** se algum envio devolver o erro 200 citado acima, ligar "Permitir acesso às mensagens" no app do Instagram da @brave2grow.

## Plano de implementação (`apps/instagram`)

Ordem e dependências da fase em [meta.md](meta.md).

1. **Conferência (`instagram_check`):** confirma que o token alcança a conta (`/me/assigned_instagram_accounts`), mostra permissões faltando, testa o acesso às mensagens (erro 200 acima), inscreve a conta (`subscribed_apps`) e mostra o limite de publicação.
2. **Recebimento:** handler da rota `instagram` do provedor `meta`, separando `messaging[]` (DM) de `changes[]` (comentários e menções).
   - DM vira `Message` de entrada, idempotente pelo `mid`, na conversa do contato com a conta, e atualiza `last_inbound_at` (janela de 24h). Ecos (`is_echo`) de mensagens enviadas pelo app do Instagram viram `Message` de saída, para o histórico ficar completo. Edição e exclusão atualizam a mensagem.
   - Contato e `ChannelIdentity` pelo IGSID, com `account_id` = ID da conta. Comentário traz o `username`, que vai para `handle` e `Contact.instagram_handle`. O vínculo com contatos de outros canais fica para o F06 (CLAUDE.md, seção 13), com confirmação do contato.
   - Comentário vira o evento `instagram.comment_received` (idempotente pelo `comment_id`); menção vira `instagram.mention_received`.
   - Palavra de saída (`SAIR`, `PARAR`, `STOP`) em DM revoga os consentimentos do Instagram, como no WhatsApp.
3. **Envio de DM:** `send_message` único, com as travas do laboratório: janela de 24h, `HUMAN_AGENT` só por ação humana na tela, `Consent` e limite semanal para contato proativo, dry-run e allowlist. Usa o `GraphClient.post` sem repetição da Fase 2.
4. **Comentários:** responder, ocultar e resposta privada. Gatilho por palavra-chave (jornada 1 do CLAUDE.md): comentário com a palavra gera resposta privada com o convite para o WhatsApp (link wa.me com código `[B2G-XXXXX]`). Enquanto não houver acesso avançado, os comentários entram pela consulta periódica.
5. **Publicação:** imagem, carrossel e Reels pelo container, com o status acompanhado por tarefa do Huey e o limite conferido antes. Toda publicação com `dry_run` e `LAB_DRY_RUN`.
6. **Insights:** comando que lê métricas da conta e das mídias.
7. **Tela:** conversas do Instagram junto das do WhatsApp (as telas da Fase 2), até a caixa de entrada unificada da Fase 8.

## Permissões

| Permissão ou recurso | Uso | Situação |
|---|---|---|
| `instagram_basic` | Perfil, mídias, contas do usuário do sistema | no token |
| `instagram_manage_messages` | Direct e resposta privada | no token |
| `instagram_manage_comments` | Comentários e menções | no token |
| `instagram_content_publish` | Publicação | no token |
| `instagram_manage_insights` | Insights | no token |
| Human Agent | Tag `HUMAN_AGENT` (7 dias) | adicionado (recurso, acesso padrão) |
| Business Asset User Profile Access | Nome e foto de quem interage | adicionado (recurso, acesso padrão) |
| `ads_read` | Só se a moderação de comentários exigir | sob demanda |

Acesso avançado (App Review) só seria pedido para receber comentários por webhook e para a resposta privada, se a consulta periódica não bastar.

## O que funcionou

- 06/11/2026: permissões adicionadas, token novo com acesso à conta, webhook verificado e conta inscrita no app. Eventos de teste de `comments` e `messages` chegaram ao servidor assinados, com rota `instagram`.
- Ainda sem evento real de pessoa (falta o aceite do testador e, pela documentação, o app publicado).

## Limitações encontradas

Ainda sem teste real. Limitações conhecidas pela documentação: comentários por webhook só com acesso avançado, webhooks só com app publicado, mídia de publicação só por URL pública, conta privada não recebe notificação de comentário.

## Custos observados

Nenhum ainda. A Graph API não cobra por chamada (meta.md).

## Próximos passos

Os do plano acima, a começar pelo passo a passo no painel e pelo recebimento.
