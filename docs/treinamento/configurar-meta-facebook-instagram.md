# Como configurar a Meta, o Facebook e o Instagram para integrações

Guia passo a passo, tela por tela, para preparar uma empresa na Meta antes de integrar Página do Facebook, Instagram, Messenger e WhatsApp a um sistema próprio. Serve de roteiro para o vídeo de treinamento.

**Baseado em:** configuração real da Brave2Grow, feita entre 03/11/2026 e 06/11/2026.
**Atenção:** a Meta muda nomes de menus e telas com frequência, e a interface pode alternar entre português e inglês. Quando a tela apareceu em inglês, o nome original vai entre parênteses.

## O que você vai ter no final

| Item | Para que serve |
|---|---|
| Portfólio empresarial com contato completo e verificado | É a "empresa" dentro da Meta: reúne Página, Instagram, WhatsApp, apps e pessoas |
| Conta no Meta for Developers | Permite criar apps |
| App com casos de uso | É a "porta de entrada" do seu sistema na Meta |
| App ID e App Secret | Identificam o app e assinam as mensagens que a Meta envia |
| Usuário do sistema com ativos atribuídos | Um "funcionário robô" do portfólio, que não depende da conta de nenhuma pessoa |
| Token do usuário do sistema | A chave que o seu sistema usa para chamar a API |
| Webhook verificado | O endereço onde a Meta avisa o seu sistema sobre mensagens, comentários e eventos |

## Glossário rápido

- **Portfólio empresarial (Business Portfolio):** o antigo Business Manager. Fica em business.facebook.com.
- **Ativo:** qualquer coisa que pertence ao portfólio: Página, conta do Instagram, conta do WhatsApp, app, conta de anúncios.
- **App:** cadastro do seu sistema no Meta for Developers (developers.facebook.com).
- **Caso de uso:** o "pacote" de permissões que o app pode pedir (por exemplo, "Gerenciar mensagens e conteúdo no Instagram").
- **Usuário do sistema (System user):** usuário técnico do portfólio, usado por servidores. Não faz login e não sai da empresa quando alguém sai.
- **Token de acesso:** senha longa que o sistema envia em cada chamada à API.
- **Webhook:** endereço HTTPS do seu sistema que a Meta chama quando algo acontece.
- **Verify token:** texto combinado entre você e a Meta para provar que o endereço do webhook é seu.

## Antes de começar

- Uma conta do Facebook que seja administradora do portfólio, com a senha à mão. Algumas telas pedem a senha de novo.
- Página do Facebook da empresa e conta do Instagram profissional (Empresa ou Criador) já ligadas ao portfólio.
- Acesso ao email da empresa e ao WhatsApp da empresa, para receber códigos de confirmação.
- De preferência, o navegador ou celular que você já usa no dia a dia com essa conta. A Meta bloqueia algumas alterações em "dispositivos novos".
- Para o webhook: o sistema rodando num servidor com endereço HTTPS público (no laboratório, uma EC2 na AWS com um subdomínio da empresa).

## Mapa das etapas

| Etapa | Onde | Tempo aproximado |
|---|---|---|
| 1. Conferir e completar o portfólio | business.facebook.com > Configurações | 15 min |
| 2. Cadastrar-se no Meta for Developers | developers.facebook.com | 10 min (pode travar por dias, ver problemas) |
| 3. Criar o app | developers.facebook.com > Meus apps | 5 min |
| 4. Pegar App ID e App Secret | Painel do app > Configurações do app > Básico | 2 min |
| 5. Criar o usuário do sistema e atribuir ativos | Configurações do negócio > Usuários do sistema | 10 min |
| 6. Gerar o token | Usuários do sistema > Gerar token | 5 min |
| 7. Liberar mais permissões no app | Painel do app > Personalizar caso de uso | 5 min por caso de uso |
| 8. Configurar e testar o webhook | Painel do app > caso de uso Messenger | 10 min |

---

## Etapa 1: conferir e completar o portfólio empresarial

### 1.1 Abrir as configurações do portfólio

