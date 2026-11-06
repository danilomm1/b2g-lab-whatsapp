# ADR 0008: Instagram pela configuração com login unificado

**Status:** aceito
**Data:** 2026-11-06

## Contexto

A API do Instagram tem três configurações (Instagram Platform > Overview, consultado em 06/11/2026):

| Configuração | Host | Token | Conta | Permissões |
|---|---|---|---|---|
| Login unificado (recomendada para integrações novas) | `graph.facebook.com` | token de usuário do sistema | ID da conta profissional, explícito | `instagram_*` |
| Login do Instagram (integrações existentes) | `graph.instagram.com` | token de usuário do Instagram | ID da conta ou `/me` | `instagram_business_*` |
| Login do Facebook (integrações existentes ligadas a Página) | `graph.facebook.com` | token de usuário ou de Página | ID da Página ou `/me` | `instagram_*` e de Página |

A Meta diz que recursos novos da API do Instagram saem só para o login unificado e não anunciou data de fim para as outras duas.

No app "B2G Integrations Lab", caso de uso "API do Instagram", o painel mostrou em 06/11/2026: "A configuração da API com login do Instagram não está disponível para apps mais recentes. Seu app usa a configuração da API com login unificado." A tela oferece token de usuário do sistema (SUAT), sem expiração, com a conta do Instagram como ativo obrigatório.

## Decisão

- O Instagram usa o login unificado: Graph API em `graph.facebook.com`, na versão de `META_GRAPH_API_VERSION`, com o token do usuário do sistema "B2G Lab API", o mesmo da Página e do WhatsApp.
- Permissões `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `instagram_content_publish` e `instagram_manage_insights`. As `instagram_business_*` não são pedidas.
- A conta é `INSTAGRAM_BUSINESS_ACCOUNT_ID`. Com esse token, `/me` é o usuário do sistema, não a conta; as contas alcançadas aparecem em `GET /me/assigned_instagram_accounts`.
- Quem escreve ou comenta é identificado pelo IGSID, guardado em `ChannelIdentity` com `account_id` igual ao ID da conta.
- Webhook do objeto `instagram` configurado na etapa "Configurar webhooks" da aba do login unificado, com o callback único da Fase 1, e conta inscrita por `POST /<IG_ID>/subscribed_apps`. DM sai por `POST /<IG_ID>/messages`.
- Sem botão de login para terceiros nesta fase. A configuração do login do Facebook para Empresas ("Criar nova configuração") só faz sentido quando houver contas de clientes.

## Consequências

- Um único token e um único cliente (`apps/meta_business/client.py`) atendem Página, Messenger, Instagram e WhatsApp.
- A documentação do login unificado descreve o token obtido pelo fluxo de login do cliente (Business Integration System User Access Token). O laboratório usa o token gerado em Configurações do negócio > Usuários do sistema. A primeira validação da Fase 3 confirma se ele alcança conta, mensagens e assinatura de webhook. Se as mensagens não funcionarem, o caminho alternativo é o do login do Facebook: token de Página, `POST /<PAGE_ID>/messages` e webhook do Instagram pelas configurações do Messenger.
- O modo de desenvolvimento limita o teste a pessoas com função no app, e a Meta exige app publicado para entregar webhooks de usuários do app. Comentários por webhook exigem acesso avançado (App Review). Detalhes em docs/integrations/instagram.md.
