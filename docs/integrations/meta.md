# Meta (Business, Graph API e webhooks)

**Versão da API:** Graph API v27.0 (`META_GRAPH_API_VERSION`) desde o fechamento da Fase 2, em 06/11/2026. É a versão padrão dos campos de webhook do app no painel e a dos exemplos atuais do WhatsApp; a tabela de versões da Graph API ainda listava a v26.0 (lançada em 29/07/2026) como a mais recente, mas a v27.0 respondeu normalmente. A v25.0 fica disponível até 29/07/2028.
**Última revisão:** 06/11/2026 (Fase 1 concluída)

Base comum para WhatsApp, Instagram e Facebook. Threads usa API própria (graph.threads.net) e entra na Fase 4.

O passo a passo detalhado, tela por tela, está em [docs/treinamento/configurar-meta-facebook-instagram.md](../treinamento/configurar-meta-facebook-instagram.md). Abaixo, o resumo do que existe e de como o laboratório usa.

## O que está configurado

- **Portfólio:** "Brave2Grow Tecnologia", com verificação da empresa concluída (veio junto com o Meta Verified para empresas, contratado em 03/11/2026). Administrado pelo usuário do Facebook "Bravo To Grow", um usuário operacional da Brave2Grow.
- **App:** "B2G Integrations Lab", criado em 06/11/2026 no sistema novo de casos de uso, ligado ao portfólio, ainda não publicado (modo de desenvolvimento). Casos de uso: WhatsApp ("Conectar-se com clientes pelo WhatsApp"), Página ("Gerenciar tudo na sua Página"), Instagram ("Gerenciar mensagens e conteúdo no Instagram") e Messenger ("Interagir com os clientes no Messenger"). App ID e App Secret em `META_APP_ID` e `META_APP_SECRET`.
- **Usuário do sistema:** "B2G Lab API", função Admin. Ativos atribuídos: Página Brave2Grow (acesso total), app B2G Integrations Lab (gerenciar app) e Instagram @brave2grow (conteúdo, mensagens, atividade da comunidade e insights).
- **Token do usuário do sistema:** sem expiração, em `META_SYSTEM_USER_TOKEN` e criptografado em `IntegrationCredential` (`meta` / `system_user`) pelo `meta_check`. Permissões: `business_management`, `pages_show_list`, `pages_manage_metadata`, `pages_messaging`, `whatsapp_business_management`, `whatsapp_business_messaging` (e `public_profile`, automática).
- **Webhook:** configurado no caso de uso do Messenger (Configurações da API do Messenger > 1. Configure webhooks) com callback `https://<domínio do servidor>/webhooks/meta/` (EC2 `b2g-labs-meta`, ADR 0005; domínio no `deploy.py` local) e o `META_WEBHOOK_VERIFY_TOKEN`. Nenhum campo assinado ainda.
- **WhatsApp:** a conta que existe no portfólio é do tipo "Aplicativo WhatsApp Business" (o número usado no app comum). Ela não vai para `WHATSAPP_BUSINESS_ACCOUNT_ID`: a Fase 2 começa pelo número de teste, e a migração do número real depende da decisão sobre coexistência (CLAUDE.md, 5.6).

## Como o laboratório integra

- **Webhook** (`apps/meta_business/webhook.py`): provedor `meta` na esteira da Fase 0 (ADR 0003).
  - Assinatura `X-Hub-Signature-256`: HMAC-SHA256 do corpo bruto com o App Secret, prefixo `sha256=`.
  - Handshake: GET com `hub.mode=subscribe`, `hub.verify_token` e `hub.challenge`; a resposta é o challenge em texto puro.
  - Rota: campo `object`. O handler de `whatsapp_business_account` existe desde a Fase 2 ([whatsapp.md](whatsapp.md)); os de `instagram` e `page` chegam na Fase 3. Até lá essas entregas ficam como "ignoradas", com o payload guardado.
  - A Meta manda lotes de até 1000 atualizações e reenvia por até 36 horas sem confirmação. A deduplicação usa o hash do corpo, e os IDs externos únicos de `Message` e `Event` cobrem o resto.
- **Graph API** (`apps/meta_business/client.py`):
  - Token no cabeçalho `Authorization`, nunca na URL; o log do `httpx` fica em WARNING para não gravar URLs.
  - `appsecret_proof` (HMAC-SHA256 do token com o App Secret) em toda chamada com token de usuário ou de sistema. Isso permite ligar "Exigir segredo do app" no painel.
  - Erros 1 e 2, HTTP 5xx e falhas de rede: novas tentativas com espera de 1 s, 2 s e 4 s.
  - Limite de volume (4, 17, 32, 341, 613, 80000 a 80014, HTTP 429): respeita `estimated_time_to_regain_access` do `X-Business-Use-Case-Usage`. Se a espera passar de 30 s, desiste e devolve `retry_after` para a tarefa do Huey reagendar.
  - Autenticação e permissão (10, 102, 190, 200 a 299): sem nova tentativa; gerar ou corrigir o token.
  - Todo erro é registrado com status, code, subcode, `fbtrace_id` e a resposta completa.