1. Acesse **business.facebook.com**.
2. No canto inferior esquerdo, clique na engrenagem **Configurações**.
3. No topo aparece o nome do portfólio (no nosso caso, "Brave2Grow Tecnologia"). Se você administra mais de um, confira se é o certo.

O menu lateral das configurações tem estes grupos:
- **Informações da empresa**
- **Usuários:** Pessoas, Parceiros, Usuários do sistema
- **Contas:** Páginas, Contas de anúncios, Grupos de ativos de negócios, Apps, Contas do Instagram, Contas do WhatsApp, Contas de mensagens, Contas do Threads
- **Fontes de dados**, **Pedidos**, **Adequação e segurança para marcas**, **Integrações**, **Cobrança e pagamentos**, **Meta Verified**, **Central de Segurança**, **Notificações**, **Guia de configuração**

### 1.2 Informações da empresa

Menu **Informações da empresa**. Confira:
- **Identificação do portfólio empresarial:** o número do portfólio (guarde, ele aparece em várias URLs).
- **Status de verificação da empresa:** "Não verificada" ou "Verificação da empresa concluída".
- **Detalhes da empresa:** razão social, endereço, telefone comercial e site. Preencha, porque a verificação usa esses dados.

### 1.3 Informações de contato do perfil (passo que destrava a criação de apps)

Ainda em **Informações da empresa**, role até **Informações de contato do perfil**. São os contatos da pessoa logada dentro desse portfólio:

| Campo | Botão | Como confirma |
|---|---|---|
| Email | "Adicionar endereço de email" | Código enviado por email, válido por 60 minutos |
| Número de celular | "Adicionar número de celular" | Código por SMS, válido por 60 minutos |
| WhatsApp | "Adicionar número do WhatsApp" | Código enviado pelo próprio WhatsApp, válido por 60 minutos |

Passo a passo de cada um:
1. Clique no botão do campo.
2. Digite o email ou escolha o país (Brasil, +55) e digite o número.
3. Deixe **desmarcadas** as caixas de comunicações de marketing, se não quiser recebê-las.
4. Clique em **Continuar**.
5. Digite o código recebido e clique em **Enviar**.

Dicas:
- Use só o código mais recente. Pedir de novo invalida os anteriores.
- Se o SMS não chegar depois de algumas tentativas, a Meta pode estar segurando os envios. Confirme pelo campo **WhatsApp**: o código chega na hora.
- No nosso caso, enquanto email e WhatsApp estavam vazios, a opção "Criar um novo ID do app" (Etapa 3) ficava desabilitada. Depois de confirmar os dois, ela foi liberada.

### 1.4 Conferir os ativos

| Menu | O que conferir |
|---|---|
| Contas > **Páginas** | A Página está no portfólio. Clique nela: aparece a **Identificação** (ID da Página) e quem tem acesso |
| Contas > **Contas do Instagram** | A conta está no portfólio. A **Identificação** (começa com 1784...) é o ID usado pela API. Pode aparecer "Login necessário" para ajustes extras |
| Contas > **Contas do WhatsApp** | Veja o tipo da conta. "Aplicativo WhatsApp Business" significa que o número está no app comum. Antes de levar esse número para a API, confira as opções de coexistência no painel da Meta: um número só da API pode deixar de funcionar no app |
| Contas > **Apps** | Lista os apps do portfólio. Vazio no início |
| Usuários > **Usuários do sistema** | Vazio no início |

### 1.5 Segurança e verificação

- **Central de Segurança:** mostra recomendações (autenticação de dois fatores, chaves de acesso, administrador secundário) e o card **Verificação da empresa**, com o botão "Iniciar verificação" quando a empresa estiver qualificada.
- **Meta Verified:** assinatura paga com selo de verificado, proteção contra falsificação e suporte por agente. No nosso caso, contratar o Meta Verified para empresas trouxe junto a verificação da empresa, e a análise levou até 48 horas.

**Cena sugerida para o vídeo:** mostrar o menu lateral inteiro, depois Informações da empresa com o status de verificação e a confirmação do WhatsApp com o código chegando no celular.

---

## Etapa 2: cadastro no Meta for Developers

1. Acesse **developers.facebook.com** logado com a mesma conta do Facebook.
2. Se no canto superior direito aparecer **Começar** (em vez de "Meus apps"), a conta ainda não é desenvolvedora. Clique em **Começar**.
3. O cadastro tem estas etapas:
   - **Register:** texto de boas-vindas e o aviso "Ao continuar, você concorda com os Termos da Plataforma da Meta e as Políticas do Desenvolvedor". Clique em **Continuar**.
   - **Verify account:** confirmação por SMS no celular da conta.
   - **Contact info:** confirma o email de contato com um código. "Atualizar email" troca o endereço.
   - **About you:** escolha o perfil que mais se parece com você (por exemplo, desenvolvedor ou dono de empresa).
4. Pronto: o canto superior direito passa a mostrar **Meus apps**.

Problemas que tivemos aqui (detalhes na tabela do fim):
- "Você não pode fazer essa alteração no momento. Notamos que você está usando um dispositivo diferente do que costuma usar". Use o navegador ou celular de sempre.
- Código do email recusado repetidas vezes, inclusive em outros aparelhos.
- "Não foi possível enviar o email" ao tentar usar um email que já está na conta. Essa tela serve para **adicionar** um email novo.

O que resolveu no nosso caso: completar o contato do perfil no portfólio (Etapa 1.3), contratar o Meta Verified e esperar a análise. Depois disso, o cadastro passou.

---

## Etapa 3: criar o app

### 3.1 Começar

1. Em developers.facebook.com, clique em **Meus apps**.
2. Clique em **Criar aplicativo**.
3. Pode aparecer o aviso "Há uma nova maneira de criar apps com a Meta". Clique em **Criar app** dentro do aviso para seguir.

O assistente tem 5 etapas, mostradas no topo: **Detalhes do app**, **Casos de uso**, **Empresa**, **Requisitos** e **Visão geral**.

### 3.2 Detalhes do app

- **Nome do app:** até 30 caracteres. Exemplo: "B2G Integrations Lab". Dá para mudar depois.
- **Email de contato do app:** a Meta usa para avisos de política e recuperação. Atenção: o campo pode vir preenchido com o celular da conta. Apague e coloque o email da empresa.
- Clique em **Avançar**.

### 3.3 Casos de uso

1. Em **Filtrar por**, escolha **Tudo (20)** para ver todas as opções.
2. Marque os casos de uso do seu projeto. No nosso caso:
   - **Conectar-se com clientes pelo WhatsApp** (exige portfólio empresarial)
   - **Gerenciar tudo na sua Página**
   - **Gerenciar mensagens e conteúdo no Instagram**
   - **Interagir com os clientes no Messenger from Meta**
3. Confira no rodapé: "4 casos de uso adicionados".
4. Clique em **Avançar**.

Observações:
- Alguns casos de uso não podem ser combinados. Os incompatíveis ficam acinzentados depois que você marca outro.
- **Acessar a API do Threads** pode ser adicionado depois, pelo painel do app.
- A opção **Outro** (experiência antiga, com escolha de tipo de app) está sendo desativada. Evite.

### 3.4 Empresa

- Pergunta "A qual portfólio empresarial você quer conectar o app?".
- Marque o portfólio da empresa. Ele aparece com o status, por exemplo "Verificação da empresa concluída".
- Clique em **Avançar**.

### 3.5 Requisitos e Visão geral

- **Requisitos:** lista o que falta para publicar. No início, "Nenhum requisito identificado". Clique em **Avançar**.
- **Visão geral:** resumo com nome, email, casos de uso e portfólio. No rodapé: "Ao continuar, você aceita os Termos da Plataforma da Meta e as Políticas do Desenvolvedor".
- Clique em **Criar aplicativo**.

Resultado: abre o **Painel** do app, com o nome no topo e o status "Não publicado". O número na URL (developers.facebook.com/apps/**NÚMERO**/dashboard) é o ID do app.

**Cena sugerida para o vídeo:** a lista completa de casos de uso, marcando os quatro, e o resumo da Visão geral.

---

## Etapa 4: App ID e App Secret