- **Token do System User** (`apps/meta_business/services.py`): o `debug_token` é chamado com o token de app (`app_id|app_secret`). `expires_at = 0` significa que não expira. Há relatos de tokens de System User expirando em 60 a 90 dias, por isso a validade fica registrada em `IntegrationCredential` e o painel avisa 7 dias antes.
- **Conferência:** `python manage.py meta_check` valida o token, mostra validade e permissões e diz, para cada ativo do `.env`, se o token o alcança. Quando não alcança, separa os dois motivos: o token não tem nenhuma permissão do ativo (adicionar ao caso de uso e gerar token novo) ou tem, mas ela não vale para aquele ativo (atribuir o ativo ao usuário do sistema).

## Permissões

| Permissão | Uso | Fase | No token |
|---|---|---|---|
| `business_management` | Ativos do Business Portfolio | 1 | sim |
| `whatsapp_business_management` | WABA, números, templates, assinatura de webhooks | 2 | sim |
| `whatsapp_business_messaging` | Enviar e receber mensagens | 2 | sim |
| `pages_show_list` | Listar as Páginas | 3 | sim |
| `pages_manage_metadata` | Assinar webhooks da Página | 3 | sim |
| `pages_messaging` | Messenger | 3 | sim |
| `pages_read_engagement` | Posts, seguidores e engajamento | 3 | não |
| `pages_manage_posts` | Publicar na Página | 3 | não |
| `pages_manage_engagement` | Responder e curtir comentários | 3 | não |
| `pages_read_user_content` | Ler comentários de usuários | 3 | não |
| `read_insights` | Insights da Página | 3 | não |
| `instagram_basic` | Perfil e mídias | 3 | não |
| `instagram_manage_comments` | Comentários | 3 | não |
| `instagram_manage_messages` | Direct | 3 | não |
| `instagram_content_publish` | Publicação | 3 | não |
| `instagram_manage_insights` | Insights | 3 | não |

Observações:
- No sistema novo de casos de uso, a tela "Gerar token" só oferece as permissões já adicionadas ao caso de uso. As que estão como "não" aparecem com o botão "Adicionar" em Painel > Personalizar caso de uso > Permissões e recursos. Adicionar e gerar um token novo na Fase 3.
- O app está em modo de desenvolvimento: funciona com os ativos do próprio portfólio e com quem tem função no app. Para dados de terceiros, publicar o app e passar pela análise (App Review).
- A família `instagram_business_*` (login do Instagram) não está disponível para este app: o Instagram usa o login unificado, com as permissões `instagram_*` e o token do usuário do sistema (ADR 0008).
- Uma permissão sem uso por 90 dias precisa ser concedida de novo.

## Fase 3: preparação (Instagram e Página)

A Fase 3 é desenvolvida no branch `fase-3-instagram-facebook`, criado do `main` numa worktree própria (`../b2g-lab-fase-3`), em paralelo à Fase 2, que ainda não entrou no `main`. Detalhes de cada canal em [instagram.md](instagram.md) e [facebook.md](facebook.md).

### Etapas comuns no painel

1. **Permissões nos casos de uso:** as listas estão em instagram.md e facebook.md.
2. **Token novo:** Configurações do negócio > Usuários do sistema > "B2G Lab API" > Gerar token, marcando as 6 permissões atuais mais as novas. Atualizar `META_SYSTEM_USER_TOKEN` no `.env` local e no do servidor, ao mesmo tempo, porque o WhatsApp da Fase 2 usa o mesmo token, e rodar `meta_check`. Revogar o token antigo só depois de conferir o novo.
3. **Funções para os testes:** a conta pessoal do Facebook do Danilo como Testador do app (Funções do app > Funções) e o @ pessoal do Instagram como Testador do Instagram. Com acesso padrão, quem não tem função no app não gera evento nem recebe mensagem.
4. **Publicação do app (decisão em aberto):** a documentação de webhooks do Instagram exige o app publicado (Live) para entregar notificações de usuários do app, mesmo sem App Review. Publicar pede, em Configurações do app > Básico, URL da política de privacidade, URL ou instruções de exclusão de dados, ícone e categoria. Com acesso padrão, o app publicado continua servindo só quem tem função nele. A Meta recomenda publicar no fim do desenvolvimento; a proposta é publicar quando o recebimento da Fase 3 estiver no servidor.

### Ordem do trabalho

1. Painel, token e comandos de conferência (`instagram_check` e `facebook_check`).
2. Recebimento: handlers das rotas `instagram` e `page`. Não depende da Fase 2.
3. Envio de DM e Messenger, comentários e resposta privada. Depende do `GraphClient.post` sem repetição da Fase 2: antes deste passo, trazer o `main` com a Fase 2 para o branch da Fase 3.
4. Publicação, insights e telas.