1. No painel do app, menu lateral **Configurações do app** > **Básico**.
2. **ID do app:** número público do app.
3. **Chave secreta do aplicativo:** clique em **Mostrar**. A Meta pede a senha do Facebook ("Digite sua senha novamente"). Digite e clique em **Confirmar**.
4. Guarde os dois no arquivo de configuração do seu sistema. No laboratório, no `.env`:

```
META_APP_ID=<ID do app>
META_APP_SECRET=<chave secreta, 32 caracteres>
```

Cuidados:
- A chave secreta é uma senha. Nunca mande por chat, email ou print.
- No vídeo, borre a chave ou grave essa parte com um app de teste.

---

## Etapa 5: usuário do sistema e atribuição de ativos

### 5.1 Criar o usuário do sistema

1. Em business.facebook.com > **Configurações** > Usuários > **Usuários do sistema** (System users), clique em **Adicionar** (Add).
2. Na primeira vez aparece a **Política de Não Discriminação** em anúncios: você certifica, em nome do portfólio, que quem agir como usuário do sistema vai seguir as Políticas de Publicidade e não vai usar anúncios para discriminar. Leia e clique em **Aceito** (I accept).
3. Na tela **Criar usuário do sistema** (Create system user):
   - **Nome:** algo como "B2G Lab API". A Meta recusou "B2G Lab System User" com a mensagem "invalid System User name"; evite a expressão "System User" no nome.
   - **Função:** **Admin** ou **Funcionário** (Employee). O Admin enxerga e gerencia todos os ativos e permissões do portfólio; o Funcionário só usa o que for atribuído a ele. Escolhemos Admin para o laboratório.
   - Clique em **Criar usuário do sistema** (Create system user).
4. O usuário aparece na lista com um ID e os botões **Gerar token** (Generate token), **Revogar tokens** (Revoke tokens) e **Atribuir ativos** (Assign assets).

### 5.2 Atribuir ativos

Clique em **Atribuir ativos** (Assign assets). A janela tem três colunas: **tipo de ativo**, **ativos** e **permissões**. As permissões são chaves de liga e desliga.

| Tipo de ativo | Ativo | Permissões que usamos | Por quê |
|---|---|---|---|
| Páginas do Facebook | a Página da empresa | **Acesso total** (Full access > Everything) | Publicar, moderar, responder mensagens e assinar webhooks sem esbarrar em permissão. Mesmo com acesso total, usuários do sistema não podem "entrar como a Página" nem fazer tarefas sensíveis |
| Apps | o app criado na Etapa 3 | **Gerenciar app** (Manage app) | Permite gerar tokens desse app |
| Contas do Instagram | a conta da empresa | **Conteúdo, Mensagens, Atividade da comunidade e Insights** | O acesso total do Instagram inclui a forma de pagamento de anúncios, que não é necessária |

Passo a passo:
1. Clique no tipo de ativo (por exemplo, Páginas do Facebook).
2. Marque o ativo na coluna do meio.
3. Ligue as chaves das permissões na coluna da direita.
4. Repita para os outros tipos. O rodapé mostra o total, por exemplo "3 ativos selecionados".
5. Clique em **Atribuir ativos** (Assign assets). Aparece "3 ativos foram atribuídos". Clique em **Concluir** (Done).

---

## Etapa 6: gerar o token do usuário do sistema

1. Na tela do usuário do sistema, clique em **Gerar token** (Generate token). O assistente tem 4 passos: **Selecionar app**, **Definir validade**, **Atribuir permissões**, **Concluído**.
2. **Selecionar app** (Select app): escolha o app. Clique em **Avançar** (Next).
3. **Definir validade** (Set expiration):
   - **60 dias** (recomendado pela Meta): mais seguro, mas o sistema precisa renovar o token.
   - **Nunca** (Never): não expira; pode ser revogado a qualquer momento em "Revogar tokens". Usamos "Nunca" no laboratório.
4. **Atribuir permissões** (Assign permissions): abra o seletor e marque as permissões. Só aparecem as que já estão nos casos de uso do app. No nosso caso apareceram 6: `business_management`, `pages_manage_metadata`, `pages_messaging`, `pages_show_list`, `whatsapp_business_management` e `whatsapp_business_messaging`. O seletor mostra "6 opções selecionadas".
   - Pode aparecer o aviso "Você não é administrador deste app" (You are not an admin of this app), avisando que a lista pode estar limitada. Se faltar alguma permissão, siga a Etapa 7.
5. Clique em **Gerar token** (Generate token). O texto do rodapé avisa que isso instala o app para o usuário do sistema.
6. **Copie o token na hora**: a Meta mostra uma única vez. Guarde no `.env`:

```
META_SYSTEM_USER_TOKEN=<token, começa com EA...>
```

No vídeo, nunca mostre o token. Se ele vazar, use **Revogar tokens** e gere outro.

---

## Etapa 7: liberar mais permissões (personalizar caso de uso)

O token só pode receber permissões que o app já adicionou aos casos de uso. Para incluir, por exemplo, publicação no Instagram ou leitura de comentários da Página:

1. No painel do app, em **Personalização do app e requisitos**, clique em **Personalizar o caso de uso "..."**.
2. A tela **Personalizar caso de uso** tem, à esquerda, um seletor para trocar de caso de uso (Conectar no WhatsApp, Gerenciar Páginas, API do Instagram, Messenger from Meta) e as seções do caso escolhido, como **Permissões e recursos**.
3. Em **Permissões e recursos**, cada linha mostra a permissão, as chamadas à API, o status e a ação:
   - **Adicionar:** inclui a permissão no app.
   - **Pronto para teste:** a permissão já está no app e pode ser usada em modo de desenvolvimento.
4. Depois de adicionar, volte à Etapa 6 e gere um token novo com as permissões novas.

Permissões que o laboratório vai precisar a seguir: `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights`, `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `instagram_content_publish` e `instagram_manage_insights`.

Enquanto o app não for publicado e aprovado na análise da Meta (App Review), ele só funciona com os ativos do próprio portfólio e com quem tem função no app.

---

## Etapa 8: configurar e testar o webhook

### 8.1 Preparar o endereço

O webhook precisa de um endereço **HTTPS público**, com certificado válido, que responda à verificação da Meta. Não serve um IP puro nem `localhost`. No laboratório:
- O sistema roda num servidor na AWS (EC2) com o Caddy, que emite o certificado HTTPS sozinho.
- Um subdomínio da empresa (por exemplo, `lab.brave2grow.com`) aponta para o IP fixo do servidor, por um registro A no painel de DNS.
- O endereço do webhook é `https://<subdomínio>/webhooks/meta/`.
- O verify token é um texto aleatório guardado no `.env` do servidor (`META_WEBHOOK_VERIFY_TOKEN`). O mesmo valor vai no painel.

Existem túneis (Cloudflare, ngrok) que publicam o computador local na internet. Usamos um na primeira validação e abandonamos: eles expõem o sistema inteiro enquanto estão ligados, mudam de endereço a cada uso e fazem os dados dos clientes passarem por mais uma empresa.

### 8.2 Onde fica no painel

No sistema novo de casos de uso não existe mais a página geral de Webhooks. Ela fica dentro de cada caso de uso:

1. Painel do app > **Personalizar o caso de uso "Interagir com os clientes no Messenger from Meta"**.
2. No menu da esquerda, **Configurações da API do Messenger**.
3. A tela **Configuração da API do Messenger** tem três blocos: **1. Configure webhooks**, **2. Gere tokens de acesso** e **3. Faça a análise do app**.

### 8.3 Verificar e salvar

No bloco **1. Configure webhooks**:
1. **URL de callback:** `https://<subdomínio>/webhooks/meta/`.
2. **Verificar token:** o mesmo texto do `.env`.
3. Deixe desmarcado "Anexe um certificado de cliente".
4. Clique em **Verificar e salvar**. A Meta chama o endereço na hora; se o sistema devolver o código de verificação, o bloco salva e recolhe.

### 8.4 Testar com um evento de exemplo

1. Abra de novo o bloco 1 (**Ver mais**). Aparece **Campos do webhook**, com as colunas Campo, Versão, Testar e Assinar.
2. Na linha do campo `messages`, clique em **Teste**.
3. Abre a janela **Exemplo do campo messages** com um JSON de exemplo. Clique em **Enviar para servidor** (o botão mostra a versão, por exemplo "Enviar para servidor v27.0").
4. No sistema, confira a entrega. No laboratório: Admin > Webhooks mostra a entrega com assinatura válida e rota `page`.