### Dependências e conflitos com a Fase 2

- A Fase 3 vai usar do branch da Fase 2: `GraphClient.post` com `idempotent=False`, a fixture `meta_post` de `tests/conftest.py`, as telas de conversa e o motor de fluxo (ADR 0007).
- Arquivos alterados pelas duas fases, com conflito simples esperado na junção: `config/settings/base.py` (`INSTALLED_APPS`), `config/urls.py`, `templates/base.html` (menu), `tests/conftest.py`, `tests/test_meta_webhook.py`, `.env.example` e a linha "Rota" deste arquivo.

### Decisões em aberto

- **Allowlist para Instagram e Messenger:** `LAB_ALLOWED_RECIPIENTS` hoje recebe telefones e emails. Proposta: aceitar também `instagram:<IGSID>` e `facebook:<PSID>`, copiados da tela de conversa depois da primeira mensagem do Danilo. A comparação atual já trata esse formato como texto, mas o código deve reconhecer o prefixo antes de tentar ler um telefone.
- **Mídia para publicar:** o Instagram e as fotos da Página exigem URL pública. Opções: uma pasta de mídia servida pelo Caddy da EC2 ou um bucket S3.
- **App Review:** pedir acesso avançado só se a consulta periódica de comentários não bastar para a jornada "comentário vira conversa".

## O que funcionou

- 03/11/2026: código da Fase 1 pronto e coberto por testes com a Graph API mockada.
- 03/11/2026: handshake validado pela URL pública do túnel (HTTPS do trycloudflare até o runserver da 8602).
- 06/11/2026: app, usuário do sistema e token criados; `meta_check` confirmou o token válido, sem expiração, do app certo, alcançando a Página.
- 06/11/2026: "Verificar e salvar" do webhook aceito pela Meta. O evento de teste do campo `messages` (botão "Teste" > "Enviar para servidor") chegou assinado: entrega com `signature_valid=True`, rota `page` e payload bruto guardado.
- Uma chamada sem assinatura válida foi gravada como `rejected` e respondida com 403, como esperado.
- 06/11/2026: callback trocado para a EC2 (`deploy.py`, certificado Let's Encrypt via Caddy, num domínio provisório do sslip.io). "Verificar e salvar" aceito e o evento de teste chegou no servidor assinado, com rota `page`, e foi processado pelo Huey do servidor (status `ignored`, sem handler de `page` até a Fase 3).
- 06/11/2026: servidor restrito a um único domínio próprio, com certificado emitido pelo certbot (docs/deploy/ec2.md). Callback atualizado; a Meta refez o handshake (GET com `hub.mode`, resposta 200) e o "Teste" do campo `messages` (botão "Enviar para servidor v27.0") chegou assinado, com rota `page`.

## Limitações encontradas

- A validação da Fase 1 usou o túnel rápido do cloudflared. Ele muda de URL a cada execução, expõe o runserver inteiro (com `DEBUG=True`) e passa o conteúdo pela Cloudflare. Por isso foi abandonado: webhooks reais só na EC2 (ADR 0005).
- O cadastro no Meta for Developers travou por dias: o código do email era recusado, e no Chrome de depuração (perfil dedicado da porta 9997) aparecia "Você não pode fazer essa alteração no momento. Notamos que você está usando um dispositivo diferente". Há relatos parecidos no fórum da Meta desde agosto de 2026. Destravou depois de completar o contato do perfil no portfólio e de contratar o Meta Verified.
- Antes de o email e o WhatsApp do perfil no portfólio serem confirmados, a opção "Criar um novo ID do app" (Configurações do negócio > Apps > Adicionar) ficava desabilitada.
- O SMS de confirmação da Meta parou de chegar depois de várias tentativas seguidas. O código pelo WhatsApp chegou na hora.
- Ver o App Secret exige digitar de novo a senha do Facebook.
- A Meta recusou o nome "B2G Lab System User" para o usuário do sistema ("invalid System User name"); "B2G Lab API" foi aceito.
- O túnel também se mostrou instável com a VPN Avast SecureLine ativa (porta TCP 7844 bloqueada e conexão QUIC caindo por inatividade).

## Custos observados

- A Graph API não cobra por chamada; valem os limites de volume.
- Meta Verified para empresas: assinatura mensal contratada em 03/11/2026 (valor na fatura da Meta).
- Custos de mensagens do WhatsApp ficam em `whatsapp.md` (Fase 2).

## Próximos passos

- Fase 2: número de teste do WhatsApp, handler de `whatsapp_business_account` e assinatura do campo `messages`.
- Troca de `META_GRAPH_API_VERSION` para v27.0: feita no fechamento da Fase 2.
- Fase 3: seguir a seção "Fase 3: preparação" acima (permissões, token novo, funções de teste, publicação do app, webhooks de `page` e `instagram`).