### 8.5 Receber eventos reais

- Ligue a chave **Assinar** dos campos que interessam (por exemplo, `messages` e `feed`).
- No bloco **2. Gere tokens de acesso**, clique em **Conectar** e conecte a Página ao app.
- Para o WhatsApp, a configuração equivalente fica no caso de uso do WhatsApp (será documentada na Fase 2 do laboratório).

**Cena sugerida para o vídeo:** preencher callback e verify token, clicar em Verificar e salvar, disparar o Teste e mostrar a entrega chegando no sistema.

---

## Etapa 9: conferência no laboratório

Comando: `python manage.py meta_check`. Ele mostra:
- se as variáveis estão preenchidas;
- se o token é válido, de qual app, de que tipo, quando expira e quais permissões tem;
- para cada ativo do `.env`, se o token o alcança. Quando não alcança, diz se falta permissão no caso de uso (Etapa 7) ou atribuição ao usuário do sistema (Etapa 5.2).

---

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| developers.facebook.com mostra "Começar" em vez de "Meus apps" | A conta ainda não é desenvolvedora | Fazer a Etapa 2 |
| "Você não pode fazer essa alteração no momento... dispositivo diferente" | A Meta não reconhece o navegador | Usar o navegador ou celular de costume, ou esperar alguns dias usando o novo |
| Código do email recusado no cadastro de desenvolvedor | Problema conhecido da Meta em 2026, ligado à confiança na conta | Completar o contato do perfil (Etapa 1.3), verificar a empresa (Meta Verified) e tentar com um código novo |
| "Não foi possível enviar o email" em "Atualizar email" | O email já está na conta | Usar um email que ainda não está na conta, ou manter o atual e pedir "Enviar email novamente" |
| SMS da Meta não chega | Muitas tentativas seguidas | Confirmar pelo campo WhatsApp ou esperar algumas horas |
| "Criar um novo ID do app" desabilitado em Configurações do negócio > Apps | Perfil sem contato confirmado ou conta sem cadastro de desenvolvedor | Etapas 1.3 e 2 |
| "invalid System User name" | Nome com termos reservados | Trocar o nome, por exemplo "Empresa API" |
| Permissão não aparece em "Gerar token" | Não foi adicionada ao caso de uso | Etapa 7 e gerar token novo |
| "Verificar e salvar" falha | Servidor fora do ar, certificado HTTPS inválido, DNS ainda não propagado ou verify token diferente | Abrir o endereço no navegador, conferir o registro A do subdomínio e o valor do verify token |

## Roteiro sugerido para o vídeo

1. **Abertura (1 min):** o que vamos montar e por que a Meta exige app, usuário do sistema e webhook.
2. **Portfólio (3 min):** menu de Configurações, Informações da empresa, contato do perfil confirmado pelo WhatsApp, ativos e verificação.
3. **Meta for Developers (2 min):** cadastro e os bloqueios mais comuns.
4. **Criar o app (3 min):** os quatro casos de uso e o portfólio verificado.
5. **App ID e App Secret (1 min):** onde ficam e como guardar com segurança.
6. **Usuário do sistema (4 min):** política, criação, atribuição de ativos e permissões.
7. **Token (2 min):** validade, permissões e o cuidado de copiar uma vez.
8. **Permissões extras (2 min):** personalizar caso de uso.
9. **Webhook (4 min):** servidor com HTTPS, verificar e salvar, teste chegando no sistema.
10. **Fechamento (1 min):** checklist final e próximos passos (WhatsApp com número de teste, Instagram e Página).

## Cuidados ao gravar

- Não mostrar: App Secret, token, verify token, arquivo `.env`, códigos de confirmação, telefones e emails pessoais.
- IDs de Página, Instagram, app e portfólio não são senhas, mas prefira borrar se o vídeo for público.
- Se possível, grave com um portfólio e um app de demonstração e depois apague o app.
